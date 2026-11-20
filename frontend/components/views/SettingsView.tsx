"use client";

import { useEffect, useRef, useState } from "react";
import { AlertTriangle, ArrowUpRight, Check, ChevronsUpDown, Cpu, ExternalLink, KeyRound, Play, Sparkles, Square, Zap } from "lucide-react";
import { api, type AppSettings, type Engine, type VoiceSettings } from "@/lib/api";
import { BRAND, CREATOR } from "@/lib/brand";
import { GitHubTile, HeartTile, LinkedInTile, YouTubeTile } from "../BrandIcons";
import { Logo } from "../Logo";
import { ErrorNote, Group, InfoNote, SectionFooter, SectionTitle, Segmented, Skeleton, cx, useToast } from "../ui";

export function SettingsView() {
  const [s, setS] = useState<AppSettings | null>(null);
  const [v, setV] = useState<VoiceSettings | null>(null);
  const [picked, setPicked] = useState<Engine | null>(null); // chosen here but maybe not saved yet (Gemini without key)
  const [error, setError] = useState<string | null>(null);
  const toast = useToast();

  const reload = () => Promise.all([api.settings().then(setS), api.voiceSettings().then(setV)]).catch((e) => setError(e.message));
  useEffect(() => { reload(); }, []);

  const engine = picked ?? v?.engine ?? "local";

  const choose = async (e: Engine, voice?: string, model?: string) => {
    setPicked(e);
    if (!v?.engines[e].available) return; // Gemini without a key: show the key field first
    if (!voice && !model && v.engine === e) return;
    try {
      setV(await api.setVoice(e, voice, model));
      toast("ok", model ? "Speed updated" : voice ? `Voice set to ${voice}` : e === "gemini" ? "Using Gemini AI voice" : "Using local voice");
    } catch (err) { toast("error", (err as Error).message); }
  };

  return (
    <div className="fade-in mx-auto max-w-2xl">
      <h1 className="font-serif text-[34px] leading-tight sm:text-5xl">Settings</h1>
      <ErrorNote error={error} className="mt-6" />

      {!v || !s ? <Skeleton className="mt-8 h-96" /> : (
        <div className="mt-8 space-y-9">
          <section>
            <SectionTitle>Reading Voice</SectionTitle>
            <Group>
              <EngineRow on={engine === "local"} onClick={() => choose("local")} tile="bg-[#8e8e93]" icon={<Cpu className="size-4" />}
                title="Local Voice" subtitle="Free · works offline · no account needed" />
              <EngineRow on={engine === "gemini"} onClick={() => choose("gemini")} tile="bg-gradient-to-b from-[#bf5af2] to-[#5e5ce6]" icon={<Sparkles className="size-4" />}
                title="Gemini AI Voice" subtitle="Natural, human-like · needs a Gemini API key" />
            </Group>
            <SectionFooter>
              {engine === "local"
                ? "Uses the voice built into this computer. Nothing leaves your device."
                : "Text is sent to Google to be read aloud. The free tier allows about 10 requests a day."}
            </SectionFooter>
          </section>

          {engine === "local" && (
            <section>
              <SectionTitle>Local Voice</SectionTitle>
              <VoiceRows v={v} engine="local" onPick={(id) => choose("local", id)} />
            </section>
          )}

          {engine === "gemini" && (
            <>
              {v.engines.gemini.blocked && (
                <div className="flex items-start gap-2.5 rounded-xl bg-warn/10 px-4 py-3 text-[15px] text-warn">
                  <AlertTriangle className="mt-0.5 size-4 shrink-0" /><span>{v.engines.gemini.blocked}</span>
                </div>
              )}
              {v.engines.gemini.available && (
                <section>
                  <SectionTitle>Gemini AI Voice</SectionTitle>
                  <Group>
                    <div className="flex items-center justify-between gap-4 px-4 py-2.5">
                      <span className="text-[17px]">Speed</span>
                      <div className="w-56">
                        <Segmented label="Speed" value={v.engines.gemini.model}
                          options={v.engines.gemini.models.map((m) => ({
                            value: m.id,
                            label: m.fast ? <><Zap className="size-3.5" />Fast</> : <>Best Quality</>,
                          }))}
                          onChange={(m) => choose("gemini", undefined, m)} />
                      </div>
                    </div>
                  </Group>
                  <SectionFooter>Fast starts playing sooner. Best Quality is more expressive but slower.</SectionFooter>
                  <div className="mt-6"><VoiceRows v={v} engine="gemini" onPick={(id) => choose("gemini", id)} /></div>
                </section>
              )}
              <GeminiKey s={s}
                onSaved={async () => { await reload(); setV(await api.setVoice("gemini")); toast("ok", "Key saved · using Gemini AI voice"); }}
                onRemoved={async () => { await api.setVoice("local").catch(() => {}); setPicked("local"); await reload(); }} />
            </>
          )}

          {!s.ffmpeg_available && (
            <InfoNote tone="warn">FFmpeg is missing, so audio can&apos;t be prepared. Install it with <code>brew install ffmpeg</code> and restart.</InfoNote>
          )}

          <About />
        </div>
      )}
    </div>
  );
}

