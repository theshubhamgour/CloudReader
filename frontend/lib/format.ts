export function formatTime(seconds: number | null | undefined): string {
  if (seconds == null || !isFinite(seconds) || seconds < 0) return "0:00";
  const s = Math.floor(seconds);
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = String(s % 60).padStart(2, "0");
  return h ? `${h}:${String(m).padStart(2, "0")}:${sec}` : `${m}:${sec}`;
}

export function formatDuration(minutes: number): string {
  if (minutes < 1) return "< 1 min";
  const h = Math.floor(minutes / 60);
  const m = Math.round(minutes % 60);
  return h ? `${h} h ${m} min` : `${m} min`;
}

export function formatNumber(n: number): string {
  return n.toLocaleString("en-US");
}

export function formatUsd(n: number | null | undefined): string {
  if (n == null) return "—";
  if (n === 0) return "$0.00";
  return n < 0.01 ? "< $0.01" : `$${n.toFixed(2)}`;
}

export const STATE_LABEL: Record<string, string> = {
  not_generated: "Not generated",
  partial: "Partially generated",
  generating: "Generating",
  ready: "Ready",
  incomplete: "Incomplete",
  outdated: "Out of date",
};

/** "github-support_request" → "github support request" (only for titles that are clearly file names). */
export function prettyTitle(title: string): string {
  const t = title.trim();
  if (/\s/.test(t) || !/[-_]/.test(t)) return t;
  return t.replace(/[-_]+/g, " ").replace(/\s+/g, " ").trim();
}

const GENERIC_CHAPTER = /^(front matter|full text)$/i;

/** A single-chapter book's auto-named chapter ("Front Matter") is shown as the book's name. */
export function chapterName(chapterTitle: string, bookTitle: string, chapterCount: number): string {
  return chapterCount <= 1 && GENERIC_CHAPTER.test(chapterTitle.trim()) ? prettyTitle(bookTitle) : chapterTitle;
}

/** "Sulafat (gemini)" → "Gemini AI · Sulafat"; "Samantha (demo)" → "Local Voice · Samantha". */
export function narratorLabel(narrator: string): string {
  const m = narrator.match(/^(.*) \((gemini|demo)\)$/);
  if (!m) return narrator;
  return `${m[2] === "gemini" ? "Gemini AI" : "Local Voice"} · ${m[1]}`;
}
