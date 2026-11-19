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
    const mod = e.metaKey || e.ctrlKey;
    if (mod && e.key === "Enter") {
      e.preventDefault();
      onSubmit(e);
      return;
    }
    if (e.key === "Enter" && !e.shiftKey && !mod) {
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
          placeholder="Assert a decision, provide evidence, or revise the stack…"
          rows={2}
          disabled={busy || disabled}
          onKeyDown={onKeyDown}
          aria-label="Message"
        />
        <div className="composer-toolbar">
          <span className="composer-shortcut">
            ⌘/Ctrl+Enter · Enter to send · Esc closes modals
          </span>
          <button
            className="btn"
            type="submit"
            disabled={busy || disabled || !draft.trim()}
          >
            {busy ? "Reviewing…" : "Send"}
          </button>
        </div>
      </div>
    </form>
  );
}
