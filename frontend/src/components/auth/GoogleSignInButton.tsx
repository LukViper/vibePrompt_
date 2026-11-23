import { useEffect, useRef, useState } from "react";

type Props = {
  clientId: string;
  disabled?: boolean;
  onCredential: (idToken: string) => void | Promise<void>;
  onError?: (message: string) => void;
};

declare global {
  interface Window {
    google?: {
      accounts: {
        id: {
          initialize: (config: Record<string, unknown>) => void;
          renderButton: (
            parent: HTMLElement,
            config: Record<string, unknown>
          ) => void;
          cancel: () => void;
        };
      };
    };
  }
}

const GIS_SRC = "https://accounts.google.com/gsi/client";

function loadGisScript(): Promise<void> {
  const existing = document.querySelector<HTMLScriptElement>(
    `script[src="${GIS_SRC}"]`
  );
  if (existing) {
    if (window.google?.accounts?.id) return Promise.resolve();
    return new Promise((resolve, reject) => {
      existing.addEventListener("load", () => resolve());
      existing.addEventListener("error", () =>
        reject(new Error("Failed to load Google Sign-In"))
      );
    });
  }
  return new Promise((resolve, reject) => {
    const script = document.createElement("script");
    script.src = GIS_SRC;
    script.async = true;
    script.defer = true;
    script.onload = () => resolve();
    script.onerror = () => reject(new Error("Failed to load Google Sign-In"));
    document.head.appendChild(script);
  });
}

export function GoogleSignInButton({
  clientId,
  disabled,
  onCredential,
  onError,
}: Props) {
  const hostRef = useRef<HTMLDivElement>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    let cancelled = false;
    const boot = async () => {
      try {
        await loadGisScript();
        if (cancelled || !hostRef.current || !window.google?.accounts?.id) return;
        hostRef.current.innerHTML = "";
        window.google.accounts.id.initialize({
          client_id: clientId,
          callback: (response: { credential?: string }) => {
            const token = response.credential;
            if (!token) {
              onError?.("Google Sign-In returned no credential");
              return;
            }
            void onCredential(token);
          },
          auto_select: false,
          cancel_on_tap_outside: true,
        });
        window.google.accounts.id.renderButton(hostRef.current, {
          type: "standard",
          theme: "outline",
          size: "large",
          text: "continue_with",
          shape: "rectangular",
          width: hostRef.current.offsetWidth || 320,
        });
        if (!cancelled) setReady(true);
      } catch (err) {
        if (!cancelled) {
          onError?.(err instanceof Error ? err.message : "Google Sign-In failed");
        }
      }
    };
    void boot();
    return () => {
      cancelled = true;
      try {
        window.google?.accounts?.id?.cancel();
      } catch {
        /* ignore */
      }
    };
  }, [clientId, onCredential, onError]);

  return (
    <div
      className={`google-signin-host ${disabled ? "disabled" : ""} ${ready ? "ready" : ""}`}
      aria-busy={!ready}
    >
      <div ref={hostRef} className="google-signin-slot" />
      {!ready && (
        <button type="button" className="btn btn-block oauth-btn" disabled>
          Continue with Google…
        </button>
      )}
    </div>
  );
}
