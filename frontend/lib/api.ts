// Typed client for the CloudReader FastAPI backend (proxied at /api).

export class ApiError extends Error {
  constructor(message: string, public status: number, public code?: string) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`/api${path}`, {
      ...init,
      headers: init?.body instanceof FormData ? init.headers : { "Content-Type": "application/json", ...init?.headers },
    });
  } catch {
    throw new ApiError("Can't reach the CloudReader backend. Is it running? (./start.sh)", 0, "offline");
  }
  if (!res.ok) {
    let detail = res.statusText;
    let code: string | undefined;
    try {
      const body = await res.json();
      detail = typeof body.detail === "string" ? body.detail : body.detail?.[0]?.msg ?? JSON.stringify(body.detail);
      code = body.code;
    } catch {}
    if (res.status === 500 && !code) detail = "The backend is not responding. Start it with ./start.sh";
    throw new ApiError(detail, res.status, code);
  }
  return res.json() as Promise<T>;
}

const json = (method: string, body?: unknown): RequestInit => ({ method, body: body === undefined ? undefined : JSON.stringify(body) });

// ---------------------------------------------------------------- types

export type ChapterState = "not_generated" | "partial" | "generating" | "ready" | "incomplete" | "outdated";

export interface ChapterStatus {
  state: ChapterState;
  segments_total: number;
  segments_completed: number;
  segments_failed: number;
  audio_ready: boolean;
  duration_s: number | null;
  is_demo: boolean | null;
  narrator: string | null;
  active_job_id: number | null;
}

export interface Chapter {
  id: number;
  book_id: number;
  position: number;
  title: string;
  word_count: number;
  estimated_minutes: number;
  status: ChapterStatus;
  paragraphs?: string[];
}

export interface Book {
  id: number;
  title: string;
  author: string;
  source_filename: string;
  source_format: string;
  has_cover: boolean;
  chapter_count: number;
  word_count: number;
  estimated_minutes: number;
  chapters_ready: number;
  audio_duration_s: number;
  listening_progress: number;
  progress: { chapter_id: number; position_s: number; playback_rate: number; updated_at: string } | null;
  narration_profile_id: number | null;
  any_generating: boolean;
  chapters?: Chapter[];
}

export interface Voice { id: string; name: string; description: string }
export interface ModelInfo { id: string; label: string; description: string; max_input_tokens: number | null }
export interface Capabilities {
  style_instructions: boolean;
  inline_tags: boolean;
  speed_control: "none" | "instruction" | "numeric";
  language_selection: boolean;
  voice_preview: boolean;
  multi_speaker: number;
  notes: string[];
}
export interface Provider {
  id: string;
  label: string;
  is_demo: boolean;
  available: boolean;
  unavailable_reason: string | null;
  capabilities: Capabilities;
  models: ModelInfo[];
  voices: Voice[];
}

export interface Profile {
  id: number;
  name: string;
  provider: string;
  model: string;
  voice: string;
  style_key: string;
  pace: string;
  language: string | null;
  delivery_notes: string;
  output_format: string;
  is_default: number | boolean;
}
export type ProfileInput = Omit<Profile, "id" | "is_default"> & { is_default: boolean };

export interface StyleOption { key: string; label: string; description?: string; instruction: string }

export interface Segment {
  id: number;
  position: number;
  source_text: string;
  tts_text: string;
  replacements: { kind: string; original: string; spoken: string }[];
  analysis: { passage_type: string; dialogue_ratio: number; emotional_intensity: string; characters: string[]; suggested_pacing: string };
  style_instruction: string;
  status: "pending" | "processing" | "completed" | "failed" | "cancelled";
  attempts: number;
  error: string | null;
  duration_s: number | null;
  is_demo: number | null;
  has_audio: boolean;
}

export interface Estimate {
  words: number;
  characters: number;
  estimated_audio_minutes: number;
  is_estimate: true;
  cost_usd: number | null;
  input_tokens: number | null;
  output_tokens: number | null;
  pricing_note: string | null;
}

export interface PrepareResult {
  total_segments: number;
  reused_segments: number;
  pending_characters: number;
  estimate: Estimate;
  large_job: boolean;
  profile_id: number;
}

export interface BookPlan {
  profile_id: number;
  profile_name: string;
  chapters: number;
  chapter_ids: number[];
  segments: number;
  reused_segments: number;
  estimate: Estimate;
  large_job: boolean;
}

