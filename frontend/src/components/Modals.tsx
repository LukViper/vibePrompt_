import { FormEvent } from "react";
import type { ByokProvider, SpecificationResult } from "../types";

const BYOK_PROVIDERS: { id: ByokProvider; label: string; defaultModel: string }[] = [
  { id: "qwen", label: "Qwen (MuleRouter)", defaultModel: "qwen3.5-flash" },
  { id: "gemini", label: "Google Gemini", defaultModel: "gemini-2.0-flash" },
  { id: "openrouter", label: "OpenRouter", defaultModel: "openai/gpt-4o-mini" },
  { id: "groq", label: "Groq", defaultModel: "openai/gpt-oss-20b" },
];

export { BYOK_PROVIDERS };

type AuthProps = {
  mode: "login" | "register";
  email: string;
  password: string;
  busy: boolean;
  onEmail: (v: string) => void;
  onPassword: (v: string) => void;
  onClose: () => void;
  onSubmit: (e: FormEvent) => void;
};

export function AuthModal({
  mode,
  email,
  password,
  busy,
  onEmail,
  onPassword,
  onClose,
  onSubmit,
}: AuthProps) {
  return (
    <div className="modal-backdrop" onClick={onClose}>
      <form className="modal" onClick={(e) => e.stopPropagation()} onSubmit={onSubmit}>
        <h3>{mode === "register" ? "Create account" : "Sign in"}</h3>
        <label htmlFor="auth-email">Email</label>
        <input
          id="auth-email"
          type="email"
          value={email}
          onChange={(e) => onEmail(e.target.value)}
          required
          autoFocus
        />
        <label htmlFor="auth-password">Password</label>
        <input
          id="auth-password"
          type="password"
          value={password}
          onChange={(e) => onPassword(e.target.value)}
          required
          minLength={8}
        />
        <div className="modal-actions">
          <button className="btn btn-ghost" type="button" onClick={onClose}>
            Cancel
          </button>
          <button className="btn" type="submit" disabled={busy}>
            {mode === "register" ? "Register" : "Sign in"}
          </button>
        </div>
      </form>
    </div>
  );
}

type CreateProps = {
  name: string;
  objective: string;
  message: string;
  busy: boolean;
  onName: (v: string) => void;
  onObjective: (v: string) => void;
  onMessage: (v: string) => void;
  onClose: () => void;
  onSubmit: (e: FormEvent) => void;
};

export function CreateProjectModal({
  name,
  objective,
  message,
  busy,
  onName,
  onObjective,
  onMessage,
  onClose,
  onSubmit,
}: CreateProps) {
  return (
    <div className="modal-backdrop" onClick={onClose}>
      <form className="modal" onClick={(e) => e.stopPropagation()} onSubmit={onSubmit}>
        <h3>New project</h3>
        <label htmlFor="name">Name</label>
        <input
          id="name"
          value={name}
          onChange={(e) => onName(e.target.value)}
          required
          autoFocus
        />
        <label htmlFor="objective">Objective (optional)</label>
        <textarea
          id="objective"
          rows={2}
          value={objective}
          onChange={(e) => onObjective(e.target.value)}
        />
        <label htmlFor="initial">Initial idea (optional)</label>
        <textarea
          id="initial"
          rows={3}
          value={message}
          onChange={(e) => onMessage(e.target.value)}
          placeholder="Describe what you want to build…"
        />
        <div className="modal-actions">
          <button className="btn btn-ghost" type="button" onClick={onClose}>
            Cancel
          </button>
          <button className="btn" type="submit" disabled={busy}>
            Create
          </button>
        </div>
      </form>
    </div>
  );
}

type ByokProps = {
  provider: ByokProvider;
  model: string;
  apiKey: string;
  baseUrl: string;
  remaining: number | null;
  allocated: number | null;
  connected: boolean;
  busy: boolean;
  onProvider: (p: ByokProvider, defaultModel: string) => void;
  onModel: (v: string) => void;
  onKey: (v: string) => void;
  onBaseUrl: (v: string) => void;
  onClose: () => void;
  onSubmit: (e: FormEvent) => void;
};

export function ByokModal({
  provider,
  model,
  apiKey,
  baseUrl,
  remaining,
  allocated,
  connected,
  busy,
  onProvider,
  onModel,
  onKey,
  onBaseUrl,
  onClose,
  onSubmit,
}: ByokProps) {
  return (
    <div className="modal-backdrop" onClick={onClose}>
      <form
        className="modal byok-modal"
        onClick={(e) => e.stopPropagation()}
        onSubmit={onSubmit}
      >
        <h3>API configuration</h3>
        <p className="muted" style={{ marginTop: 0 }}>
          Your API key is encrypted at rest and never returned by the API.
        </p>

        <p className="field-label">Provider</p>
        <div className="provider-chips" role="group" aria-label="Provider">
          {BYOK_PROVIDERS.map((p) => (
            <button
              key={p.id}
              type="button"
              className={`provider-chip ${provider === p.id ? "active" : ""}`}
              onClick={() => onProvider(p.id, p.defaultModel)}
            >
              {p.label.split(" ")[0]}
            </button>
          ))}
        </div>

        <label htmlFor="byok-model">Model</label>
        <input
          id="byok-model"
          value={model}
          onChange={(e) => onModel(e.target.value)}
          required
        />
        <label htmlFor="byok-key">API key</label>
        <input
          id="byok-key"
          type="password"
          value={apiKey}
          onChange={(e) => onKey(e.target.value)}
          required
          minLength={8}
          autoComplete="off"
        />
        <label htmlFor="byok-base">Base URL (optional)</label>
        <input
          id="byok-base"
          value={baseUrl}
          onChange={(e) => onBaseUrl(e.target.value)}
          placeholder="Leave blank for provider default"
        />

        <div className={`connection-status ${connected ? "ok" : ""}`}>
          <span className="dot" />
          {connected
            ? `Connected · ${remaining ?? "—"} / ${allocated ?? "—"} free generations remaining`
            : "Not connected — validate a key to continue after free tier"}
        </div>

        <div className="modal-actions">
          <button className="btn btn-ghost" type="button" onClick={onClose}>
            Cancel
          </button>
          <button className="btn" type="submit" disabled={busy}>
            Validate &amp; save
          </button>
        </div>
      </form>
    </div>
  );
}

type SpecProps = {
  spec: SpecificationResult;
  onClose: () => void;
};

export function SpecModal({ spec, onClose }: SpecProps) {
  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal spec-modal" onClick={(e) => e.stopPropagation()}>
        <div className="spec-header">
          <h3>Specification</h3>
          <span className={`readiness-badge ${spec.readiness.status}`}>
            {spec.readiness.status.replace(/_/g, " ")}
          </span>
        </div>
        <pre>{spec.markdown}</pre>
        <div className="modal-actions">
          <button
            className="btn btn-ghost"
            type="button"
            onClick={() => void navigator.clipboard.writeText(spec.markdown)}
          >
            Copy markdown
          </button>
          <button className="btn" type="button" onClick={onClose}>
            Close
          </button>
        </div>
      </div>
    </div>
  );
}
