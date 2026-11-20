# Gemini TTS — verified notes (checked 2026-10-30)

Sources: ai.google.dev/gemini-api/docs/speech-generation, /models, /pricing, /rate-limits,
model cards for `gemini-3.8-flash-tts` and `gemini-3.8-flash-lite-tts` (pages updated
2026-10-28/29), plus inspection of the installed `google-genai` 2.34.0 SDK types.

## Access

- Requires a **Gemini API key** from Google AI Studio (https://aistudio.google.com/apikey).
  A Google Gemini Pro *consumer* subscription does **not** include API access or credits.
- A free tier exists for the 3.8 TTS models (rate-limited; limits shown only in AI Studio).
  Google may use free-tier inputs to improve its products — use a billed key if that matters.

## Models

| Model ID | Status | Notes |
|---|---|---|
| `gemini-3.8-flash-tts` | Stable | Flagship, most expressive, 130+ languages. CloudReader's **Best Quality** option. |
| `gemini-3.8-flash-lite-tts` | Stable | Cheaper/faster, 100+ languages. CloudReader's **Fast** option (default). |
| `gemini-3.1-flash-tts-preview` | Preview (legacy) | Not offered by CloudReader. |

## API shape (Interactions API; REST `POST https://generativelanguage.googleapis.com/v1beta/interactions`)

```python
client.interactions.create(
    model="gemini-3.8-flash-tts",
    input=[{"type": "user_input", "content": [{
        "type": "text", "text": "<verbatim transcript>",
        "annotations": [{"type": "speech_metadata", "style": "warm, measured storytelling"}],
    }]}],
    response_format={"type": "audio", "mime_type": "audio/wav", "sample_rate": 24000},
    generation_config={"speech_config": [{"voice": "Kore"}]},
)
audio = base64.b64decode(interaction.output_audio.data)
```

- Output: WAV, 24 kHz, mono, 16-bit PCM (default for unary requests).
- Usage: `interaction.usage.total_input_tokens / total_output_tokens`.
- Errors: `google.genai._gaos.errors.GenAiError` with `.status_code`.

## Limits

- Input: 8,192 tokens. Output: 16,384 tokens; at 25 audio tokens/s ≈ 10.9 minutes.
- Text-only input, audio-only output.
- Multi-speaker in one request: max 2 prebuilt voices (future character-voice work).

## Style control (what is actually supported)

- `speech_metadata.style`: natural-language delivery, emotion, pacing, volume
  (e.g. "speaking slowly", "warm and enthusiastic").
- Inline tags in angle brackets inside the text: `<short pause>`, `<long pause>`, `<sigh>`, …
  → CloudReader escapes literal `<`/`>` in the manuscript so prose is never misread as a tag.
- The `text` field is a **verbatim transcript** — stage directions in the text are read aloud.
  So delivery instructions go only in `style`, never in the text.
- **No numeric speed/pitch parameter.** Speed is expressed as words in `style`.
- Accent is a property of the voice; docs say not to change accent via `style`.
- Language is auto-detected.

## Prebuilt voices (30)

Zephyr (Bright), Puck (Upbeat), Charon (Informative), Kore (Firm), Fenrir (Excitable),
Leda (Youthful), Orus (Firm), Aoede (Breezy), Callirrhoe (Easy-going), Autonoe (Bright),
Enceladus (Breathy), Iapetus (Clear), Umbriel (Easy-going), Algieba (Smooth),
Despina (Smooth), Erinome (Clear), Algenib (Gravelly), Rasalgethi (Informative),
Laomedeia (Upbeat), Achernar (Soft), Alnilam (Firm), Schedar (Even), Gacrux (Mature),
Pulcherrima (Forward), Achird (Friendly), Zubenelgenubi (Casual), Vindemiatrix (Gentle),
Sadachbia (Lively), Sadaltager (Knowledgeable), Sulafat (Warm).

## Pricing (paid tier, USD per 1M tokens)

| Model | Text input | Audio output | Valid |
|---|---|---|---|
| gemini-3.8-flash-tts | $0.50 | $9.00 | through 2026-12-31 |
| gemini-3.8-flash-tts | $1.00 | $18.00 | from 2027-01-01 |
| gemini-3.8-flash-lite-tts | $0.50 | $6.00 | through 2026-12-31 |
| gemini-3.8-flash-lite-tts | $1.00 | $12.00 | from 2027-01-01 |

Audio = 25 tokens per second → 1 hour of audio ≈ 90,000 tokens ≈ $0.81 (flash, 2026 price).
The lite input price came from a summarised read of the pricing page — re-check it there.
CloudReader labels every cost figure as an estimate.

## Rate limits

Not published in the docs; visible in AI Studio (https://aistudio.google.com/rate-limit).

**Observed 2026-10-30:** the free tier allows **10 requests per day** for
`gemini-3.8-flash-tts`. The API answers HTTP 429 with
`"Rate limit exceeded … (limit: 10 requests per day on Free Tier). Please retry in 1h15m50s"`.
That is far too few for a book, so narrating a novel needs billing enabled on the key.

CloudReader stops a job immediately on a daily-limit 429 (with the reset time), and backs
off and retries on per-minute 429s.

## SDK note

`google-genai` 2.34 silently retries 429 responses for as long as the server's retry-after
(over an hour), ignoring the configured timeout. CloudReader therefore sends synthesis
requests to the documented REST endpoint (`POST /v1beta/interactions`, header
`x-goog-api-key`) itself. The request and response shapes are identical to the SDK's.
