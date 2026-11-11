import { FormEvent, useCallback, useEffect, useState } from "react";
import { api } from "../api/client";
import type {
  AcquisitionReport,
  BookPreview,
  BookRecord,
  CatalogBook,
  SkillPackage,
  SkillSummary,
} from "../types";

type Tab = "collection" | "catalog" | "skills" | "generate";

type Props = {
  onClose: () => void;
  onError: (msg: string) => void;
};

const RIGHTS_FALLBACK =
  "I confirm I have the legal right to upload and process this material for generating abstracted skill instructions, and I will not use VibePrompt to reproduce substantial copyrighted passages.";

export function KnowledgeLibrary({ onClose, onError }: Props) {
  const [tab, setTab] = useState<Tab>("collection");
  const [books, setBooks] = useState<BookRecord[]>([]);
  const [catalog, setCatalog] = useState<CatalogBook[]>([]);
  const [skills, setSkills] = useState<SkillSummary[]>([]);
  const [preview, setPreview] = useState<BookPreview | null>(null);
  const [skillDetail, setSkillDetail] = useState<SkillPackage | null>(null);
  const [report, setReport] = useState<AcquisitionReport | null>(null);
  const [busy, setBusy] = useState(false);
  const [query, setQuery] = useState("");
  const [rightsText, setRightsText] = useState(RIGHTS_FALLBACK);
  const [uploadSlug, setUploadSlug] = useState("");
  const [genBookIds, setGenBookIds] = useState<string[]>([]);
  const [genSlug, setGenSlug] = useState("grill");
  const [evalResult, setEvalResult] = useState<Record<string, unknown> | null>(null);

  const refresh = useCallback(async () => {
    const [b, c, s, rights] = await Promise.all([
      api.listKnowledgeBooks(query || undefined),
      api.knowledgeCatalog(),
      api.listSkills(),
      api.rightsConfirmation().catch(() => ({ required_confirmation: RIGHTS_FALLBACK })),
    ]);
    setBooks(b);
    setCatalog(c);
    setSkills(s);
    setRightsText(rights.required_confirmation);
  }, [query]);

  useEffect(() => {
    void refresh().catch((e) => onError(String(e)));
  }, [refresh, onError]);

  async function loadPreview(id: string) {
    setBusy(true);
    try {
      setPreview(await api.getKnowledgeBook(id));
      setTab("collection");
    } catch (e) {
      onError(String(e));
    } finally {
      setBusy(false);
    }
  }

  async function registerSlug(slug: string) {
    setBusy(true);
    try {
      await api.registerCatalogBook(slug);
      await refresh();
    } catch (e) {
      onError(String(e));
    } finally {
      setBusy(false);
    }
  }

  async function runDiscoveryReport() {
    setBusy(true);
    try {
      setReport(await api.acquisitionReport());
      setTab("catalog");
    } catch (e) {
      onError(String(e));
    } finally {
      setBusy(false);
    }
  }

  async function handleUpload(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = e.currentTarget;
    const fd = new FormData(form);
    const file = (form.elements.namedItem("file") as HTMLInputElement)?.files?.[0];
    if (!file) {
      onError("Choose a file");
      return;
    }
    fd.set("file", file);
    fd.set("rights_confirmed", "true");
    fd.set("confirmation_text", rightsText);
    if (uploadSlug) fd.set("catalog_slug", uploadSlug);
    setBusy(true);
    try {
      await api.uploadKnowledgeBook(fd);
      form.reset();
      await refresh();
      setTab("collection");
    } catch (err) {
      onError(String(err));
    } finally {
      setBusy(false);
    }
  }

  async function processBook(id: string) {
    setBusy(true);
    try {
      await api.processKnowledgeBook(id);
      await loadPreview(id);
      await refresh();
    } catch (e) {
      onError(String(e));
    } finally {
      setBusy(false);
    }
  }

  async function generateDraft() {
    if (genBookIds.length === 0) {
      onError("Select at least one ready book");
      return;
    }
    setBusy(true);
    try {
      const draft = await api.generateSkill({
        book_ids: genBookIds,
        target_slug: genSlug,
      });
      setSkillDetail(draft);
      setEvalResult(null);
      await refresh();
      setTab("skills");
    } catch (e) {
      onError(String(e));
    } finally {
      setBusy(false);
    }
  }

  async function approve(id: string) {
    setBusy(true);
    try {
      setSkillDetail(await api.approveSkill(id));
      await refresh();
    } catch (e) {
      onError(String(e));
    } finally {
      setBusy(false);
    }
  }

  async function reject(id: string) {
    setBusy(true);
    try {
      await api.rejectSkill(id);
      setSkillDetail(null);
      await refresh();
    } catch (e) {
      onError(String(e));
    } finally {
      setBusy(false);
    }
  }

  async function runEval(id: string) {
    setBusy(true);
    try {
      setEvalResult(await api.evaluateSkill(id));
    } catch (e) {
      onError(String(e));
    } finally {
      setBusy(false);
    }
  }

  const readyBooks = books.filter((b) => b.status === "ready");

  return (
    <div className="modal-backdrop" role="dialog" aria-modal="true">
      <div className="modal knowledge-modal">
        <header className="modal-header">
          <div>
            <h2>Books-to-Skill / Knowledge Library</h2>
            <p className="muted">
              Upload legitimate books, extract abstractions, generate skills, orchestrate them in chat. No pirate downloads.
            </p>
          </div>
          <button type="button" className="btn btn-ghost" onClick={onClose}>
            Close
          </button>
        </header>

        <div className="kl-tabs">
          {(
            [
              ["collection", "Books"],
              ["catalog", "Catalog"],
              ["generate", "Generate"],
              ["skills", "Skills"],
            ] as const
          ).map(([id, label]) => (
            <button
              key={id}
              type="button"
              className={`kl-tab ${tab === id ? "active" : ""}`}
              onClick={() => setTab(id)}
            >
              {label}
            </button>
          ))}
        </div>

        <div className="kl-body">
          {tab === "collection" && (
            <div className="kl-split">
              <div>
                <div className="kl-toolbar">
                  <input
                    type="search"
                    placeholder="Search books…"
                    value={query}
                    onChange={(e) => setQuery(e.target.value)}
                  />
                  <button
                    type="button"
                    className="btn btn-sm"
                    disabled={busy}
                    onClick={() => void refresh()}
                  >
                    Refresh
                  </button>
                </div>
                <ul className="kl-list">
                  {books.map((b) => (
                    <li key={b.id}>
                      <button
                        type="button"
                        className={`kl-item ${preview?.book.id === b.id ? "active" : ""}`}
                        onClick={() => void loadPreview(b.id)}
                      >
                        <strong>{b.title}</strong>
                        <span className="meta">
                          {b.author} · {b.status}
                          {b.target_skill ? ` · ${b.target_skill}` : ""}
                        </span>
                      </button>
                    </li>
                  ))}
                  {books.length === 0 && (
                    <li className="muted">No books yet — register from Catalog or upload.</li>
                  )}
                </ul>

                <form className="kl-upload" onSubmit={(e) => void handleUpload(e)}>
                  <h3>Upload rights-confirmed file</h3>
                  <p className="muted small">
                    PDF, EPUB, TXT, DOCX. You must confirm legal rights.
                  </p>
                  <label>
                    Catalog slug (optional)
                    <select
                      value={uploadSlug}
                      onChange={(e) => setUploadSlug(e.target.value)}
                    >
                      <option value="">—</option>
                      {catalog.map((c) => (
                        <option key={c.slug} value={c.slug}>
                          {c.title}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label>
                    File
                    <input name="file" type="file" accept=".pdf,.epub,.txt,.docx" required />
                  </label>
                  <input type="hidden" name="usage_permission" value="owned" />
                  <label className="check-row">
                    <input type="checkbox" required /> I confirm rights using the required text
                  </label>
                  <p className="muted small rights-box">{rightsText}</p>
                  <button className="btn" type="submit" disabled={busy}>
                    Upload
                  </button>
                </form>
              </div>

              <div className="kl-detail">
                {preview ? (
                  <>
                    <h3>{preview.book.title}</h3>
                    <p className="muted">
                      {preview.book.author} · {preview.book.status}
                      {preview.book.concept_count
                        ? ` · ${preview.book.concept_count} concepts`
                        : ""}
                    </p>
                    <p>{preview.book.description}</p>
                    <div className="kl-actions">
                      {(preview.book.status === "uploaded" ||
                        preview.book.status === "failed") && (
                        <button
                          type="button"
                          className="btn btn-sm"
                          disabled={busy}
                          onClick={() => void processBook(preview.book.id)}
                        >
                          Process
                        </button>
                      )}
                      <button
                        type="button"
                        className="btn btn-sm btn-ghost"
                        disabled={busy}
                        onClick={() =>
                          void api.archiveKnowledgeBook(preview.book.id).then(refresh)
                        }
                      >
                        Archive
                      </button>
                    </div>
                    {preview.latest_job && (
                      <div className="kl-job">
                        <strong>Last job:</strong> {preview.latest_job.status} /{" "}
                        {preview.latest_job.stage}
                        {preview.latest_job.error && (
                          <p className="danger-text">{preview.latest_job.error}</p>
                        )}
                      </div>
                    )}
                    <h4>Text preview</h4>
                    <pre className="kl-pre">{preview.text_preview || "(none)"}</pre>
                    <h4>Concepts ({preview.concepts.length})</h4>
                    <ul className="kl-concepts">
                      {preview.concepts.slice(0, 40).map((c) => (
                        <li key={c.id}>
                          <strong>
                            [{c.kind}] {c.title}
                          </strong>
                          <span className="muted"> — {c.summary}</span>
                        </li>
                      ))}
                    </ul>
                  </>
                ) : (
                  <p className="muted">Select a book to inspect extraction.</p>
                )}
              </div>
            </div>
          )}

          {tab === "catalog" && (
            <div>
              <div className="kl-toolbar">
                <button
                  type="button"
                  className="btn btn-sm"
                  disabled={busy}
                  onClick={() => void runDiscoveryReport()}
                >
                  Run acquisition report
                </button>
              </div>
              <ul className="kl-list">
                {catalog.map((c) => (
                  <li key={c.slug} className="kl-catalog-row">
                    <div>
                      <strong>{c.title}</strong>
                      <span className="meta">
                        {c.author} · → {c.target_skill}
                      </span>
                      <span className="meta">
                        {c.full_text_authorized
                          ? "Authorized download available"
                          : "Purchase / library / manual upload"}
                      </span>
                    </div>
                    <button
                      type="button"
                      className="btn btn-sm"
                      disabled={busy}
                      onClick={() => void registerSlug(c.slug)}
                    >
                      Register
                    </button>
                  </li>
                ))}
              </ul>
              {report && (
                <pre className="kl-pre report">{report.markdown}</pre>
              )}
            </div>
          )}

          {tab === "generate" && (
            <div className="kl-generate">
              <p className="muted">
                Select processed books and a target skill. Output is always a draft until
                approved.
              </p>
              <label>
                Target skill slug
                <select value={genSlug} onChange={(e) => setGenSlug(e.target.value)}>
                  {skills.map((s) => (
                    <option key={s.id} value={s.slug}>
                      {s.slug} ({s.status})
                    </option>
                  ))}
                </select>
              </label>
              <fieldset>
                <legend>Ready books</legend>
                {readyBooks.length === 0 && (
                  <p className="muted">No ready books — process an upload first.</p>
                )}
                {readyBooks.map((b) => (
                  <label key={b.id} className="check-row">
                    <input
                      type="checkbox"
                      checked={genBookIds.includes(b.id)}
                      onChange={(e) => {
                        setGenBookIds((prev) =>
                          e.target.checked
                            ? [...prev, b.id]
                            : prev.filter((id) => id !== b.id)
                        );
                      }}
                    />
                    {b.title}
                  </label>
                ))}
              </fieldset>
              <button
                type="button"
                className="btn"
                disabled={busy}
                onClick={() => void generateDraft()}
              >
                Generate draft skill
              </button>
            </div>
          )}

          {tab === "skills" && (
            <div className="kl-split">
              <ul className="kl-list">
                {skills.map((s) => (
                  <li key={s.id}>
                    <button
                      type="button"
                      className={`kl-item ${skillDetail?.id === s.id ? "active" : ""}`}
                      onClick={() =>
                        void api.getSkill(s.id).then(setSkillDetail).catch((e) => onError(String(e)))
                      }
                    >
                      <strong>{s.name}</strong>
                      <span className="meta">
                        {s.slug} · {s.status} · v{s.version}
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
              <div className="kl-detail">
                {skillDetail ? (
                  <>
                    <h3>
                      {skillDetail.name}{" "}
                      <span className="muted">
                        v{skillDetail.version} · {skillDetail.status}
                      </span>
                    </h3>
                    <p>{skillDetail.description}</p>
                    <div className="kl-actions">
                      {skillDetail.status === "draft" && (
                        <>
                          <button
                            type="button"
                            className="btn btn-sm"
                            disabled={busy}
                            onClick={() => void approve(skillDetail.id)}
                          >
                            Approve
                          </button>
                          <button
                            type="button"
                            className="btn btn-sm btn-ghost"
                            disabled={busy}
                            onClick={() => void reject(skillDetail.id)}
                          >
                            Reject
                          </button>
                        </>
                      )}
                      <button
                        type="button"
                        className="btn btn-sm btn-ghost"
                        disabled={busy}
                        onClick={() => void runEval(skillDetail.id)}
                      >
                        Evaluate
                      </button>
                    </div>
                    <h4>Principles ({skillDetail.principles.length})</h4>
                    <ul className="kl-concepts">
                      {skillDetail.principles.slice(0, 30).map((p) => (
                        <li key={p.id}>
                          <strong>{p.title}</strong>
                          <span className="muted"> — {p.summary}</span>
                        </li>
                      ))}
                    </ul>
                    {evalResult && (
                      <pre className="kl-pre">
                        {JSON.stringify(evalResult, null, 2)}
                      </pre>
                    )}
                  </>
                ) : (
                  <p className="muted">Select a skill.</p>
                )}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
