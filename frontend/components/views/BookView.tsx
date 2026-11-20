"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { AudioLines, BookmarkPlus, Check, CheckCircle2, ChevronLeft, Download, Loader2, Pause, Pencil, Play, Square, Trash2, X } from "lucide-react";
import { api, bookExportUrl, exportUrl, type Book, type Bookmark, type Chapter, type VoiceSettings } from "@/lib/api";
import { chapterName, formatDuration, formatTime, formatUsd, prettyTitle } from "@/lib/format";
import { Cover } from "../Cover";
import { isListenable, usePlayer } from "../player/PlayerProvider";
import { Button, ErrorNote, Group, ProgressBar, SectionFooter, SectionTitle, Skeleton, cx, useToast } from "../ui";

export function BookView() {
  const { id } = useParams<{ id: string }>();
  const bookId = Number(id);
  const [book, setBook] = useState<Book | null>(null);
  const [voice, setVoice] = useState<VoiceSettings | null>(null);
  const [cost, setCost] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [starting, setStarting] = useState<number | "book" | null>(null);
  const [marks, setMarks] = useState<Bookmark[]>([]);
  const player = usePlayer();
  const toast = useToast();
  const router = useRouter();

  const load = useCallback(() => api.book(bookId).then(setBook).catch((e) => setError(e.message)), [bookId]);
  useEffect(() => {
    load();
    api.voiceSettings().then(setVoice).catch(() => {});
  }, [load]);
  const loadMarks = useCallback(() => api.bookmarks(bookId).then(setMarks).catch(() => {}), [bookId]);
  useEffect(() => { loadMarks(); }, [loadMarks, player.bookmarkTick]);
  // While audio is being prepared, refresh so chapter status updates.
  useEffect(() => {
    if (!book?.any_generating) return;
    const t = setInterval(load, 2500);
    return () => clearInterval(t);
  }, [book?.any_generating, load]);

  const chapters = book?.chapters ?? [];
  const readyCount = chapters.filter((c) => c.status.audio_ready).length;
  const allReady = chapters.length > 0 && readyCount === chapters.length;
  const engineOk = voice ? voice.engines[voice.engine].available : true;
  const blocked = voice ? voice.engines[voice.engine].blocked : null;
  const useLocal = async () => {
    try { setVoice(await api.setVoice("local")); toast("ok", "Switched to the free local voice"); }
    catch (e) { toast("error", (e as Error).message); }
  };

  // Show what Gemini narration of the rest would cost (local voice is free).
  useEffect(() => {
    if (!book || !voice || voice.engine !== "gemini" || allReady || !engineOk) return;
    api.bookPlan(book.id, voice.profile_id).then((p) => setCost(p.estimate.cost_usd)).catch(() => setCost(null));
  }, [book?.id, voice, allReady, engineOk]); // eslint-disable-line react-hooks/exhaustive-deps

  if (error) return <ErrorNote error={error} />;
  if (!book) return <div className="space-y-4"><Skeleton className="h-72" /><Skeleton className="h-96" /></div>;

  const isThisBook = player.book?.id === book.id;
  const nowId = isThisBook ? player.chapter?.id : undefined;
  const name = prettyTitle(book.title);

  /** Play from a chapter (or where you left off). Starts narration first if needed. */
  const listen = async (chapter?: Chapter) => {
    const target = chapter ?? chapters.find((c) => c.id === book.progress?.chapter_id) ?? chapters[0];
    if (!target) return;
    const startAt = book.progress?.chapter_id === target.id ? book.progress.position_s : 0;
    const needsNarration = chapters.some((c) => !c.status.audio_ready && c.status.state !== "generating");
    if (needsNarration && !book.any_generating) {
      if (!engineOk) {
        toast("error", "The Gemini voice needs an API key. Add it in Settings, or switch to the free local voice.");
        return;
      }
      if (blocked) { toast("error", blocked); return; }
      setStarting(chapter ? chapter.id : "book");
      try {
        await api.generateBook(book.id, voice?.profile_id, target.id);
        await load();
      } catch (e) {
        toast("error", (e as Error).message);
        api.voiceSettings().then(setVoice).catch(() => {}); // e.g. the daily limit was just reached
        setStarting(null);
        return;
      }
      setStarting(null);
    }
    player.load(book.id, target.id, startAt, true);
  };

  /** Save the current spot: the live player position, or where you last stopped. */
  const canBookmark = (isThisBook && !!player.chapter) || !!book.progress;
  const addMark = async () => {
    try {
      if (isThisBook && player.chapter) {
        await player.addBookmark(); // refreshes the list through bookmarkTick
        toast("ok", `Bookmarked at ${formatTime(player.time)}`);
      } else if (book.progress) {
        await api.addBookmark(book.id, book.progress.chapter_id, book.progress.position_s);
        await loadMarks();
        toast("ok", `Bookmarked at ${formatTime(book.progress.position_s)}`);
      }
    } catch (e) { toast("error", (e as Error).message); }
  };
  const removeMark = async (m: Bookmark) => {
    try { await api.deleteBookmark(m.id); setMarks((xs) => xs.filter((x) => x.id !== m.id)); toast("ok", "Bookmark deleted"); }
    catch (e) { toast("error", (e as Error).message); }
  };

  const mainPlay = () => (isThisBook && player.chapter ? player.toggle() : listen());
  const playing = isThisBook && player.playing;

  return (
    <div className="fade-in">
      <Link href="/" className="-ml-1.5 mb-6 inline-flex items-center text-[17px] text-accent hover:opacity-70">
        <ChevronLeft className="size-6" strokeWidth={2.2} />Library
      </Link>

      {/* ------------------------------------------------ header */}
      <div className="flex flex-col items-center gap-7 text-center sm:flex-row sm:items-end sm:gap-10 sm:text-left">
        <Cover id={book.id} title={book.title} author={book.author} hasCover={book.has_cover} size="lg" className="w-48 shrink-0 sm:w-60" />
        <div className="min-w-0 flex-1 pb-1">
          <TitleEditor book={book} name={name} onSaved={(b) => {
            setBook((cur) => (cur ? { ...cur, title: b.title } : cur));
            if (isThisBook) player.refresh(); // keep the player's title in step
          }} />
          {book.author && <div className="mt-1 text-[20px] text-accent">{book.author}</div>}
          <div className="mt-2 text-[13px] font-medium uppercase tracking-wide text-muted">
            Audiobook · {chapters.length} {chapters.length === 1 ? "chapter" : "chapters"} · {formatDuration(book.estimated_minutes)}
          </div>

          <div className="mt-6 flex items-center justify-center gap-3 sm:justify-start">
            <button onClick={mainPlay} disabled={starting !== null}
              className="press inline-flex h-12 min-w-40 items-center justify-center gap-2 rounded-full bg-accent px-7 text-[17px] font-semibold text-accent-ink hover:brightness-110 disabled:opacity-60">
              {starting === "book" ? <Loader2 className="size-5 animate-spin" />
                : playing ? <Pause className="size-5 fill-current" /> : <Play className="size-5 fill-current" />}
              {starting === "book" ? "Starting…" : playing ? "Pause" : book.progress ? "Resume" : "Play"}
            </button>
            <button onClick={addMark} disabled={!canBookmark}
              title={canBookmark ? "Bookmark your current spot" : "Start listening first, then bookmark your spot"}
              className="press inline-flex h-12 items-center gap-2 rounded-full bg-accent/12 px-5 text-[17px] font-semibold text-accent hover:bg-accent/18 disabled:opacity-40">
              <BookmarkPlus className="size-5" />Bookmark
            </button>
          </div>

          {blocked && !allReady && !book.any_generating ? (
            <div className="mx-auto mt-5 max-w-md rounded-xl bg-warn/10 px-4 py-3 text-left text-[15px] text-warn sm:mx-0">
              <p>{blocked}</p>
              <Button size="sm" variant="primary" className="mt-3" onClick={useLocal}>Use the Free Local Voice</Button>
            </div>
          ) : (
            <StatusLine book={book} readyCount={readyCount} allReady={allReady} voice={voice} cost={cost}
              onStop={async () => {
                const r = await api.cancelBook(book.id);
                toast("info", `Stopped preparing ${r.cancelled} chapter(s)`);
                load();
              }} />
          )}
        </div>
      </div>

      <div className="mx-auto mt-12 max-w-3xl space-y-9">
        {/* ------------------------------------------------ bookmarks */}
        {marks.length > 0 && (
          <section>
            <SectionTitle>Bookmarks</SectionTitle>
            <Group>
              {marks.map((m) => (
                <div key={m.id} className="flex items-center">
                  <button onClick={() => player.load(book.id, m.chapter_id, m.position_s, true)}
                    className="flex min-w-0 flex-1 items-center gap-3 py-3 pl-4 text-left transition hover:bg-fill">
                    <span className="grid size-8 shrink-0 place-items-center rounded-full bg-accent text-accent-ink">
                      <Play className="ml-0.5 size-3.5 fill-current" />
                    </span>
                    <span className="min-w-0">
                      <span className="block truncate text-[15px]">{chapterName(m.chapter_title, book.title, chapters.length)}</span>
                      <span className="block text-[13px] text-muted">{formatTime(m.position_s)}{m.label ? ` · ${m.label}` : ""}</span>
                    </span>
                  </button>
                  <button onClick={() => removeMark(m)} aria-label={`Delete bookmark at ${formatTime(m.position_s)}`} title="Delete Bookmark"
                    className="press mr-3 grid size-8 shrink-0 place-items-center rounded-full bg-fill text-muted hover:bg-bad/15 hover:text-bad">
                    <X className="size-4" strokeWidth={2.5} />
                  </button>
                </div>
              ))}
            </Group>
            <SectionFooter>Tap a bookmark to continue from that spot.</SectionFooter>
          </section>
        )}

        {/* ------------------------------------------------ chapters */}
        <section>
          <SectionTitle>Chapters</SectionTitle>
          <Group>
            {chapters.map((c, i) => {
              const current = nowId === c.id;
              return (
                <div key={c.id} className="flex items-center">
                  <button onClick={() => (current ? player.toggle() : listen(c))} disabled={starting !== null}
                    aria-label={current && player.playing ? `Pause ${c.title}` : `Play ${c.title}`}
                    className="flex min-w-0 flex-1 items-center gap-4 py-3 pl-4 pr-2 text-left transition hover:bg-fill disabled:opacity-60">
                    <span className={cx("w-6 shrink-0 text-center text-[15px] tabular-nums", current ? "text-accent" : "text-muted")}>
                      {starting === c.id ? <Loader2 className="mx-auto size-4 animate-spin" />
                        : current && player.playing ? <AudioLines className="mx-auto size-4" /> : i + 1}
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className={cx("block truncate text-[15px]", current && "font-semibold text-accent")}>{chapterName(c.title, book.title, chapters.length)}</span>
                      <ChapterStatus c={c} />
                    </span>
                  </button>
                  {c.status.audio_ready && (
                    <a href={exportUrl(c.id)} aria-label={`Download ${c.title}`} title="Download"
                      className="mr-2 grid size-9 place-items-center rounded-full text-muted transition hover:bg-fill hover:text-accent"><Download className="size-4" /></a>
                  )}
                </div>
              );
            })}
          </Group>
        </section>

        {/* ------------------------------------------------ actions */}
        <section>
          <Group>
            <a href={readyCount ? bookExportUrl(book.id) : undefined} aria-disabled={!readyCount}
              className={cx("flex items-center gap-3 px-4 py-3 text-[17px] text-accent transition hover:bg-fill", !readyCount && "pointer-events-none opacity-40")}>
              <Download className="size-5" />Download Audiobook
            </a>
            <button onClick={async () => {
              if (!confirm(`Delete “${name}”?`)) return;
              try { await api.deleteBook(book.id); router.push("/"); } catch (e) { toast("error", (e as Error).message); }
            }} className="flex w-full items-center gap-3 px-4 py-3 text-left text-[17px] text-bad transition hover:bg-fill">
              <Trash2 className="size-5" />Delete Book
            </button>
          </Group>
        </section>
      </div>
    </div>
  );
}

