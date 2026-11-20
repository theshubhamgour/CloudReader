"use client";

import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { AlertTriangle, CheckCircle2, Info, Loader2, X } from "lucide-react";
import type { ChapterState } from "@/lib/api";
import { STATE_LABEL } from "@/lib/format";

export function cx(...c: (string | false | null | undefined)[]) {
  return c.filter(Boolean).join(" ");
}

type BtnVariant = "primary" | "secondary" | "ghost" | "danger";
export function Button({ variant = "secondary", size = "md", loading, className, children, ...rest }:
  React.ButtonHTMLAttributes<HTMLButtonElement> & { variant?: BtnVariant; size?: "sm" | "md"; loading?: boolean }) {
  // Apple-style: filled, tinted, plain (text) and destructive.
  const v = {
    primary: "bg-accent text-accent-ink hover:brightness-110 font-semibold",
    secondary: "bg-accent/12 text-accent hover:bg-accent/18 font-medium",
    ghost: "text-accent hover:bg-fill font-medium",
    danger: "bg-bad/10 text-bad hover:bg-bad/15 font-medium",
  }[variant];
  return (
    <button
      {...rest}
      disabled={rest.disabled || loading}
      className={cx(
        "press inline-flex items-center justify-center gap-1.5 rounded-full disabled:opacity-40 disabled:cursor-not-allowed whitespace-nowrap",
        size === "sm" ? "h-8 px-3.5 text-[13px]" : "h-10 px-5 text-[15px]",
        v, className)}
    >
      {loading && <Loader2 className="size-4 animate-spin" />}
      {children}
    </button>
  );
}

export function Card({ className, children }: { className?: string; children: React.ReactNode }) {
  return <div className={cx("rounded-2xl bg-surface shadow-card", className)}>{children}</div>;
}

// ---------------------------------------------------------------- grouped lists (iOS style)

export function SectionTitle({ children, className }: { children: React.ReactNode; className?: string }) {
  return <h2 className={cx("mb-2 px-4 text-[13px] font-normal uppercase tracking-wide text-muted", className)}>{children}</h2>;
}

export function SectionFooter({ children }: { children: React.ReactNode }) {
  return <p className="mt-2 px-4 text-[13px] leading-snug text-muted">{children}</p>;
}

/** A rounded group whose rows are separated by inset hairlines. */
export function Group({ children, className }: { children: React.ReactNode; className?: string }) {
  return (
    <div className={cx("overflow-hidden rounded-xl bg-surface shadow-card [&>*+*]:relative [&>*+*]:before:absolute [&>*+*]:before:left-4 [&>*+*]:before:right-0 [&>*+*]:before:top-0 [&>*+*]:before:h-px [&>*+*]:before:bg-line [&>*+*]:before:content-['']", className)}>
      {children}
    </div>
  );
}

/** Segmented control. */
export function Segmented<T extends string>({ value, options, onChange, label }: {
  value: T; options: { value: T; label: React.ReactNode }[]; onChange: (v: T) => void; label: string;
}) {
  return (
    <div role="radiogroup" aria-label={label} className="grid rounded-[9px] bg-fill p-0.5" style={{ gridTemplateColumns: `repeat(${options.length}, minmax(0, 1fr))` }}>
      {options.map((o) => {
        const on = o.value === value;
        return (
          <button key={o.value} role="radio" aria-checked={on} onClick={() => !on && onChange(o.value)}
            className={cx("flex h-8 items-center justify-center gap-1.5 rounded-[7px] text-[13px] font-medium transition",
              on ? "bg-raised text-ink shadow-[0_1px_3px_rgb(0_0_0/0.12),0_0_0_0.5px_rgb(0_0_0/0.04)]" : "text-ink/80 hover:text-ink")}>
            {o.label}
          </button>
        );
      })}
    </div>
  );
}

export function PageHeader({ eyebrow, title, children }: { eyebrow?: string; title: string; children?: React.ReactNode }) {
  return (
    <div className="mb-8 flex flex-wrap items-end justify-between gap-4">
      <div>
        {eyebrow && <div className="mb-1 text-xs font-medium uppercase tracking-[0.18em] text-faint">{eyebrow}</div>}
        <h1 className="font-serif text-4xl tracking-tight text-ink">{title}</h1>
      </div>
      <div className="flex items-center gap-2">{children}</div>
    </div>
  );
}

const STATE_STYLE: Record<ChapterState, string> = {
  ready: "bg-ok/10 text-ok",
  generating: "bg-accent/15 text-accent",
  partial: "bg-fill-2 text-muted",
  not_generated: "bg-fill text-faint",
  incomplete: "bg-bad/10 text-bad",
  outdated: "bg-warn/10 text-warn",
};

export function StateBadge({ state, extra }: { state: ChapterState; extra?: string }) {
  return (
    <span className={cx("inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium", STATE_STYLE[state])}>
      {state === "generating" && <Loader2 className="size-3 animate-spin" />}
      {STATE_LABEL[state]}{extra ? ` · ${extra}` : ""}
    </span>
  );
}

export function DemoBadge() {
  return (
    <span title="Read by the free voice built into this computer (not AI narration)."
      className="rounded-full border border-line bg-fill px-2 py-0.5 text-[11px] font-medium text-muted">
      Local voice
    </span>
  );
}

