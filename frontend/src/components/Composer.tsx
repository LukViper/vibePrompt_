import { FormEvent, KeyboardEvent } from "react";

type Props = {
  draft: string;
  busy: boolean;
  disabled: boolean;
  onDraftChange: (value: string) => void;
  onSubmit: (e: FormEvent) => void;
};

export function Composer({
  draft,
  busy,
  disabled,
  onDraftChange,
  onSubmit,
}: Props) {
  function onKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      onSubmit(e);
    }
  }

  return (
    <form className="composer" onSubmit={onSubmit}>
      <div className={`composer-box ${disabled ? "disabled" : ""}`}>
        <textarea
          value={draft}
          onChange={(e) => onDraftChange(e.target.value)}
          placeholder="Ask about your idea, decisions, or next steps…"
          rows={2}
          disabled={busy || disabled}
          onKeyDown={onKeyDown}
          aria-label="Message"
        />
        <div className="composer-toolbar">
          <span className="composer-shortcut">Enter to send · Shift+Enter newline</span>
          <button
            className="btn"
            type="submit"
            disabled={busy || disabled || !draft.trim()}
          >
            {busy ? "Thinking…" : "Send"}
          </button>
        </div>
      </div>
    </form>
  );
}
