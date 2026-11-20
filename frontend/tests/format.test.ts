import { describe, expect, it } from "vitest";
import { formatDuration, formatTime, formatUsd } from "@/lib/format";

describe("formatTime", () => {
  it("formats minutes and hours", () => {
    expect(formatTime(0)).toBe("0:00");
    expect(formatTime(75.9)).toBe("1:15");
    expect(formatTime(3725)).toBe("1:02:05");
  });
  it("is safe for bad input", () => {
    expect(formatTime(NaN)).toBe("0:00");
    expect(formatTime(null)).toBe("0:00");
    expect(formatTime(-3)).toBe("0:00");
  });
});

describe("formatDuration / formatUsd", () => {
  it("renders estimates readably", () => {
    expect(formatDuration(0.4)).toBe("< 1 min");
    expect(formatDuration(95)).toBe("1 h 35 min");
    expect(formatUsd(null)).toBe("—");
    expect(formatUsd(0.004)).toBe("< $0.01");
    expect(formatUsd(1.234)).toBe("$1.23");
  });
});
