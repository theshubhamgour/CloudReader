"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Logo } from "./Logo";
import { BRAND } from "@/lib/brand";
import { cx } from "./ui";

export function TopBar() {
  const path = usePathname();
  const items = [
    { href: "/", label: "Library", active: path === "/" || path.startsWith("/books") },
    { href: "/settings", label: "Settings", active: path.startsWith("/settings") },
  ];
  return (
    <header className="material sticky top-0 z-30 border-b border-line">
      <div className="mx-auto flex h-13 max-w-5xl items-center justify-between px-5 sm:px-8">
        <Link href="/" className="flex items-center gap-2">
          <Logo size={28} className="shadow-sm rounded-[7px]" />
          <span className="text-[17px] font-semibold tracking-tight">{BRAND.name}</span>
        </Link>
        <nav aria-label="Main" className="flex rounded-[9px] bg-fill p-0.5">
          {items.map(({ href, label, active }) => (
            <Link key={href} href={href} aria-current={active ? "page" : undefined}
              className={cx("rounded-[7px] px-3.5 py-1 text-[13px] font-medium transition",
                active ? "bg-raised text-ink shadow-[0_1px_3px_rgb(0_0_0/0.12)]" : "text-muted hover:text-ink")}>
              {label}
            </Link>
          ))}
        </nav>
      </div>
    </header>
  );
}
