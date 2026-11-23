import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { ByokModal } from "./Modals";

describe("ByokModal provider key links", () => {
  it("updates the console link when switching providers", async () => {
    const user = userEvent.setup();
    const onProvider = vi.fn();
    render(
      <ByokModal
        provider="qwen"
        model="qwen3.5-flash"
        apiKey=""
        baseUrl=""
        remaining={8}
        allocated={8}
        connected={false}
        busy={false}
        onProvider={onProvider}
        onModel={vi.fn()}
        onKey={vi.fn()}
        onBaseUrl={vi.fn()}
        onClose={vi.fn()}
        onSubmit={vi.fn()}
      />
    );

    const qwenLink = screen.getByRole("link", { name: /Get Qwen API key/i });
    expect(qwenLink).toHaveAttribute(
      "href",
      "https://bailian.console.alibabacloud.com/?apiKey=1"
    );
    expect(qwenLink).toHaveAttribute("target", "_blank");
    expect(qwenLink).toHaveAttribute("rel", expect.stringContaining("noopener"));

    await user.click(screen.getByRole("button", { name: /^Google$/i }));
    expect(onProvider).toHaveBeenCalledWith("gemini", "gemini-2.0-flash");
  });

  it("shows Google key link when gemini is selected", () => {
    render(
      <ByokModal
        provider="gemini"
        model="gemini-2.0-flash"
        apiKey=""
        baseUrl=""
        remaining={null}
        allocated={null}
        connected={false}
        busy={false}
        onProvider={vi.fn()}
        onModel={vi.fn()}
        onKey={vi.fn()}
        onBaseUrl={vi.fn()}
        onClose={vi.fn()}
        onSubmit={vi.fn()}
      />
    );
    const link = screen.getByRole("link", { name: /Get Google AI Studio key/i });
    expect(link).toHaveAttribute("href", "https://aistudio.google.com/app/apikey");
  });
});
