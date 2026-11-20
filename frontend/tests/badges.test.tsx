import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { DemoBadge, StateBadge } from "@/components/ui";

describe("status badges", () => {
  it("labels local-voice audio clearly", () => {
    render(<DemoBadge />);
    expect(screen.getByText(/local voice/i)).toBeTruthy();
  });
  it("shows incomplete chapters clearly", () => {
    render(<StateBadge state="incomplete" extra="3/5" />);
    expect(screen.getByText("Incomplete · 3/5")).toBeTruthy();
  });
});
