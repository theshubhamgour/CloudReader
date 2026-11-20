import type { Metadata, Viewport } from "next";
import { Suspense } from "react";
import { Inter } from "next/font/google";
import "./globals.css";
import { BRAND } from "@/lib/brand";
import { PlayerProvider } from "@/components/player/PlayerProvider";
import { MiniPlayer } from "@/components/player/MiniPlayer";
import { TopBar } from "@/components/TopBar";
import { ToastProvider } from "@/components/ui";

const inter = Inter({ variable: "--font-inter", subsets: ["latin"] });

export const metadata: Metadata = {
  title: `${BRAND.name} — ${BRAND.tagline}`,
  description: "Turn any document into an audiobook.",
  appleWebApp: { capable: true, title: BRAND.name, statusBarStyle: "default" },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#f5f5f7" },
    { media: "(prefers-color-scheme: dark)", color: "#000000" },
  ],
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className={`${inter.variable} h-full antialiased`}>
      <body className="min-h-full font-sans">
        <ToastProvider>
          <PlayerProvider>
            <div className="min-h-screen">
              <Suspense fallback={<div className="h-13 border-b border-line" />}>
                <TopBar />
              </Suspense>
              <main className="mx-auto max-w-5xl px-5 pb-40 pt-6 sm:px-8 sm:pt-10">{children}</main>
            </div>
            <Suspense>
              <MiniPlayer />
            </Suspense>
          </PlayerProvider>
        </ToastProvider>
      </body>
    </html>
  );
}
