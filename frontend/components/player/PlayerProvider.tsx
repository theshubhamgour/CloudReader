"use client";

// One <audio> element for the whole app, mounted in the root layout, so playback
// continues while you move between pages. Progress is saved to the backend every
// few seconds, on pause/seek/chapter change, and with sendBeacon when the tab closes.
//
// Two sources:
//  • finished chapters play the assembled, loudness-normalised chapter file;
//  • chapters still generating play "live": each segment as soon as it is ready,
//    waiting briefly when playback catches up with generation (like buffering).

import { createContext, useCallback, useContext, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { api, audioUrl, segmentAudioUrl, type Book, type Chapter, type Segment } from "@/lib/api";

const SAVE_EVERY_MS = 5000;
const POLL_MS = 1500;
const CHARS_PER_SECOND = 12.5; // measured Gemini narration rate, used only to estimate unfinished audio
export const SPEEDS = [0.75, 0.9, 1, 1.1, 1.25, 1.5, 1.75, 2, 2.5];

/** A chapter you can start listening to now (finished, or with audio arriving). */
export function isListenable(c: Chapter) {
  return c.status.audio_ready || c.status.state === "generating" || c.status.segments_completed > 0;
}

interface PlayerState {
  book: Book | null;
  chapter: Chapter | null;
  playable: Chapter[];
  playing: boolean;
  loading: boolean;
  /** Live mode: playback has caught up with generation and is waiting for the next part. */
  waiting: boolean;
  live: boolean;
  time: number;
  duration: number;
  rate: number;
  volume: number;
  muted: boolean;
  error: string | null;
}

interface PlayerApi extends PlayerState {
  load: (bookId: number, chapterId?: number, startAt?: number, autoplay?: boolean) => Promise<void>;
  toggle: () => void;
  play: () => void;
  pause: () => void;
  seek: (t: number) => void;
  skip: (delta: number) => void;
  setRate: (r: number) => void;
  setVolume: (v: number) => void;
  toggleMute: () => void;
  next: () => void;
  prev: () => void;
  refresh: () => Promise<void>;
  addBookmark: () => Promise<void>;
  bookmarkTick: number;
}

interface Live {
  chapterId: number;
  segs: Segment[];
  index: number; // segment currently loaded
  offsets: number[]; // chapter time at which each ready segment starts
}

const Ctx = createContext<PlayerApi | null>(null);

export function usePlayer() {
  const v = useContext(Ctx);
  if (!v) throw new Error("usePlayer must be used inside PlayerProvider");
  return v;
}

function readyPrefix(segs: Segment[]) {
  const out: Segment[] = [];
  for (const s of segs) {
    if (s.status !== "completed" || !s.has_audio || s.duration_s == null) break;
    out.push(s);
  }
  return out;
}

/** If nothing is generating this chapter any more, explain why playback can't continue. */
async function stalledReason(chapterId: number): Promise<string | null> {
  const ch = await api.chapter(chapterId);
  if (ch.status.active_job_id) return null;
  const job = (await api.jobs()).find((j) => j.chapter_id === chapterId);
  return job?.error ?? "Generation of this chapter stopped before it finished. Open the Studio to continue it.";
}

function liveDuration(segs: Segment[]) {
  return segs.reduce((t, s) => t + (s.has_audio && s.duration_s != null ? s.duration_s : s.tts_text.length / CHARS_PER_SECOND), 0);
}

export function PlayerProvider({ children }: { children: React.ReactNode }) {
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const [s, setS] = useState<PlayerState>({
    book: null, chapter: null, playable: [], playing: false, loading: false, waiting: false, live: false,
    time: 0, duration: 0, rate: 1, volume: 1, muted: false, error: null,
  });
  const [bookmarkTick, setBookmarkTick] = useState(0);
  // Latest state for event handlers registered once (audio events, media keys, beacons).
  const stateRef = useRef(s);
  useLayoutEffect(() => { stateRef.current = s; });
  const lastSave = useRef(0);
  const pendingSeek = useRef<number | null>(null);
  const autoplayRef = useRef(false);
  const liveRef = useRef<Live | null>(null);
  const pollRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const wantPlay = useRef(false); // user intends playback (survives waiting for generation)

  const patch = (p: Partial<PlayerState>) => setS((prev) => ({ ...prev, ...p }));
  const clearPoll = () => { if (pollRef.current) clearTimeout(pollRef.current); pollRef.current = null; };

  /** Position within the chapter, in seconds (live mode adds the segment's offset). */
  const chapterTime = useCallback(() => {
    const a = audioRef.current;
    const L = liveRef.current;
    if (!a) return 0;
    return L && L.index >= 0 ? (L.offsets[L.index] ?? 0) + (a.currentTime || 0) : a.currentTime || 0;
  }, []);

  const save = useCallback((beacon = false) => {
    const { book, chapter, rate } = stateRef.current;
    if (!book || !chapter || !audioRef.current) return;
    const body = { chapter_id: chapter.id, position_s: Math.max(0, chapterTime()), playback_rate: rate };
    lastSave.current = Date.now();
    if (beacon && navigator.sendBeacon) {
      navigator.sendBeacon(`/api/books/${book.id}/progress`, new Blob([JSON.stringify(body)], { type: "application/json" }));
    } else {
      api.saveProgress(book.id, body.chapter_id, body.position_s, body.playback_rate).catch(() => {});
    }
  }, [chapterTime]);

  const loadSrc = (url: string, seekTo: number, autoplay: boolean) => {
    const a = audioRef.current!;
    pendingSeek.current = seekTo;
    autoplayRef.current = autoplay;
    a.src = url;
    a.load();
  };

  // ---------------------------------------------------------------- live mode

  const refreshLive = async (L: Live) => {
    L.segs = await api.segments(L.chapterId);
    const prefix = readyPrefix(L.segs);
    L.offsets = prefix.reduce<number[]>((acc, seg, i) => (acc.push(i ? acc[i - 1] + prefix[i - 1].duration_s! : 0), acc), []);
    return prefix;
  };

  // Declared via ref so live helpers and chapter navigation can call each other.
  const advanceChapterRef = useRef<(autoplay: boolean) => Promise<void>>(async () => {});
  const playLiveRef = useRef<(t: number, autoplay: boolean) => Promise<void>>(async () => {});
  const continueLiveRef = useRef<() => Promise<void>>(async () => {});

  const playLiveAt = useCallback(async (t: number, autoplay: boolean) => {
    const L = liveRef.current;
    if (!L) return;
    clearPoll();
    const prefix = await refreshLive(L);
    if (liveRef.current !== L) return; // chapter changed meanwhile
    const failed = L.segs.find((x) => x.status === "failed");
    if (!prefix.length) {
      if (failed && failed.position === 0) {
        patch({ waiting: false, loading: false, error: `Generation failed: ${failed.error ?? "unknown error"}` });
        return;
      }
      const stalled = await stalledReason(L.chapterId);
      if (stalled) { patch({ waiting: false, loading: false, playing: false, error: stalled }); return; }
      wantPlay.current = autoplay;
      patch({ waiting: true, loading: false, playing: autoplay, duration: liveDuration(L.segs) });
      pollRef.current = setTimeout(() => playLiveRef.current(t, wantPlay.current), POLL_MS);
      return;
    }
    let i = prefix.findIndex((_, k) => t < L.offsets[k] + prefix[k].duration_s!);
    if (i < 0) i = prefix.length - 1;
    L.index = i;
    patch({ waiting: false, live: true, duration: liveDuration(L.segs), error: null });
    loadSrc(segmentAudioUrl(prefix[i].id), Math.max(0, t - L.offsets[i]), autoplay);
  }, []);

  /** Called when a live segment ends (or while waiting for the next one). */
  const continueLive = useCallback(async () => {
    const L = liveRef.current;
    if (!L) return;
    clearPoll();
    const endedAt = (L.offsets[L.index] ?? 0) + (L.segs[L.index]?.duration_s ?? 0);
    const prefix = await refreshLive(L);
    if (liveRef.current !== L) return;
    const nextIdx = L.index + 1;
    if (nextIdx < prefix.length) {
      L.index = nextIdx;
      patch({ waiting: false, duration: liveDuration(L.segs) });
      loadSrc(segmentAudioUrl(prefix[nextIdx].id), 0, true);
      return;
    }
    if (prefix.length === L.segs.length) {
      // Chapter finished generating and we've heard all of it.
      save();
      await advanceChapterRef.current(true);
      return;
    }
    const blocked = L.segs[nextIdx];
    if (blocked?.status === "failed") {
      patch({ waiting: false, playing: false, error: "The next part failed to generate. Open the Studio and press Retry failed." });
      return;
    }
    const stalled = await stalledReason(L.chapterId);
    if (stalled) { patch({ waiting: false, playing: false, error: stalled }); return; }
    wantPlay.current = true;
    patch({ waiting: true, playing: true, time: endedAt, duration: liveDuration(L.segs) });
    pollRef.current = setTimeout(() => continueLiveRef.current(), POLL_MS);
  }, [save]);
  useEffect(() => { playLiveRef.current = playLiveAt; continueLiveRef.current = continueLive; }, [playLiveAt, continueLive]);

  // ---------------------------------------------------------------- sources

  const setSource = useCallback(async (chapter: Chapter, startAt: number, autoplay: boolean) => {
    clearPoll();
    liveRef.current = null;
    patch({ chapter, time: startAt, loading: true, waiting: false, error: null });
    if (chapter.status.audio_ready) {
      patch({ live: false, duration: chapter.status.duration_s ?? 0 });
      // Cache-bust per duration so a regenerated chapter isn't served stale.
      loadSrc(`${audioUrl(chapter.id)}?v=${Math.round((chapter.status.duration_s ?? 0) * 1000)}`, startAt, autoplay);
      return;
    }
    liveRef.current = { chapterId: chapter.id, segs: [], index: -1, offsets: [] };
    patch({ live: true });
    await playLiveAt(startAt, autoplay);
  }, [playLiveAt]);

  const load = useCallback(async (bookId: number, chapterId?: number, startAt = 0, autoplay = true) => {
    save();
    try {
      const book = await api.book(bookId);
      const playable = (book.chapters ?? []).filter(isListenable);
      const chapter = playable.find((c) => c.id === chapterId) ?? playable[0];
      patch({ book, playable });
      if (!chapter) {
        patch({ chapter: null, error: "No chapter of this book has audio yet." });
        return;
      }
      const rate = book.progress?.playback_rate ?? stateRef.current.rate;
      patch({ rate });
      wantPlay.current = autoplay;
      await setSource(chapter, startAt, autoplay);
      api.saveProgress(bookId, chapter.id, startAt, rate).catch(() => {});
    } catch (e) {
      patch({ error: (e as Error).message });
    }
  }, [save, setSource]);

  const refresh = useCallback(async () => {
    const { book, chapter } = stateRef.current;
    if (!book) return;
    const fresh = await api.book(book.id);
    const playable = (fresh.chapters ?? []).filter(isListenable);
    patch({ book: fresh, playable, chapter: playable.find((c) => c.id === chapter?.id) ?? chapter });
  }, []);

  /** Move to the next chapter in reading order that has (or is getting) audio. */
  const advanceChapter = useCallback(async (autoplay: boolean) => {
    const { book, chapter } = stateRef.current;
    if (!book || !chapter) return;
    const fresh = await api.book(book.id);
    const all = fresh.chapters ?? [];
    const playable = all.filter(isListenable);
    patch({ book: fresh, playable });
    const next = all.find((c) => c.position > chapter.position && isListenable(c));
    if (!next) {
      patch({ playing: false, waiting: false });
      return;
    }
    await setSource(next, 0, autoplay);
    api.saveProgress(book.id, next.id, 0, stateRef.current.rate).catch(() => {});
  }, [setSource]);
  useEffect(() => { advanceChapterRef.current = advanceChapter; }, [advanceChapter]);

  // Restore the last listening position on app start (paused — never autoplay).
  useEffect(() => {
    api.latestProgress().then((p) => {
      if (p.book_id && p.chapter_id) load(p.book_id, p.chapter_id, p.position_s ?? 0, false);
    }).catch(() => {});
  }, [load]);

  // ---------------------------------------------------------------- audio element events

  useEffect(() => {
    const a = audioRef.current!;
    const onTime = () => {
      patch({ time: chapterTime() });
      if (!a.paused && Date.now() - lastSave.current > SAVE_EVERY_MS) save();
    };
    const onMeta = () => {
      if (pendingSeek.current != null) {
        a.currentTime = Math.min(pendingSeek.current, Math.max(0, a.duration - 0.25));
        pendingSeek.current = null;
      }
      a.playbackRate = stateRef.current.rate;
      if (!liveRef.current) patch({ duration: a.duration });
      patch({ loading: false });
      if (autoplayRef.current) a.play().catch(() => {});
    };
    const onPlay = () => { wantPlay.current = true; patch({ playing: true }); };
    const onPause = () => {
      if (a.ended) return; // segment/chapter boundary, not a user pause
      wantPlay.current = false;
      patch({ playing: false });
      save();
    };
    const onEnded = () => {
      if (liveRef.current) { continueLive(); return; }
      save();
      advanceChapterRef.current(true);
    };
    const onError = () => {
      if (!a.getAttribute("src")) return;
      patch({ loading: false, playing: false, error: "Couldn't load the audio. Is the backend running?" });
    };
    const onWaiting = () => patch({ loading: true });
    const onCanPlay = () => patch({ loading: false });
    const onVisibility = () => { if (document.visibilityState === "hidden") save(true); };
    const onHide = () => save(true);
    a.addEventListener("timeupdate", onTime);
    a.addEventListener("loadedmetadata", onMeta);
    a.addEventListener("play", onPlay);
    a.addEventListener("pause", onPause);
    a.addEventListener("ended", onEnded);
    a.addEventListener("error", onError);
    a.addEventListener("waiting", onWaiting);
    a.addEventListener("canplay", onCanPlay);
    window.addEventListener("pagehide", onHide);
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      a.removeEventListener("timeupdate", onTime);
      a.removeEventListener("loadedmetadata", onMeta);
      a.removeEventListener("play", onPlay);
      a.removeEventListener("pause", onPause);
      a.removeEventListener("ended", onEnded);
      a.removeEventListener("error", onError);
      a.removeEventListener("waiting", onWaiting);
      a.removeEventListener("canplay", onCanPlay);
      window.removeEventListener("pagehide", onHide);
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [save, chapterTime, continueLive]);

  // ---------------------------------------------------------------- controls

  const play = useCallback(() => {
    wantPlay.current = true;
    if (stateRef.current.waiting) { patch({ playing: true }); return; }
    audioRef.current?.play().catch(() => {});
  }, []);
  const pause = useCallback(() => {
    wantPlay.current = false;
    audioRef.current?.pause();
    if (stateRef.current.waiting) patch({ playing: false });
  }, []);
  const toggle = useCallback(() => {
    const a = audioRef.current;
    if (!a || !stateRef.current.chapter) return;
    if (stateRef.current.waiting) { wantPlay.current = !wantPlay.current; patch({ playing: wantPlay.current }); return; }
    if (a.paused) a.play().catch(() => {}); else a.pause();
  }, []);

  const seek = useCallback((t: number) => {
    const a = audioRef.current;
    if (!a) return;
    const L = liveRef.current;
    if (L) {
      const prefix = readyPrefix(L.segs);
      const avail = prefix.reduce((x, seg) => x + seg.duration_s!, 0);
      const target = Math.max(0, Math.min(t, Math.max(0, avail - 0.25)));
      const i = L.index;
      const start = L.offsets[i] ?? 0;
      if (i >= 0 && target >= start && target < start + (prefix[i]?.duration_s ?? 0)) {
        a.currentTime = target - start;
      } else {
        playLiveAt(target, !a.paused || wantPlay.current);
      }
      patch({ time: target });
      save();
      return;
    }
    if (!isFinite(a.duration)) return;
    a.currentTime = Math.max(0, Math.min(t, a.duration - 0.05));
    patch({ time: a.currentTime });
    save();
  }, [save, playLiveAt]);
  const skip = useCallback((d: number) => seek(chapterTime() + d), [seek, chapterTime]);
  const setRate = useCallback((r: number) => {
    if (audioRef.current) audioRef.current.playbackRate = r;
    patch({ rate: r });
    setTimeout(() => save(), 0);
  }, [save]);
  const setVolume = useCallback((v: number) => {
    if (audioRef.current) { audioRef.current.volume = v; audioRef.current.muted = false; }
    patch({ volume: v, muted: false });
  }, []);
  const toggleMute = useCallback(() => {
    const a = audioRef.current;
    if (!a) return;
    a.muted = !a.muted;
    patch({ muted: a.muted });
  }, []);
  const go = useCallback(async (dir: 1 | -1) => {
    const { playable, chapter } = stateRef.current;
    const a = audioRef.current;
    // "Previous" restarts the chapter if you're more than 5s in, like most players.
    if (dir === -1 && chapterTime() > 5) { seek(0); return; }
    const i = playable.findIndex((c) => c.id === chapter?.id) + dir;
    if (i >= 0 && i < playable.length) {
      save();
      await setSource(playable[i], 0, !!a && (!a.paused || wantPlay.current));
    }
  }, [save, seek, setSource, chapterTime]);
  const next = useCallback(() => { go(1); }, [go]);
  const prev = useCallback(() => { go(-1); }, [go]);

  const addBookmark = useCallback(async () => {
    const { book, chapter } = stateRef.current;
    if (!book || !chapter) return;
    await api.addBookmark(book.id, chapter.id, chapterTime());
    setBookmarkTick((t) => t + 1);
  }, [chapterTime]);

  // macOS Now Playing / media keys via the Media Session API.
  useEffect(() => {
    if (!("mediaSession" in navigator) || !s.chapter || !s.book) return;
    navigator.mediaSession.metadata = new MediaMetadata({
      title: s.chapter.title, artist: s.book.author || "CloudReader", album: s.book.title,
      artwork: s.book.has_cover ? [{ src: `/api/books/${s.book.id}/cover` }] : [],
    });
    const ms = navigator.mediaSession;
    ms.setActionHandler("play", play);
    ms.setActionHandler("pause", pause);
    ms.setActionHandler("seekbackward", () => skip(-15));
    ms.setActionHandler("seekforward", () => skip(30));
    ms.setActionHandler("previoustrack", prev);
    ms.setActionHandler("nexttrack", next);
    ms.setActionHandler("seekto", (d) => { if (d.seekTime != null) seek(d.seekTime); });
  }, [s.chapter, s.book, play, pause, skip, prev, next, seek]);

  // Global keyboard shortcuts (ignored while typing in a field).
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement;
      if (t.closest("input, textarea, select, [contenteditable=true]") || e.metaKey || e.ctrlKey || e.altKey) return;
      if (!stateRef.current.chapter) return;
      const r = stateRef.current.rate;
      switch (e.key) {
        case " ": if (t.closest("button")) return; e.preventDefault(); toggle(); break;
        case "k": toggle(); break;
        case "ArrowLeft": e.preventDefault(); if (e.shiftKey) prev(); else skip(-15); break;
        case "ArrowRight": e.preventDefault(); if (e.shiftKey) next(); else skip(30); break;
        case "j": skip(-15); break;
        case "l": skip(30); break;
        case "[": setRate(SPEEDS[Math.max(0, SPEEDS.indexOf(r) - 1)] ?? 1); break;
        case "]": setRate(SPEEDS[Math.min(SPEEDS.length - 1, SPEEDS.indexOf(r) + 1)] ?? 1); break;
        case "m": toggleMute(); break;
        case "b": addBookmark(); break;
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [toggle, prev, next, skip, setRate, toggleMute, addBookmark]);

  useEffect(() => clearPoll, []);

  const value = useMemo<PlayerApi>(() => ({
    ...s, load, toggle, play, pause, seek, skip, setRate, setVolume, toggleMute, next, prev, refresh, addBookmark, bookmarkTick,
  }), [s, load, toggle, play, pause, seek, skip, setRate, setVolume, toggleMute, next, prev, refresh, addBookmark, bookmarkTick]);

  return (
    <Ctx.Provider value={value}>
      {children}
      <audio ref={audioRef} preload="auto" />
    </Ctx.Provider>
  );
}
