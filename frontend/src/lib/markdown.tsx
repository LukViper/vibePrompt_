import type { ReactNode } from "react";

/** Lightweight markdown renderer — no extra dependencies. */
export function renderMarkdown(source: string): ReactNode[] {
  const blocks = source.split(/\n```/);
  const nodes: ReactNode[] = [];

  blocks.forEach((chunk, i) => {
    if (i % 2 === 1) {
      const nl = chunk.indexOf("\n");
      const lang = nl === -1 ? "" : chunk.slice(0, nl).trim();
      const code = nl === -1 ? chunk : chunk.slice(nl + 1).replace(/\n$/, "");
      nodes.push(
        <pre key={`code-${i}`} className="md-code" data-lang={lang || undefined}>
          <code>{code}</code>
        </pre>
      );
      return;
    }

    const paragraphs = chunk.split(/\n{2,}/);
    paragraphs.forEach((para, pi) => {
      const trimmed = para.trim();
      if (!trimmed) return;

      if (/^[-*] /.test(trimmed) || /^\d+\. /.test(trimmed)) {
        const items = trimmed.split("\n").filter(Boolean);
        nodes.push(
          <ul key={`list-${i}-${pi}`} className="md-list">
            {items.map((item, ii) => (
              <li key={ii}>{inline(item.replace(/^([-*]|\d+\.)\s+/, ""))}</li>
            ))}
          </ul>
        );
        return;
      }

      if (trimmed.startsWith("# ")) {
        nodes.push(
          <h3 key={`h-${i}-${pi}`} className="md-h">
            {inline(trimmed.slice(2))}
          </h3>
        );
        return;
      }

      nodes.push(
        <p key={`p-${i}-${pi}`} className="md-p">
          {inline(trimmed)}
        </p>
      );
    });
  });

  return nodes;
}

function inline(text: string): ReactNode[] {
  const parts = text.split(/(`[^`]+`|\*\*[^*]+\*\*)/g);
  return parts.map((part, i) => {
    if (part.startsWith("`") && part.endsWith("`")) {
      return (
        <code key={i} className="md-inline-code">
          {part.slice(1, -1)}
        </code>
      );
    }
    if (part.startsWith("**") && part.endsWith("**")) {
      return <strong key={i}>{part.slice(2, -2)}</strong>;
    }
    return <span key={i}>{part}</span>;
  });
}