export interface Job {
  id: number;
  book_id: number;
  chapter_id: number;
  profile_id: number | null;
  status: "pending" | "processing" | "completed" | "failed" | "cancelled";
  total_segments: number;
  completed_segments: number;
  failed_segments: number;
  reused_segments: number;
  error: string | null;
  cancel_requested: boolean;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  chapter_title: string;
  book_title: string;
  profile_name: string | null;
  provider: string | null;
}

export interface PreviewResult {
  url: string;
  cached: boolean;
  is_demo: boolean;
  text: string;
  tts_text: string;
  style_instruction: string;
  voice: string;
  model: string;
}

export interface Pronunciation { id: number; term: string; replacement: string; notes: string; chapter_id: number | null; case_sensitive: number }
export interface Character { id: number; name: string; description: string }
export interface Bookmark { id: number; chapter_id: number; position_s: number; label: string; chapter_title: string; chapter_position: number }

export interface AppSettings {
  app_name: string;
  gemini: { configured: boolean; source: "env" | "keychain" | "none"; masked_key: string | null; default_model: string };
  ffmpeg_available: boolean;
  data_dir: string;
  disk_free_gb: number;
  segment_target_chars: number;
  large_job_word_threshold: number;
}

export interface EngineInfo {
  provider: string;
  available: boolean;
  unavailable_reason: string | null;
  model: string;
  /** Set when the daily quota is used up: why, and when it resets. */
  blocked: string | null;
  models: { id: string; label: string; fast: boolean }[];
  voices: Voice[];
}
export type Engine = "local" | "gemini";
export interface VoiceSettings {
  engine: Engine;
  voice: string;
  profile_id: number;
  engines: Record<Engine, EngineInfo>;
}

export interface UsageRow { provider: string; model: string; kind: string; requests: number; characters: number; input_tokens: number | null; output_tokens: number | null; audio_seconds: number | null; cost_usd: number | null }

// ---------------------------------------------------------------- endpoints