/** The book title, with a pen icon to rename it in place. */
function TitleEditor({ book, name, onSaved }: { book: Book; name: string; onSaved: (b: Book) => void }) {
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState(name);
  const [busy, setBusy] = useState(false);
  const toast = useToast();

  const start = () => { setValue(name); setEditing(true); };
  const save = async () => {
    const title = value.trim();
    if (!title || title === name) { setEditing(false); return; }
    setBusy(true);
    try {
      onSaved(await api.updateBook(book.id, { title }));
      setEditing(false);
      toast("ok", "Book renamed");
    } catch (e) { toast("error", (e as Error).message); } finally { setBusy(false); }
  };

  if (editing) {
    return (
      <div className="flex items-center gap-2">
        <input autoFocus value={value} maxLength={200} aria-label="Book name" disabled={busy}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") save(); if (e.key === "Escape") setEditing(false); }}
          className="min-w-0 flex-1 rounded-xl bg-fill px-3 py-1.5 text-[24px] font-bold tracking-tight text-ink outline-none focus:ring-2 focus:ring-accent/50 sm:text-[32px]" />
        <button onClick={save} disabled={busy || !value.trim()} aria-label="Save name" title="Save"
          className="press grid size-10 shrink-0 place-items-center rounded-full bg-accent text-accent-ink disabled:opacity-40">
          {busy ? <Loader2 className="size-4 animate-spin" /> : <Check className="size-5" strokeWidth={2.6} />}
        </button>
        <button onClick={() => setEditing(false)} disabled={busy} aria-label="Cancel" title="Cancel"
          className="press grid size-10 shrink-0 place-items-center rounded-full bg-fill text-muted hover:text-ink">
          <X className="size-5" strokeWidth={2.4} />
        </button>
      </div>
    );
  }
  return (
    <h1 className="font-serif text-[28px] leading-tight [overflow-wrap:anywhere] sm:text-[40px]">
      {name}
      <button onClick={start} aria-label="Rename book" title="Rename"
        className="press ml-2 inline-grid size-9 translate-y-[-3px] place-items-center rounded-full bg-fill align-middle text-muted transition hover:bg-accent/12 hover:text-accent">
        <Pencil className="size-4" strokeWidth={2.2} />
      </button>
    </h1>
  );
}

