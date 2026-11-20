<p align="center"><img src="frontend/public/logo.svg" width="96" alt="CloudReader logo"></p>

<h1 align="center">CloudReader</h1>

<p align="center">Turn any document into an audiobook, on your own computer.</p>

<p align="center">
  Created by <a href="https://github.com/theshubhamgour"><b>Shubham Gour</b></a> ·
  <a href="https://youtube.com/shubhamgourtech">YouTube</a> ·
  <a href="https://www.linkedin.com/in/theshubhamgour/">LinkedIn</a>
</p>

<p align="center">
  <a href="LICENSE"><img alt="MIT License" src="https://img.shields.io/badge/license-MIT-blue"></a>
  <img alt="Python 3.11+" src="https://img.shields.io/badge/python-3.11%2B-blue">
  <img alt="Node 20+" src="https://img.shields.io/badge/node-20%2B-blue">
  <a href="https://razorpay.me/@decodethedeskbyshubhamgour"><img alt="Support this project" src="https://img.shields.io/badge/support-this%20project-ff5e5b"></a>
</p>

Drop in a Word, EPUB, text or Markdown file, press **Play**, and CloudReader reads it aloud.
It starts playing within seconds and prepares the rest while you listen.

- **Free and offline by default.** Uses the voice built into your computer, with no account or API key.
- **Natural AI narration when you want it.** Add a Google Gemini API key in Settings for human-like voices.
- **Local-first.** Your books, audio and listening progress stay on your machine.
- **A real audiobook player.** It remembers where you stopped, and has bookmarks, playback speed, keyboard shortcuts and media keys.
- **Works on desktop and phone**, in light and dark mode.

---

## Quick start

