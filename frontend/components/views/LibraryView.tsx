"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { ChevronRight, FileText, Loader2, Play, Trash2 } from "lucide-react";
import { api, type Book, type VoiceSettings } from "@/lib/api";
import { formatDuration, prettyTitle } from "@/lib/format";
import { Cover } from "../Cover";
import { usePlayer } from "../player/PlayerProvider";
import { ErrorNote, Skeleton, cx, useToast } from "../ui";

const ACCEPT = ".docx,.epub,.txt,.md,.markdown";

export function LibraryView() {
  const [books, setBooks] = useState<Book[] | null>(null);
  const [voice, setVoice] = useState<VoiceSettings | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => api.books().then(setBooks).catch((e) => setError(e.message)), []);
  useEffect(() => {
    load();
    api.voiceSettings().then(setVoice).catch(() => {});
  }, [load]);

  return (
    <div className="fade-in">
      <h1 className="font-serif text-[34px] leading-tight sm:text-5xl">Library</h1>
      <p className="mt-1 text-[17px] text-muted">Turn any document into an audiobook.</p>

      <UploadCard voice={voice} />
      <ErrorNote error={error} className="mt-6" />

      <div className="mb-5 mt-12 flex items-baseline justify-between">
        <h2 className="text-[22px] font-bold tracking-tight">My Books</h2>
        {books && books.length > 0 && <span className="text-[15px] text-muted">{books.length} {books.length === 1 ? "book" : "books"}</span>}
      </div>

      {books === null && !error && (
        <div className="grid grid-cols-2 gap-6 sm:grid-cols-3 lg:grid-cols-4">{[0, 1, 2].map((i) => <Skeleton key={i} className="aspect-[2/3]" />)}</div>
      )}

      {books?.length === 0 && (
        <div className="rounded-2xl bg-surface px-6 py-14 text-center shadow-card">
          <p className="text-[17px] font-semibold">No Books Yet</p>
          <p className="mt-1 text-[15px] text-muted">Books you add will appear here.</p>
        </div>
      )}

      {books && books.length > 0 && (
        <div className="grid grid-cols-2 gap-x-5 gap-y-9 sm:grid-cols-3 sm:gap-x-8 lg:grid-cols-4">
          {books.map((b) => <BookCard key={b.id} b={b} onDeleted={load} />)}
        </div>
      )}
    </div>
  );
}

function BookCard({ b, onDeleted }: { b: Book; onDeleted: () => void }) {
  const player = usePlayer();
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  const remove = async () => {
    if (!confirm(`Delete “${prettyTitle(b.title)}”?`)) return;
    setBusy(true);
    try {
      await api.deleteBook(b.id);
      toast("ok", "Book deleted");
      onDeleted();
    } catch (e) { toast("error", (e as Error).message); setBusy(false); }
  };
  const ready = b.chapter_count > 0 && b.chapters_ready === b.chapter_count;
  const hoverBtn = "opacity-100 transition sm:opacity-0 sm:group-hover:opacity-100 focus:opacity-100";
  return (
    <div className={cx("group relative", busy && "pointer-events-none opacity-40")}>
      <Link href={`/books/${b.id}`} className="press block">
        <div className="relative transition duration-300 sm:group-hover:-translate-y-1">
          <Cover id={b.id} title={b.title} author={b.author} hasCover={b.has_cover} className="w-full" />
          {b.chapters_ready > 0 && (
            <button aria-label={`Play ${prettyTitle(b.title)}`}
              onClick={(e) => { e.preventDefault(); player.load(b.id, b.progress?.chapter_id, b.progress?.position_s ?? 0, true); }}
              className={cx("material press absolute bottom-2.5 right-2.5 grid size-10 place-items-center rounded-full text-ink shadow-lg", hoverBtn)}>
              <Play className="ml-0.5 size-4 fill-current" />
            </button>
          )}
        </div>
        <div className="mt-3 line-clamp-2 text-[15px] font-semibold leading-snug [overflow-wrap:anywhere]">{prettyTitle(b.title)}</div>
        <div className="mt-0.5 flex items-center gap-1.5 text-[13px] text-muted">
          {b.any_generating
            ? <><Loader2 className="size-3 animate-spin text-accent" />Preparing…</>
            : b.listening_progress > 0
              ? <>{Math.round(b.listening_progress * 100)}% listened</>
              : ready ? <>{formatDuration(b.estimated_minutes)}</> : <>Not started · {formatDuration(b.estimated_minutes)}</>}
        </div>
        {b.listening_progress > 0 && (
          <div className="mt-1.5 h-[3px] overflow-hidden rounded-full bg-fill-2">
            <div className="h-full rounded-full bg-accent" style={{ width: `${Math.round(b.listening_progress * 100)}%` }} />
          </div>
        )}
      </Link>
      <button onClick={remove} aria-label={`Delete ${prettyTitle(b.title)}`} title="Delete Book"
        className={cx("material press absolute right-2 top-2 grid size-8 place-items-center rounded-full text-bad shadow", hoverBtn)}>
        <Trash2 className="size-3.5" />
      </button>
    </div>
  );
}

