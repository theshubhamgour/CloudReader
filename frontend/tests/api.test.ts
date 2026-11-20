import { afterEach, describe, expect, it, vi } from "vitest";
import { api, ApiError } from "@/lib/api";

afterEach(() => vi.unstubAllGlobals());

describe("api client", () => {
  it("surfaces the backend's error message", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ detail: "PDF import is not supported yet.", code: "manuscript_error" }), { status: 400 })));
    await expect(api.books()).rejects.toMatchObject({ message: "PDF import is not supported yet.", status: 400, code: "manuscript_error" });
  });
  it("explains when the backend is offline", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => { throw new TypeError("fetch failed"); }));
    const err = await api.books().catch((e) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err.message).toMatch(/backend/);
  });
  it("sends JSON bodies to the proxied /api path", async () => {
    const f = vi.fn(async () => new Response("{}", { status: 200 }));
    vi.stubGlobal("fetch", f);
    await api.saveProgress(3, 7, 12.5, 1.25);
    const [url, init] = f.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("/api/books/3/progress");
    expect(init.method).toBe("PUT");
    expect(JSON.parse(init.body as string)).toEqual({ chapter_id: 7, position_s: 12.5, playback_rate: 1.25 });
  });
});
