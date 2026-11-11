type Props = {
  allocated: number;
  needsAuth: boolean;
  onStart: () => void;
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
  if (needsAuth) {
    return (
      <div className="welcome">
        <p className="welcome-kicker">VibePrompt</p>
        <h1>Sign in to start building</h1>
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
      <p className="welcome-kicker">VibePrompt</p>
      <h1>Talk through your idea</h1>
      <p className="welcome-lead">
        Shape the product, make solid decisions, and export a clear specification for
        coding agents — critical checks happen quietly in the background.
      </p>
      <button className="btn" type="button" onClick={onStart}>
        Start a conversation
      </button>

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
