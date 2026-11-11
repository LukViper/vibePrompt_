import type { Message } from "../types";
import { renderMarkdown } from "../lib/markdown";

type Props = {
  message: Message;
  onCopy?: (content: string) => void;
};

export function MessageBubble({ message, onCopy }: Props) {
  const isUser = message.role === "user";
  const role =
    message.role === "user"
      ? "You"
      : message.role === "system"
        ? "System"
        : "VibePrompt";

  return (
    <article className={`msg ${isUser ? "msg-user" : "msg-assistant"}`}>
      <header className="msg-meta">
        <span className="msg-role">{role}</span>
      </header>
      <div className="msg-body">
        {isUser ? message.content : renderMarkdown(message.content)}
      </div>
      {!isUser && (
        <footer className="msg-actions">
          <button
            type="button"
            className="btn btn-ghost btn-sm"
            onClick={() => onCopy?.(message.content)}
          >
            Copy
          </button>
        </footer>
      )}
    </article>
  );
}
