import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

function OfflineBanner({ offline }: { offline: boolean }) {
  if (!offline) return null;
  return (
    <div className="offline-banner" role="status">
      Offline heuristic mode — not live adversarial review.
    </div>
  );
}

describe("Offline honesty banner", () => {
  it("renders the exact honesty copy when offline", () => {
    render(<OfflineBanner offline />);
    expect(
      screen.getByText("Offline heuristic mode — not live adversarial review.")
    ).toBeInTheDocument();
  });

  it("hides when live review is active", () => {
    const { container } = render(<OfflineBanner offline={false} />);
    expect(container).toBeEmptyDOMElement();
  });
});