export const api = {
  books: () => request<Book[]>("/books"),
  book: (id: number) => request<Book>(`/books/${id}`),
  importBook: (file: File, title?: string, author?: string) => {
    const fd = new FormData();
    fd.append("file", file);
    if (title) fd.append("title", title);
    if (author) fd.append("author", author);
    return request<Book>("/books/import", { method: "POST", body: fd });
  },
  updateBook: (id: number, body: Partial<Pick<Book, "title" | "author" | "narration_profile_id">>) =>
    request<Book>(`/books/${id}`, json("PATCH", body)),
  deleteBook: (id: number) => request(`/books/${id}`, json("DELETE")),
  uploadCover: (id: number, file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    return request(`/books/${id}/cover`, { method: "POST", body: fd });
  },

  chapter: (id: number) => request<Chapter>(`/chapters/${id}`),
  segments: (chapterId: number) => request<Segment[]>(`/chapters/${chapterId}/segments`),
  prepare: (chapterId: number, profileId?: number) =>
    request<PrepareResult>(`/chapters/${chapterId}/prepare${profileId ? `?profile_id=${profileId}` : ""}`, json("POST")),
  renameChapter: (id: number, title: string) => request(`/chapters/${id}`, json("PATCH", { title })),
  splitChapter: (id: number, at_paragraph: number, new_title?: string) =>
    request<{ new_chapter_id: number }>(`/chapters/${id}/split`, json("POST", { at_paragraph, new_title })),
  mergeNext: (id: number) => request(`/chapters/${id}/merge-next`, json("POST")),
  deleteChapter: (id: number) => request(`/chapters/${id}`, json("DELETE")),
  reorder: (bookId: number, chapter_ids: number[]) => request<Book>(`/books/${bookId}/chapters/reorder`, json("POST", { chapter_ids })),
  createChapter: (bookId: number, title: string, text: string) => request(`/books/${bookId}/chapters`, json("POST", { title, text })),

  providers: () => request<Provider[]>("/providers"),
  styles: () => request<{ styles: StyleOption[]; paces: StyleOption[] }>("/styles"),
  profiles: () => request<Profile[]>("/profiles"),
  createProfile: (p: ProfileInput) => request<Profile>("/profiles", json("POST", p)),
  updateProfile: (id: number, p: ProfileInput) => request<Profile>(`/profiles/${id}`, json("PUT", p)),
  deleteProfile: (id: number) => request(`/profiles/${id}`, json("DELETE")),
  preview: (body: { provider: string; model: string; voice: string; style_key: string; pace: string; delivery_notes: string; text?: string; chapter_id?: number; book_id?: number }) =>
    request<PreviewResult>("/preview", json("POST", body)),

  bookPlan: (bookId: number, profileId?: number) =>
    request<BookPlan>(`/books/${bookId}/plan${profileId ? `?profile_id=${profileId}` : ""}`),
  generateBook: (bookId: number, profile_id?: number, from_chapter_id?: number) =>
    request<{ jobs: number[]; already_running: number; chapters: number }>(`/books/${bookId}/generate`, json("POST", { profile_id, from_chapter_id })),
  cancelBook: (bookId: number) => request<{ cancelled: number }>(`/books/${bookId}/cancel`, json("POST")),
  startJob: (chapter_id: number, profile_id?: number) => request<Job>("/jobs", json("POST", { chapter_id, profile_id })),
  jobs: () => request<Job[]>("/jobs"),
  job: (id: number) => request<Job>(`/jobs/${id}`),
  cancelJob: (id: number) => request<Job>(`/jobs/${id}/cancel`, json("POST")),
  retryJob: (id: number) => request<Job>(`/jobs/${id}/retry`, json("POST")),
  regenerateSegment: (id: number) => request<Job>(`/segments/${id}/regenerate`, json("POST")),
  usage: () => request<{ rows: UsageRow[]; note: string }>("/usage"),

  saveProgress: (bookId: number, chapter_id: number, position_s: number, playback_rate: number) =>
    request(`/books/${bookId}/progress`, json("PUT", { chapter_id, position_s, playback_rate })),
  latestProgress: () => request<{ book_id?: number; chapter_id?: number; position_s?: number; playback_rate?: number }>("/progress/latest"),
  bookmarks: (bookId: number) => request<Bookmark[]>(`/books/${bookId}/bookmarks`),
  addBookmark: (bookId: number, chapter_id: number, position_s: number, label = "") =>
    request<Bookmark>(`/books/${bookId}/bookmarks`, json("POST", { chapter_id, position_s, label })),
  deleteBookmark: (id: number) => request(`/bookmarks/${id}`, json("DELETE")),

  pronunciations: (bookId: number) => request<Pronunciation[]>(`/books/${bookId}/pronunciations`),
  addPronunciation: (bookId: number, p: { term: string; replacement: string; notes: string; chapter_id: number | null; case_sensitive: boolean }) =>
    request<Pronunciation>(`/books/${bookId}/pronunciations`, json("POST", p)),
  deletePronunciation: (id: number) => request(`/pronunciations/${id}`, json("DELETE")),
  characters: (bookId: number) => request<Character[]>(`/books/${bookId}/characters`),
  addCharacter: (bookId: number, name: string, description: string) => request<Character>(`/books/${bookId}/characters`, json("POST", { name, description })),
  deleteCharacter: (id: number) => request(`/characters/${id}`, json("DELETE")),

  settings: () => request<AppSettings>("/settings"),
  saveKey: (api_key: string) => request<AppSettings>("/settings/gemini-key", json("PUT", { api_key })),
  removeKey: () => request<AppSettings>("/settings/gemini-key", json("DELETE")),
  voiceSettings: () => request<VoiceSettings>("/settings/voice"),
  setVoice: (engine: Engine, voice?: string, model?: string) => request<VoiceSettings>("/settings/voice", json("PUT", { engine, voice, model })),
  testKey: () => request<{ ok: boolean; error?: string; model?: string }>("/settings/gemini-key/test", json("POST")),
};

export const audioUrl = (chapterId: number) => `/api/chapters/${chapterId}/audio`;
export const exportUrl = (chapterId: number, format = "mp3") => `/api/chapters/${chapterId}/export?format=${format}`;
export const bookExportUrl = (bookId: number, format = "mp3") => `/api/books/${bookId}/export?format=${format}`;
export const coverUrl = (bookId: number) => `/api/books/${bookId}/cover`;
export const segmentAudioUrl = (id: number, download = false) => `/api/segments/${id}/audio${download ? "?download=true" : ""}`;