**You need:** macOS (recommended) or Linux, plus [Python 3.11+](https://www.python.org), [Node.js 20+](https://nodejs.org)
and [FFmpeg](https://ffmpeg.org). On a Mac, `./start.sh` offers to install any of these that are missing with
[Homebrew](https://brew.sh).

```bash
git clone https://github.com/theshubhamgour/CloudReader.git
cd CloudReader
./start.sh
```

The first run sets everything up (a few minutes, once). Then your browser opens **http://127.0.0.1:3000**.
Keep the terminal open while you use it, and press **Ctrl+C** to stop.

On a Mac you can also double-click **`Start CloudReader.command`** in Finder.

### Use it on your phone

```bash
./start.sh --phone
```

Open the address it prints (for example `http://192.168.1.20:3000`) on a phone connected to the same Wi-Fi.
In Safari or Chrome, tap **Share → Add to Home Screen** to open it like an app.
Anyone on that network can reach it, so only use `--phone` on a Wi-Fi network you trust.

---

## How to use it

| | |
|---|---|
| **Add a book** | On **Library**, drop a document onto **Add a Document** or click **Choose File**. Supported: `.docx`, `.epub`, `.txt`, `.md` (up to 50 MB). |
| **Listen** | Open the book and press **Play**. Playback begins as soon as the first part is ready. |
| **Pick up where you left off** | Your position is saved automatically. Press **Resume**. |
| **Bookmark a moment** | Press **Bookmark** on the book page, or **B** while listening. Tap a bookmark to jump back; tap **✕** to delete it. |
| **Rename a book** | Tap the ✎ pen next to its title. |
| **Download** | Use **Download Audiobook** for a ZIP of MP3s, or the ⬇ button on any chapter. |
| **Delete a book** | Use the 🗑 button on its cover in Library, or **Delete Book** on its page. |

Chapters are detected from heading styles (Word/EPUB/Markdown) or lines like "Chapter One", "Chapter 12: Title",
"Prologue" (plain text). A document without chapter headings becomes a single part.

### Keyboard shortcuts

| Key | Action |
|---|---|
| Space / K | Play / pause |
| ← / → | Back 15 s / forward 30 s |
| Shift + ← / → | Previous / next chapter |
| [ / ] | Slower / faster |
| M | Mute |
| B | Bookmark |

---

## Voices

Choose the voice in **Settings**.

### Local Voice (default)

This voice is free, works offline and needs no setup. CloudReader uses your operating system's speech engine
(macOS `say`). It sounds more robotic than AI narration, and nothing leaves your computer.

### Gemini AI Voice

For natural, expressive narration:

1. Create a free API key at **[Google AI Studio](https://aistudio.google.com/apikey)**.
   A Gemini app subscription doesn't include API access; the API key is separate.
2. In CloudReader, go to **Settings → Gemini AI Voice**, paste the key and press **Save**.
3. Pick **Fast** (starts playing sooner) or **Best Quality**, choose a voice, and press **Play Sample** to hear it.

The key is stored in your system keychain, never in the database or logs. You can also put it in
`backend/.env` as `GEMINI_API_KEY=...` (see `backend/.env.example`).

> **Free tier limits:** Gemini's free tier allows only about **10 requests per day** per model. That's enough
> to try a few samples, but a whole book needs many requests. When the limit runs out, CloudReader tells
> you right away and offers to switch to the local voice. For whole books, enable billing on your key
> (AI Studio → *Usage & Billing*).

**Cost with billing (estimates):** about **$0.50–$0.80 per hour of audio** in 2026, roughly doubling from
2027-01-01. A 90,000-word novel is around 10 hours. CloudReader shows an estimate on the book page before you
start, and caches every part so nothing is paid for twice. Details are in [docs/GEMINI_TTS_NOTES.md](docs/GEMINI_TTS_NOTES.md).

---

## Privacy

- There are no accounts, analytics or telemetry. The servers listen on `127.0.0.1` only, unless you use `--phone`.
- Import, chapter detection and the local voice run entirely on your computer.
- With the Gemini voice, the text being narrated is sent to Google, and nothing else is sent. On the free tier,
  Google may use that text to improve its products. Use a billed key if that matters to you.
- Everything lives in the `data/` folder. Back it up or delete it to start fresh.

---

## Troubleshooting

| Problem | Fix |
|---|---|
| "Can't reach the CloudReader backend" | Start with `./start.sh`. Make sure nothing else is using ports 8000/3000 (`lsof -i :8000`). |
| "Port … is already in use" | Close the other program, or stop an older CloudReader with Ctrl+C. |
| Phone says "This site can't be reached" | Type the full address with `http://`, exactly as `./start.sh --phone` prints it (including `:3000`). On **iPhone with Chrome** (or any browser other than Safari), turn on **Settings → Apps → Chrome → Local Network**. Make sure the phone is on the **same Wi-Fi** (its IP should start like the computer's, e.g. `192.168.0.`), turn off any VPN on the phone, and avoid guest networks, which block devices from reaching each other. If macOS asks whether to allow incoming connections for `node`, choose **Allow**. |
| `--phone` says it's already running | It was started without `--phone`. Answer **Y** to restart it with phone access. |
| "FFmpeg is missing" | `brew install ffmpeg` (macOS) or `sudo apt install ffmpeg` (Linux). |
| "Gemini's free daily limit is used up" | Switch to the local voice, wait for the reset time shown, or enable billing on your key. |
| "The Gemini API key was rejected" | Copy the key from AI Studio again and press **Check Key** in Settings. |
| Chapters detected wrongly | Use heading styles in Word (Heading 1 per chapter) and import again. |
| App was closed mid-narration | Start it again. Unfinished work resumes from where it stopped. |

Logs are written to `data/logs/cloudreader.log`.

---

## Development

```bash
./start.sh --dev                                  # hot-reloading servers
cd backend  && .venv/bin/python -m pytest -q      # backend tests (mocked voices, no API calls)
cd frontend && npm test && npm run lint           # frontend tests + lint
```

```
backend/            FastAPI (Python)
  app/manuscript/   importers (DOCX, EPUB, TXT, Markdown) + chapter detection
  app/processing/   segmenting text and preparing it for speech
  app/providers/    voice engines: local (macOS say) and Gemini; add new ones here
  app/services/     library, generation worker, export, costs, quota handling
  app/api/          HTTP routes
  tests/            pytest suite
frontend/           Next.js + React + Tailwind
  app/              pages: Library, Book, Settings, Now Playing
  components/       player, views, UI kit, cover and logo
  lib/              API client and formatting
docs/               Gemini TTS notes and a sample manuscript to try
start.sh            one-command setup and launcher
```

**Adding a voice engine:** implement `TTSProvider` in `backend/app/providers/` (voices, models, `synthesize`)
and register it in `registry.py`.

**Configuration:** settings can be overridden with environment variables or `backend/.env`. See
`backend/app/config.py`; for example, `CLOUDREADER_TTS_CONCURRENCY`, `CLOUDREADER_DATA_DIR`.

Try it out with [docs/Sample_Manuscript.docx](docs/Sample_Manuscript.docx).

## Known limitations

- The local voice uses macOS speech. On other systems it falls back to a test tone, so use Gemini there.
- PDF import isn't supported yet. Export to DOCX or EPUB instead.
- One narrator voice per book.

## Created by

<p align="center">
  <a href="https://github.com/theshubhamgour"><img src="https://github.com/theshubhamgour.png?size=200" width="100" alt="Shubham Gour"></a>
</p>

<h3 align="center">Shubham Gour</h3>

<p align="center">I build practical, open-source tools and teach tech on YouTube.</p>

<p align="center">
  <a href="https://youtube.com/shubhamgourtech"><img alt="YouTube" src="https://img.shields.io/badge/YouTube-Shubham%20Gour%20Tech-FF0000?style=for-the-badge&logo=youtube&logoColor=white"></a>
  <a href="https://www.linkedin.com/in/theshubhamgour/"><img alt="LinkedIn" src="https://img.shields.io/badge/LinkedIn-theshubhamgour-0A66C2?style=for-the-badge&logo=linkedin&logoColor=white"></a>
  <a href="https://github.com/theshubhamgour"><img alt="GitHub" src="https://img.shields.io/badge/GitHub-theshubhamgour-181717?style=for-the-badge&logo=github&logoColor=white"></a>
</p>

## Support

<p align="center">CloudReader is free and open source. If it's useful to you, you can support its development and more projects like it.</p>

<p align="center">
  <a href="https://razorpay.me/@decodethedeskbyshubhamgour"><img alt="Support this project" src="https://img.shields.io/badge/%E2%99%A5%20Support%20this%20project-Razorpay-FF2D55?style=for-the-badge"></a>
</p>

<p align="center">Starring ⭐ the repository, reporting bugs and sharing it with others helps too.</p>

## License

[MIT](LICENSE) © 2026 Shubham Gour
