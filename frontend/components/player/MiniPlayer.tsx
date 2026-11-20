"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Bookmark, Loader2, Maximize2, Pause, Play, RotateCcw, RotateCw, SkipBack, SkipForward, Volume2, VolumeX } from "lucide-react";
import { formatTime, prettyTitle } from "@/lib/format";
import { Cover } from "../Cover";
import { DemoBadge, cx, useToast } from "../ui";
import { SPEEDS, usePlayer } from "./PlayerProvider";

export function Scrubber({ className }: { className?: string }) {
  const p = usePlayer();
  const pct = p.duration ? (p.time / p.duration) * 100 : 0;
  return (
    <input type="range" className={cx("scrub w-full", className)} min={0} max={p.duration || 0} step={0.1} value={p.time}
      onChange={(e) => p.seek(Number(e.target.value))} aria-label="Playback position"
      aria-valuetext={`${formatTime(p.time)} of ${formatTime(p.duration)}`}
      style={{ ["--pct" as string]: `${pct}%` }} />
  );
}

export function SpeedSelect({ className }: { className?: string }) {
  const p = usePlayer();
  return (
    <select value={p.rate} onChange={(e) => p.setRate(Number(e.target.value))} aria-label="Playback speed"
      className={cx("h-8 cursor-pointer rounded-md border border-line bg-transparent px-2 text-xs font-medium text-ink outline-none hover:bg-fill", className)}>
      {SPEEDS.map((s) => <option key={s} value={s} className="bg-raised">{s}×</option>)}
    </select>
  );
}

export function MiniPlayer() {
  const p = usePlayer();
  const toast = useToast();
  const path = usePathname();
  if (!p.chapter || !p.book || path === "/now-playing") return null;
  const idx = p.playable.findIndex((c) => c.id === p.chapter!.id);
  return (
    <div className="safe-bottom pointer-events-none fixed inset-x-0 bottom-0 z-40 px-3 pb-3 sm:px-6 sm:pb-5">
      <div className="material pointer-events-auto relative mx-auto max-w-4xl overflow-hidden rounded-2xl border border-line shadow-[0_10px_40px_rgb(0_0_0/0.18)]">
      <div className="absolute inset-x-0 bottom-0 h-[3px] bg-fill-2">
        <div className="h-full bg-accent" style={{ width: `${p.duration ? Math.min(100, (p.time / p.duration) * 100) : 0}%` }} />
      </div>
      <div className="flex items-center gap-2 px-2.5 py-2 sm:gap-4 sm:px-3">
        <Link href="/now-playing" className="flex min-w-0 flex-1 items-center gap-3 group">
          <Cover id={p.book.id} title={p.book.title} hasCover={p.book.has_cover} size="sm" className="!w-10 shrink-0 !rounded-[6px] shadow" />
          <div className="min-w-0">
            <div className="truncate text-[15px] font-medium">{prettyTitle(p.book.title)}</div>
            <div className="flex items-center gap-2 truncate text-xs text-muted">
              {p.error ? (
                <span className="truncate text-bad" title={p.error}>{p.error}</span>
              ) : p.waiting ? (
                <span className="flex items-center gap-1.5 text-accent"><Loader2 className="size-3 animate-spin" />Generating the next part…</span>
              ) : (
                <span className="truncate">{p.book.chapter_count > 1 ? p.chapter.title : p.book.author || "Audiobook"}</span>
              )}
              {p.live && !p.waiting && <span className="rounded-full bg-accent/15 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-accent">Live</span>}
              {p.chapter.status.is_demo && <DemoBadge />}
            </div>
          </div>
        </Link>

        <div className="flex items-center gap-1">
          <span className="hidden sm:block"><IconBtn label="Previous chapter (Shift+←)" onClick={p.prev} disabled={idx <= 0 && p.time < 5}><SkipBack className="size-4" /></IconBtn></span>
          <IconBtn label="Back 15 seconds (←)" onClick={() => p.skip(-15)}><RotateCcw className="size-4" /></IconBtn>
          <button onClick={p.toggle} aria-label={p.playing ? "Pause (Space)" : "Play (Space)"}
            className="press mx-1 grid size-10 place-items-center rounded-full text-ink transition hover:bg-fill">
            {(p.loading || p.waiting) && p.playing ? <Loader2 className="size-5 animate-spin" /> : p.playing ? <Pause className="size-6 fill-current" /> : <Play className="ml-0.5 size-6 fill-current" />}
          </button>
          <IconBtn label="Forward 30 seconds (→)" onClick={() => p.skip(30)}><RotateCw className="size-4" /></IconBtn>
          <span className="hidden sm:block"><IconBtn label="Next chapter (Shift+→)" onClick={p.next} disabled={idx >= p.playable.length - 1}><SkipForward className="size-4" /></IconBtn></span>
        </div>

        <div className="hidden flex-1 items-center justify-end gap-3 lg:flex">
          <span className="text-xs tabular-nums text-muted">{formatTime(p.time)} / {formatTime(p.duration)}</span>
          <SpeedSelect />
          <IconBtn label="Add bookmark (B)" onClick={() => p.addBookmark().then(() => toast("ok", `Bookmarked at ${formatTime(p.time)}`))}><Bookmark className="size-4" /></IconBtn>
          <IconBtn label={p.muted ? "Unmute (M)" : "Mute (M)"} onClick={p.toggleMute}>
            {p.muted || p.volume === 0 ? <VolumeX className="size-4" /> : <Volume2 className="size-4" />}
          </IconBtn>
          <input type="range" min={0} max={1} step={0.01} value={p.muted ? 0 : p.volume} aria-label="Volume"
            onChange={(e) => p.setVolume(Number(e.target.value))} className="scrub w-20"
            style={{ ["--pct" as string]: `${(p.muted ? 0 : p.volume) * 100}%` }} />
          <Link href="/now-playing" aria-label="Open Now Playing" className="rounded-full p-2 text-muted hover:bg-fill hover:text-ink"><Maximize2 className="size-4" /></Link>
        </div>
      </div>
      </div>
    </div>
  );
}

export function IconBtn({ label, children, className, ...rest }: React.ButtonHTMLAttributes<HTMLButtonElement> & { label: string }) {
  return (
    <button {...rest} aria-label={label} title={label}
      className={cx("grid size-9 place-items-center rounded-full text-muted transition hover:bg-fill-2 hover:text-ink disabled:opacity-30 disabled:hover:bg-transparent", className)}>
      {children}
    </button>
  );
}