/** Drop or pick a file: it's imported immediately and you land on the book. */
function UploadCard({ voice }: { voice: VoiceSettings | null }) {
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [drag, setDrag] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const router = useRouter();
  const toast = useToast();

  const upload = async (file: File | undefined) => {
    if (!file || busy) return;
    setBusy(file.name);
    setError(null);
    try {
      const book = await api.importBook(file);
      toast("ok", `Added “${prettyTitle(book.title)}”`);
      router.push(`/books/${book.id}`);
    } catch (e) {
      setError((e as Error).message);
      setBusy(null);
    }
  };

  return (
    <div className="mt-7">
      <div onDragOver={(e) => { e.preventDefault(); setDrag(true); }} onDragLeave={() => setDrag(false)}
        onDrop={(e) => { e.preventDefault(); setDrag(false); upload(e.dataTransfer.files[0]); }}
        className={cx("flex flex-col items-center gap-4 rounded-2xl bg-surface px-6 py-8 text-center shadow-card transition sm:flex-row sm:text-left",
          drag && "ring-2 ring-accent")}>
        <span className="grid size-14 shrink-0 place-items-center rounded-2xl bg-gradient-to-b from-[#5ac8fa] to-[#007aff] text-white shadow-md">
          {busy ? <Loader2 className="size-6 animate-spin" /> : <FileText className="size-6" />}
        </span>
        <div className="min-w-0 flex-1">
          <div className="text-[17px] font-semibold">{busy ? `Adding “${busy}”…` : "Add a Document"}</div>
          <div className="mt-0.5 text-[15px] text-muted">
            <span className="hidden sm:inline">Drop a file here, or choose one. </span>Word, EPUB, text or Markdown.
          </div>
        </div>
        <button type="button" onClick={() => inputRef.current?.click()} disabled={!!busy}
          className="press h-10 shrink-0 rounded-full bg-accent px-6 text-[15px] font-semibold text-accent-ink hover:brightness-110 disabled:opacity-50">
          Choose File
        </button>
      </div>
      <input ref={inputRef} type="file" accept={ACCEPT} hidden onChange={(e) => { upload(e.target.files?.[0]); e.target.value = ""; }} />
      {voice && (
        <Link href="/settings" className="mt-2 flex items-center justify-center gap-0.5 px-4 text-[13px] text-muted hover:text-ink sm:justify-start">
          Read by {voice.engine === "gemini" ? `Gemini AI · ${voice.voice}` : `Local Voice · ${voice.voice}`}
          <ChevronRight className="size-3.5" />
        </Link>
      )}
      <ErrorNote error={error} className="mt-4" />
    </div>
  );
}