function EngineRow({ on, onClick, tile, icon, title, subtitle }: {
  on: boolean; onClick: () => void; tile: string; icon: React.ReactNode; title: string; subtitle: string;
}) {
  return (
    <button onClick={onClick} role="radio" aria-checked={on} className="flex w-full items-center gap-3 px-4 py-2.5 text-left transition hover:bg-fill">
      <span className={cx("grid size-[30px] shrink-0 place-items-center rounded-[7px] text-white", tile)}>{icon}</span>
      <span className="min-w-0 flex-1">
        <span className="block text-[17px]">{title}</span>
        <span className="block text-[13px] text-muted">{subtitle}</span>
      </span>
      {on && <Check className="size-5 shrink-0 text-accent" strokeWidth={2.6} />}
    </button>
  );
}

function VoiceRows({ v, engine, onPick }: { v: VoiceSettings; engine: Engine; onPick: (id: string) => void }) {
  const info = v.engines[engine];
  const current = v.engine === engine ? v.voice : info.voices[0]?.id;
  const [voice, setVoice] = useState(current);
  const [busy, setBusy] = useState(false);
  const [playing, setPlaying] = useState(false);
  const audio = useRef<HTMLAudioElement | null>(null);
  const toast = useToast();
  useEffect(() => () => audio.current?.pause(), []);

  const tryIt = async () => {
    if (playing) { audio.current?.pause(); setPlaying(false); return; }
    setBusy(true);
    try {
      const r = await api.preview({ provider: info.provider, model: info.model, voice: voice!, style_key: "natural", pace: "natural", delivery_notes: "" });
      audio.current?.pause();
      audio.current = new Audio(r.url);
      audio.current.onended = () => setPlaying(false);
      await audio.current.play();
      setPlaying(true);
    } catch (e) { toast("error", (e as Error).message); } finally { setBusy(false); }
  };

  return (
    <Group>
      <label className="flex items-center justify-between gap-4 px-4 py-3">
        <span className="text-[17px]">Voice</span>
        <span className="relative flex min-w-0 items-center">
          <select value={voice} aria-label="Voice"
            onChange={(e) => { setVoice(e.target.value); onPick(e.target.value); }}
            className="min-w-0 cursor-pointer appearance-none truncate bg-transparent pr-6 text-right text-[17px] text-muted outline-none">
            {info.voices.map((x) => <option key={x.id} value={x.id}>{x.name}{x.description && !x.description.startsWith("macOS") ? ` – ${x.description}` : ""}</option>)}
          </select>
          <ChevronsUpDown className="pointer-events-none absolute right-0 size-4 text-faint" />
        </span>
      </label>
      <button onClick={tryIt} disabled={busy} className="flex w-full items-center gap-2 px-4 py-3 text-left text-[17px] text-accent transition hover:bg-fill disabled:opacity-50">
        {playing ? <Square className="size-4 fill-current" /> : <Play className="size-4 fill-current" />}
        {busy ? "Loading Sample…" : playing ? "Stop Sample" : "Play Sample"}
      </button>
    </Group>
  );
}