export function Spinner({ label }: { label?: string }) {
  return <div className="flex items-center gap-2 text-sm text-muted"><Loader2 className="size-4 animate-spin" />{label}</div>;
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={cx("shimmer rounded-xl", className)} />;
}

export function ErrorNote({ error, className }: { error: string | null | undefined; className?: string }) {
  if (!error) return null;
  return (
    <div role="alert" className={cx("flex items-start gap-2 rounded-xl bg-bad/10 px-4 py-3 text-sm text-bad", className)}>
      <AlertTriangle className="mt-0.5 size-4 shrink-0" />
      <span>{error}</span>
    </div>
  );
}

export function InfoNote({ children, className, tone = "info" }: { children: React.ReactNode; className?: string; tone?: "info" | "warn" }) {
  return (
    <div className={cx("flex items-start gap-2 rounded-xl border px-4 py-3 text-sm",
      tone === "warn" ? "border-transparent bg-warn/10 text-warn" : "border-transparent bg-fill text-muted", className)}>
      {tone === "warn" ? <AlertTriangle className="mt-0.5 size-4 shrink-0" /> : <Info className="mt-0.5 size-4 shrink-0" />}
      <div>{children}</div>
    </div>
  );
}

export function Field({ label, hint, disabledReason, children }: { label: string; hint?: string; disabledReason?: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <div className="mb-1.5 flex items-baseline justify-between gap-2">
        <span className="text-[13px] font-medium text-ink">{label}</span>
        {hint && <span className="text-xs text-faint">{hint}</span>}
      </div>
      {children}
      {disabledReason && <p className="mt-1.5 text-xs text-faint">{disabledReason}</p>}
    </label>
  );
}

export const inputCls = "w-full rounded-[10px] bg-fill px-3 py-2.5 text-[15px] text-ink placeholder:text-faint outline-none transition focus:ring-2 focus:ring-accent/50 disabled:opacity-40";

export function Modal({ open, onClose, title, children, footer }: {
  open: boolean; onClose: () => void; title: string; children: React.ReactNode; footer?: React.ReactNode;
}) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const prev = document.activeElement as HTMLElement | null;
    ref.current?.querySelector<HTMLElement>("input, textarea, button")?.focus();
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => { window.removeEventListener("keydown", onKey); prev?.focus(); };
  }, [open, onClose]);
  if (!open || typeof document === "undefined") return null;
  // Portal to <body>: animated ancestors would otherwise trap position:fixed.
  return createPortal(
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-black/40 p-0 sm:items-center sm:p-4" onMouseDown={onClose}>
      <div ref={ref} role="dialog" aria-modal="true" aria-label={title} onMouseDown={(e) => e.stopPropagation()}
        className="fade-in safe-bottom w-full max-w-lg rounded-t-2xl bg-raised shadow-2xl sm:rounded-2xl">
        <div className="flex items-center justify-between border-b border-line px-6 py-4">
          <h2 className="text-[17px] font-semibold">{title}</h2>
          <button onClick={onClose} aria-label="Close" className="rounded-md p-1 text-muted hover:text-ink"><X className="size-5" /></button>
        </div>
        <div className="max-h-[70vh] overflow-y-auto px-6 py-5">{children}</div>
        {footer && <div className="flex justify-end gap-2 border-t border-line px-6 py-4">{footer}</div>}
      </div>
    </div>,
    document.body,
  );
}

// ---------------------------------------------------------------- toasts

type Toast = { id: number; kind: "ok" | "error" | "info"; text: string };
const ToastCtx = createContext<(kind: Toast["kind"], text: string) => void>(() => {});
export const useToast = () => useContext(ToastCtx);

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const push = useCallback((kind: Toast["kind"], text: string) => {
    const id = Date.now() + Math.random();
    setToasts((t) => [...t, { id, kind, text }]);
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), kind === "error" ? 8000 : 4000);
  }, []);
  return (
    <ToastCtx.Provider value={push}>
      {children}
      <div aria-live="polite" className="pointer-events-none fixed inset-x-4 top-16 z-[60] mx-auto flex max-w-md flex-col items-center gap-2">
        {toasts.map((t) => (
          <div key={t.id} className={cx("material fade-in pointer-events-auto flex items-start gap-2 rounded-2xl px-4 py-2.5 text-sm text-ink shadow-[0_8px_30px_rgb(0_0_0/0.18)]")}>
            {t.kind === "error" ? <AlertTriangle className="mt-0.5 size-4 shrink-0 text-bad" /> : t.kind === "ok" ? <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-ok" /> : <Info className="mt-0.5 size-4 shrink-0 text-accent" />}
            <span>{t.text}</span>
          </div>
        ))}
      </div>
    </ToastCtx.Provider>
  );
}

export function ProgressBar({ value, className, tone = "accent" }: { value: number; className?: string; tone?: "accent" | "ok" | "bad" }) {
  return (
    <div className={cx("h-1.5 overflow-hidden rounded-full bg-fill-2", className)}
      role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(value * 100)}>
      <div className={cx("h-full rounded-full transition-[width] duration-500",
        tone === "ok" ? "bg-ok" : tone === "bad" ? "bg-bad" : "bg-accent")} style={{ width: `${Math.min(100, value * 100)}%` }} />
    </div>
  );
}