function StatusLine({ book, readyCount, allReady, voice, cost, onStop }: {
  book: Book; readyCount: number; allReady: boolean; voice: VoiceSettings | null; cost: number | null; onStop: () => void;
}) {
  const total = book.chapter_count;
  if (allReady) {
    return <p className="mt-4 flex items-center justify-center gap-1.5 text-[15px] text-muted sm:justify-start"><CheckCircle2 className="size-4 text-ok" />Ready to listen</p>;
  }
  if (book.any_generating) {
    return (
      <div className="mx-auto mt-5 max-w-sm text-left sm:mx-0">
        <div className="mb-2 flex items-center justify-between gap-3 text-[13px] text-muted">
          <span className="flex items-center gap-1.5"><Loader2 className="size-3.5 animate-spin" />Preparing audio · {readyCount} of {total}</span>
          <button onClick={onStop} className="flex items-center gap-1 font-medium text-accent hover:opacity-70"><Square className="size-3 fill-current" />Stop</button>
        </div>
        <ProgressBar value={total ? readyCount / total : 0} />
        <p className="mt-2 text-[13px] text-muted">You can listen while the rest is prepared.</p>
      </div>
    );
  }
  if (!voice) return null;
  const ok = voice.engines[voice.engine].available;
  return (
    <p className="mt-4 text-[13px] text-muted">
      {ok ? (
        <>Read by {voice.engine === "gemini" ? `Gemini AI · ${voice.voice}` : `Local Voice · ${voice.voice}`}
          {voice.engine === "gemini" && cost != null && <> · about {formatUsd(cost)}</>}
          {" · "}<Link href="/settings" className="text-accent hover:opacity-70">Change</Link></>
      ) : (
        <span className="text-warn">The Gemini voice needs an API key. <Link href="/settings" className="underline">Open Settings</Link></span>
      )}
    </p>
  );
}

function ChapterStatus({ c }: { c: Chapter }) {
  const s = c.status;
  let text: React.ReactNode;
  if (s.audio_ready) text = <>{s.duration_s ? formatTime(s.duration_s) : "Ready"}</>;
  else if (s.state === "generating") text = <span className="text-accent">Preparing… {s.segments_completed} of {s.segments_total}</span>;
  else if (s.state === "incomplete") text = <span className="text-bad">Some parts failed. Tap to try again.</span>;
  else if (isListenable(c)) text = <>Partly ready</>;
  else text = <>About {formatDuration(c.estimated_minutes)}</>;
  return <span className="block text-[13px] text-muted">{text}</span>;
}