function GeminiKey({ s, onSaved, onRemoved }: { s: AppSettings; onSaved: () => Promise<void>; onRemoved: () => Promise<void> }) {
  const [key, setKey] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [test, setTest] = useState<{ ok: boolean; error?: string } | null>(null);
  const toast = useToast();
  const run = async (name: string, fn: () => Promise<void>) => {
    setBusy(name);
    try { await fn(); } catch (e) { toast("error", (e as Error).message); } finally { setBusy(null); }
  };

  if (s.gemini.configured) {
    return (
      <section>
        <SectionTitle>API Key</SectionTitle>
        <Group>
          <div className="flex items-center justify-between gap-4 px-4 py-3">
            <span className="text-[17px]">Gemini Key</span>
            <span className="flex items-center gap-1.5 text-[17px] text-muted">{s.gemini.masked_key}<Check className="size-4 text-ok" strokeWidth={2.6} /></span>
          </div>
          <button onClick={() => run("test", async () => setTest(await api.testKey()))} disabled={busy === "test"}
            className="flex w-full items-center justify-between px-4 py-3 text-left text-[17px] text-accent transition hover:bg-fill">
            {busy === "test" ? "Checking…" : "Check Key"}
            {test && <span className={cx("text-[15px]", test.ok ? "text-ok" : "text-bad")}>{test.ok ? "Works" : "Not working"}</span>}
          </button>
          {s.gemini.source !== "env" && (
            <button onClick={() => run("rm", async () => { if (!confirm("Remove the Gemini API key?")) return; await api.removeKey(); setTest(null); await onRemoved(); })}
              className="flex w-full items-center px-4 py-3 text-left text-[17px] text-bad transition hover:bg-fill">Remove Key</button>
          )}
        </Group>
        <SectionFooter>
          {test && !test.ok ? test.error : s.gemini.source === "env" ? "This key comes from backend/.env. Edit that file to change it." : "Your key is stored in this computer's keychain."}
        </SectionFooter>
      </section>
    );
  }

  return (
    <section>
      <SectionTitle>API Key</SectionTitle>
      <Group>
        <div className="flex items-center gap-3 px-4 py-2">
          <KeyRound className="size-5 shrink-0 text-faint" />
          <input type="password" autoComplete="off" placeholder="Paste your Gemini API key" value={key} onChange={(e) => setKey(e.target.value)}
            aria-label="Gemini API key" className="min-w-0 flex-1 bg-transparent py-1.5 text-[17px] text-ink placeholder:text-faint outline-none" />
          <button disabled={key.trim().length < 10 || busy === "save"}
            onClick={() => run("save", async () => { await api.saveKey(key.trim()); setKey(""); await onSaved(); })}
            className="press h-8 shrink-0 rounded-full bg-accent px-4 text-[15px] font-semibold text-accent-ink disabled:opacity-35">
            {busy === "save" ? "Saving…" : "Save"}
          </button>
        </div>
      </Group>
      <SectionFooter>
        Get a free key from{" "}
        <a className="inline-flex items-center gap-0.5 text-accent" href="https://aistudio.google.com/apikey" target="_blank" rel="noreferrer">Google AI Studio<ExternalLink className="size-3" /></a>
        {" "}→ Create API key. For whole books, turn on billing there (about $1 per hour of audio).
      </SectionFooter>
    </section>
  );
}

function About() {
  const links = [
    { href: CREATOR.youtube, icon: <YouTubeTile />, title: "YouTube", subtitle: "Shubham Gour Tech" },
    { href: CREATOR.linkedin, icon: <LinkedInTile />, title: "LinkedIn", subtitle: "Connect with Shubham" },
    { href: CREATOR.github, icon: <GitHubTile />, title: "GitHub", subtitle: "Source code and more projects" },
    { href: CREATOR.support, icon: <HeartTile />, title: "Support This Project", subtitle: "Help keep CloudReader free" },
  ];
  return (
    <section>
      <SectionTitle>About</SectionTitle>
      <Group>
        <div className="flex items-center gap-4 px-4 py-4">
          <Logo size={56} className="rounded-[13px] shadow-sm" />
          <div className="min-w-0">
            <div className="text-[17px] font-semibold">{BRAND.name}</div>
            <div className="text-[13px] text-muted">Created by <span className="font-medium text-ink">{CREATOR.name}</span></div>
            <div className="text-[13px] text-muted">Free and open source · MIT License</div>
          </div>
        </div>
        {links.map((l) => (
          <a key={l.title} href={l.href} target="_blank" rel="noreferrer"
            className="flex items-center gap-3 px-4 py-2.5 transition hover:bg-fill">
            {l.icon}
            <span className="min-w-0 flex-1">
              <span className="block text-[17px]">{l.title}</span>
              <span className="block truncate text-[13px] text-muted">{l.subtitle}</span>
            </span>
            <ArrowUpRight className="size-4 shrink-0 text-faint" />
          </a>
        ))}
      </Group>
      <SectionFooter>Made with care by {CREATOR.name}. If CloudReader helps you, a ⭐ on GitHub means a lot.</SectionFooter>
    </section>
  );
}
