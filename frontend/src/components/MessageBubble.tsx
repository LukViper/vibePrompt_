import type { Message } from "../types";
import { renderMarkdown } from "../lib/markdown";

type Props = {
  message: Message;
  techStack?: string[];
  rejectedApproaches?: { approach: string }[];
  onCopy?: (content: string) => void;
};

/** Pull LOCKED / REJECTED tokens already present in mentor text, plus stack state. */
function extractStateBadges(
  content: string,
  techStack: string[],
  rejected: { approach: string }[]
): { label: string; kind: "locked" | "rejected" }[] {
  const found: { label: string; kind: "locked" | "rejected" }[] = [];
  const seen = new Set<string>();

  const re = /([A-Za-z0-9][\w.+/#-]{1,40})\s*:\s*(LOCKED|REJECTED)/gi;
  let m: RegExpExecArray | null;
  while ((m = re.exec(content)) !== null) {
    const key = `${m[1].toLowerCase()}:${m[2].toLowerCase()}`;
    if (seen.has(key)) continue;
    seen.add(key);
    found.push({
      label: `${m[1]}: ${m[2].toUpperCase()}`,
      kind: m[2].toUpperCase() === "LOCKED" ? "locked" : "rejected",
    });
  }

  if (found.length === 0) {
    for (const t of techStack.slice(0, 4)) {
      const key = `lock:${t.toLowerCase()}`;
      if (seen.has(key)) continue;
      if (content.toLowerCase().includes(t.toLowerCase())) {
        seen.add(key);
        found.push({ label: `${t}: LOCKED`, kind: "locked" });
      }
    }
    for (const r of rejected.slice(0, 4)) {
      const key = `rej:${r.approach.toLowerCase()}`;
      if (seen.has(key)) continue;
      if (content.toLowerCase().includes(r.approach.toLowerCase())) {
        seen.add(key);
        found.push({ label: `${r.approach}: REJECTED`, kind: "rejected" });
      }
    }
  }

  return found.slice(0, 6);
}

export function MessageBubble({
  message,
  techStack = [],
  rejectedApproaches = [],
  onCopy,
}: Props) {
  const isUser = message.role === "user";
  const role =
    message.role === "user"
      ? "Assertion"
      : message.role === "system"
        ? "System"
        : "Mentor brief";

  const badges =
    !isUser
      ? extractStateBadges(message.content, techStack, rejectedApproaches)
      : [];

  return (
    <article className={`msg ${isUser ? "msg-user" : "msg-assistant"}`}>
      <header className="msg-meta">
        <span className="msg-role">{role}</span>
        {message.finding_ids.length > 0 && (
          <span className="state-badge blocking">
            {message.finding_ids.length} finding
            {message.finding_ids.length === 1 ? "" : "s"}
          </span>
        )}
      </header>
      <div className="msg-body">
        {isUser ? message.content : renderMarkdown(message.content)}
      </div>
      {badges.length > 0 && (
        <div className="inline-badges">
          {badges.map((b) => (
            <span key={b.label} className={`state-badge ${b.kind}`}>
              {b.label}
            </span>
          ))}
        </div>
      )}
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
