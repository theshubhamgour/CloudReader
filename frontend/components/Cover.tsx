"use client";

import { useLayoutEffect, useRef, useState } from "react";
import { Headphones } from "lucide-react";
import { BRAND } from "@/lib/brand";
import { coverUrl } from "@/lib/api";
import { prettyTitle } from "@/lib/format";
import { cx } from "./ui";

// Heights of the sound-wave bars on generated covers (0–1).
const WAVE = [0.35, 0.6, 0.45, 0.85, 0.55, 1, 0.7, 0.4, 0.75, 0.5, 0.9, 0.6, 0.35, 0.65, 0.45, 0.8, 0.5, 0.3];

/** 1% of an element's width in px, kept up to date as it resizes. */
function useWidthUnit<T extends HTMLElement>() {
  const ref = useRef<T>(null);
  const [unit, setUnit] = useState(0);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const update = () => setUnit(el.getBoundingClientRect().width / 100);
    update();
    const ro = new ResizeObserver(update);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  return [ref, unit] as const;
}

/** Book artwork: the uploaded cover, or a generated design that fits any title. */
export function Cover({ id, title, author, hasCover, className, size = "md" }: {
  id: number; title: string; author?: string; hasCover?: boolean; className?: string; size?: "sm" | "md" | "lg";
}) {
  const name = prettyTitle(title);
  const [ref, u] = useWidthUnit<HTMLDivElement>();
  const w = (n: number) => `${(n * u).toFixed(2)}px`; // n % of the cover's width
  if (hasCover) {
    // eslint-disable-next-line @next/next/no-img-element
    return <img src={coverUrl(id)} alt={`Cover of ${name}`} className={cx("aspect-[2/3] rounded-[10px] object-cover shadow-cover", className)} />;
  }
  const [a, b] = BRAND.coverPalettes[id % BRAND.coverPalettes.length];

  if (size === "sm") {
    return (
      <div role="img" aria-label={`Cover of ${name}`} className={cx("grid aspect-[2/3] place-items-center rounded-md", className)}
        style={{ background: `linear-gradient(160deg, ${a}, ${b})` }}>
        <Headphones className="size-3.5 text-white/85" />
      </div>
    );
  }

  // Everything is sized from the cover's measured width; long titles get a smaller size.
  const len = name.length;
  const titleSize = w(len > 60 ? 8 : len > 36 ? 9.5 : len > 18 ? 11 : 13);

  return (
    <div ref={ref} role="img" aria-label={`Cover of ${name}`}
      className={cx("relative flex aspect-[2/3] flex-col overflow-hidden rounded-[10px] shadow-cover ring-1 ring-black/5", className)}
      style={{ background: `linear-gradient(160deg, ${b} -30%, ${a} 55%)`, padding: w(9) }}>
      {/* glow + depth */}
      <div className="pointer-events-none absolute -right-[25%] -top-[15%] aspect-square w-[75%] rounded-full bg-white/25 blur-2xl" />
      <div className="pointer-events-none absolute inset-x-0 bottom-0 h-1/2 bg-gradient-to-t from-black/35 to-transparent" />
      {/* spine highlight */}
      <div className="pointer-events-none absolute inset-y-0 left-0 w-[4%] bg-gradient-to-r from-black/30 to-white/5" />

      <div className="relative flex items-center font-medium uppercase text-white/75" style={{ gap: w(2.5), fontSize: w(4.2), letterSpacing: "0.22em" }}>
        <Headphones style={{ width: w(5.5), height: w(5.5) }} />
        Audiobook
      </div>

      <div className="relative font-serif text-white"
        style={{
          marginTop: w(8), fontSize: titleSize, lineHeight: 1.12, overflowWrap: "anywhere", hyphens: "auto",
          display: "-webkit-box", WebkitLineClamp: 6, WebkitBoxOrient: "vertical", overflow: "hidden",
        }}>
        {name}
      </div>

      <div className="relative mt-auto">
        <div className="flex items-end gap-[1.4%]" style={{ height: w(11) }} aria-hidden>
          {WAVE.map((h, i) => (
            <span key={i} className="flex-1 rounded-full bg-white" style={{ height: `${h * 100}%`, opacity: 0.35 + h * 0.45 }} />
          ))}
        </div>
        {author && (
          <div className="truncate uppercase text-white/75" style={{ marginTop: w(4), fontSize: w(4), letterSpacing: "0.18em" }}>{author}</div>
        )}
      </div>
    </div>
  );
}
