"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Bookmark, Loader2, Pause, Play, RotateCcw, RotateCw, SkipBack, SkipForward, Trash2, Volume2, VolumeX } from "lucide-react";
import { api, type Bookmark as BM } from "@/lib/api";
import { chapterName, formatTime, narratorLabel, prettyTitle } from "@/lib/format";
import { Cover } from "../Cover";
import { IconBtn, Scrubber, SpeedSelect } from "../player/MiniPlayer";
import { isListenable, usePlayer } from "../player/PlayerProvider";
import { Button, ErrorNote, cx, useToast } from "../ui";

export function NowPlayingView() {
  const p = usePlayer();
  const toast = useToast();
  const [marks, setMarks] = useState<BM[]>([]);
  useEffect(() => {
    if (p.book) api.bookmarks(p.book.id).then(setMarks).catch(() => {});
  }, [p.book, p.bookmarkTick]);

  if (!p.book || !p.chapter) {
    return (
      <div className="mx-auto mt-24 max-w-md text-center">
        <h1 className="font-serif text-3xl">Nothing playing</h1>
        <ErrorNote error={p.error} className="mt-4 text-left" />
        <p className="mt-2 text-sm text-muted">Pick a narrated chapter from your <Link href="/" className="text-accent underline">Library</Link>.</p>
      </div>
    );
  }
  const idx = p.playable.findIndex((c) => c.id === p.chapter!.id);
  const chapterMarks = marks.filter((m) => m.chapter_id === p.chapter!.id);

  return (
    <div className="fade-in mx-auto grid max-w-5xl gap-12 lg:grid-cols-[minmax(0,1fr)_320px]">
      <div className="flex flex-col items-center text-center">
        <div className="relative w-64 sm:w-72">
          <Cover id={p.book.id} title={p.book.title} author={p.book.author} hasCover={p.book.has_cover} size="lg" className="w-full" />
        </div>
        {p.book.chapter_count > 1 && (
          <div className="mt-8 text-[13px] font-medium uppercase tracking-wide text-muted">Chapter {p.chapter.position + 1} of {p.book.chapter_count}</div>
        )}
        <Link href={`/books/${p.book.id}`} className={cx("text-[22px] font-semibold tracking-tight hover:opacity-70 [overflow-wrap:anywhere] sm:text-[28px]", p.book.chapter_count > 1 ? "mt-2" : "mt-8")}>
          {prettyTitle(p.book.title)}
        </Link>
        {(p.book.chapter_count > 1 || p.book.author) && (
          <div className="mt-1 text-[17px] text-accent">
            {[p.book.chapter_count > 1 ? p.chapter.title : null, p.book.author || null].filter(Boolean).join(" · ")}
          </div>
        )}
        {p.chapter.status.narrator && (
          <div className="mt-2 text-[13px] text-muted">Read by {narratorLabel(p.chapter.status.narrator)}</div>
        )}

        <div className="mt-10 w-full max-w-xl">
          <div className="relative">
            <Scrubber />
            {p.duration > 0 && chapterMarks.map((m) => (
              <button key={m.id} onClick={() => p.seek(m.position_s)} aria-label={`Jump to bookmark at ${formatTime(m.position_s)}`}
                className="absolute -top-3 size-2 -translate-x-1/2 rounded-full bg-accent" style={{ left: `${(m.position_s / p.duration) * 100}%` }} />
            ))}
          </div>
          <div className="mt-2 flex justify-between text-xs tabular-nums text-muted">
            <span>{formatTime(p.time)}</span>
            <span>-{formatTime(Math.max(0, p.duration - p.time))}</span>
          </div>
        </div>

        <div className="mt-6 flex items-center gap-3">
          <IconBtn label="Previous chapter" onClick={p.prev} className="size-11"><SkipBack className="size-5" /></IconBtn>
          <IconBtn label="Back 15 seconds" onClick={() => p.skip(-15)} className="size-11"><RotateCcw className="size-5" /></IconBtn>
          <button onClick={p.toggle} aria-label={p.playing ? "Pause" : "Play"}
            className="press grid size-16 place-items-center rounded-full text-ink transition hover:bg-fill">
            {(p.loading || p.waiting) && p.playing ? <Loader2 className="size-6 animate-spin" /> : p.playing ? <Pause className="size-9 fill-current" /> : <Play className="ml-1 size-9 fill-current" />}
          </button>
          <IconBtn label="Forward 30 seconds" onClick={() => p.skip(30)} className="size-11"><RotateCw className="size-5" /></IconBtn>
          <IconBtn label="Next chapter" onClick={p.next} disabled={idx >= p.playable.length - 1} className="size-11"><SkipForward className="size-5" /></IconBtn>
        </div>

        <div className="mt-6 flex flex-wrap items-center justify-center gap-4">
          <SpeedSelect />
          <div className="flex items-center gap-2">
            <IconBtn label={p.muted ? "Unmute" : "Mute"} onClick={p.toggleMute}>{p.muted ? <VolumeX className="size-4" /> : <Volume2 className="size-4" />}</IconBtn>
            <input type="range" min={0} max={1} step={0.01} value={p.muted ? 0 : p.volume} aria-label="Volume" className="scrub w-28"
              onChange={(e) => p.setVolume(Number(e.target.value))} style={{ ["--pct" as string]: `${(p.muted ? 0 : p.volume) * 100}%` }} />
          </div>
          <Button size="sm" onClick={() => p.addBookmark().then(() => toast("ok", `Bookmarked at ${formatTime(p.time)}`))}><Bookmark className="size-3.5" />Bookmark</Button>
        </div>
        {p.waiting && <p className="mt-4 flex items-center gap-2 text-sm text-accent"><Loader2 className="size-4 animate-spin" />Generating the next part — playback continues automatically.</p>}
        {p.live && !p.waiting && <p className="mt-4 text-xs text-faint">Playing while the chapter is still being generated. Total length is an estimate until it finishes.</p>}
        <ErrorNote error={p.error} className="mt-6" />
        <p className="mt-8 text-[11px] text-faint">
          Space play/pause · ←/→ back 15s / forward 30s · Shift+←/→ chapters · [ ] speed · M mute · B bookmark. Media keys work too.
        </p>
      </div>

      <aside className="space-y-8">
        <section>
          <h2 className="mb-3 text-xs font-medium uppercase tracking-[0.15em] text-faint">Chapters</h2>
          <div className="space-y-0.5">
            {p.book.chapters?.map((c, i) => (
              <button key={c.id} disabled={!isListenable(c)} onClick={() => p.load(p.book!.id, c.id, 0, true)}
                className={cx("flex w-full items-center gap-3 rounded-lg px-3 py-2 text-left text-sm transition disabled:opacity-35",
                  c.id === p.chapter!.id ? "bg-fill-2 text-ink" : "text-muted enabled:hover:bg-fill enabled:hover:text-ink")}>
                <span className="w-5 text-[11px] text-faint">{i + 1}</span>
                <span className="flex-1 truncate">{chapterName(c.title, p.book!.title, p.book!.chapter_count)}</span>
                <span className="text-[11px] text-faint">{c.status.duration_s ? formatTime(c.status.duration_s) : "—"}</span>
              </button>
            ))}
          </div>
        </section>
        <section>
          <h2 className="mb-3 text-xs font-medium uppercase tracking-[0.15em] text-faint">Bookmarks</h2>
          {marks.length === 0 ? <p className="text-sm text-faint">Press B while listening to mark a moment.</p> : (
            <div className="space-y-0.5">
              {marks.map((m) => (
                <div key={m.id} className="group flex items-center gap-2 rounded-lg px-3 py-2 text-sm hover:bg-fill">
                  <button className="flex-1 truncate text-left text-muted hover:text-ink" onClick={() => p.load(p.book!.id, m.chapter_id, m.position_s, true)}>
                    {chapterName(m.chapter_title, p.book!.title, p.book!.chapter_count)} · {formatTime(m.position_s)}
                  </button>
                  <button aria-label="Delete bookmark" onClick={() => api.deleteBookmark(m.id).then(() => setMarks(marks.filter((x) => x.id !== m.id)))}
                    className="text-faint opacity-0 hover:text-bad group-hover:opacity-100"><Trash2 className="size-3.5" /></button>
                </div>
              ))}
            </div>
          )}
        </section>
      </aside>
    </div>
  );
}
