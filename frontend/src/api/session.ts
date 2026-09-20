const API_URL = `${import.meta.env.VITE_API_URL ?? "http://127.0.0.1:8000"}/api`;

const SESSION_KEY = "session_id";
const SESSION_TOKEN_KEY = "session_token";

let sessionPromise: Promise<string> | null = null;

export async function getSessionId(): Promise<string> {
  const saved = localStorage.getItem(SESSION_KEY);
  const savedToken = localStorage.getItem(SESSION_TOKEN_KEY);

  if (saved && savedToken) {
    return saved;
  }

  if (!sessionPromise) {
    sessionPromise = fetch(`${API_URL}/sessions`, {
      method: "POST",
    })
      .then(async (res) => {
        if (!res.ok) {
          throw new Error("Failed to create session");
        }

        const data = await res.json();

        localStorage.setItem(SESSION_KEY, data.session_id);
        // Returned only once, at creation time — must be persisted now.
        localStorage.setItem(SESSION_TOKEN_KEY, data.session_token);

        return data.session_id;
      })
      .finally(() => {
        sessionPromise = null;
      });
  }

  return sessionPromise;
}

/** Synchronous — safe to call once a session exists (after getSessionId()). */
export function getSessionToken(): string | null {
  return localStorage.getItem(SESSION_TOKEN_KEY);
}

/**
 * Adopt a session handed back by tracking-code recovery
 * (POST /api/tracking/resume).
 *
 * The token is a freshly minted one for that session rather than the
 * original, which the backend only stores hashed — see
 * app/core/auth.py::issue_additional_session_token. Storing it here is what
 * makes every existing status poll and download link work on the recovered
 * run without any of them knowing recovery happened.
 */
export function adoptSession(sessionId: string, sessionToken: string) {
  localStorage.setItem(SESSION_KEY, sessionId);
  localStorage.setItem(SESSION_TOKEN_KEY, sessionToken);
}