import { FormEvent, useState } from "react";

type Props = {
  allocated: number;
  needsAuth: boolean;
  onStart: (brief: {
    name: string;
    problem: string;
    stack: string;
    constraints: string;
  }) => void;
  onRegister: () => void;
  onPickExample: (name: string, idea: string) => void;
};

const EXAMPLES = [
  {
    name: "Habit Tracker",
    idea: "Local-first habit tracker with gentle nudges — decide sync needs later.",
  },
  {
    name: "Internal Ops Tool",
    idea: "Replace a spreadsheet workflow with a small internal app for the ops team.",
  },
  {
    name: "API Product",
    idea: "Design a public API with auth, rate limits, and clear SLOs for developers.",
  },
];

export function Welcome({
  allocated,
  needsAuth,
  onStart,
  onRegister,
  onPickExample,
}: Props) {
  const [name, setName] = useState("");
  const [problem, setProblem] = useState("");
  const [stack, setStack] = useState("");
  const [constraints, setConstraints] = useState("");

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (!name.trim() || !problem.trim()) return;
    onStart({
      name: name.trim(),
      problem: problem.trim(),
      stack: stack.trim(),
      constraints: constraints.trim(),
    });
  }

  if (needsAuth) {
    return (
      <div className="welcome">
        <h1>Sign in to start</h1>
        <p className="welcome-lead">
          New accounts get {allocated} free AI generations on platform-funded Qwen.
          After that, bring your own API key.
        </p>
        <button className="btn" type="button" onClick={onRegister}>
          Create account
        </button>
      </div>
    );
  }

  return (
    <div className="welcome">
      <h1>Project brief</h1>
      <p className="welcome-lead">
        Define the problem, target stack, and constraints. VibePrompt will stress-test
        assumptions before you export an agent spec.
      </p>

      <form className="brief-form" onSubmit={handleSubmit}>
        <div className="brief-field">
          <label htmlFor="brief-name">Project name</label>
          <input
            id="brief-name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            required
            autoFocus
            placeholder="e.g. Habit Tracker"
          />
        </div>
        <div className="brief-field">
          <label htmlFor="brief-problem">1 · Problem</label>
          <textarea
            id="brief-problem"
            value={problem}
            onChange={(e) => setProblem(e.target.value)}
            required
            rows={3}
            placeholder="Who is stuck, and what outcome do they need?"
          />
        </div>
        <div className="brief-field">
          <label htmlFor="brief-stack">2 · Target stack</label>
          <textarea
            id="brief-stack"
            value={stack}
            onChange={(e) => setStack(e.target.value)}
            rows={2}
            placeholder="Languages, frameworks, hosting, data store…"
          />
        </div>
        <div className="brief-field">
          <label htmlFor="brief-constraints">3 · Constraints</label>
          <textarea
            id="brief-constraints"
            value={constraints}
            onChange={(e) => setConstraints(e.target.value)}
            rows={2}
            placeholder="Budget, timeline, team size, must-nots…"
          />
        </div>
        <button className="btn" type="submit">
          Start project
        </button>
      </form>

      <p className="section-label welcome-examples-label">Or start from an example</p>
      <div className="example-grid">
        {EXAMPLES.map((ex) => (
          <button
            key={ex.name}
            type="button"
            className="example-card"
            onClick={() => onPickExample(ex.name, ex.idea)}
          >
            <strong>{ex.name}</strong>
            <span>{ex.idea}</span>
          </button>
        ))}
      </div>
    </div>
  );
}
