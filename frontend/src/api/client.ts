import { getSessionId, getSessionToken } from "./session";

// Configurable at build/run time via VITE_API_URL. Falls back to local dev.
export const API = import.meta.env.VITE_API_URL ?? "http://127.0.0.1:8000";

export async function sessionApi<T>(
  path: string,
  options?: RequestInit
): Promise<T> {
  const sessionId = await getSessionId();
  const token = getSessionToken();

  const response = await fetch(
    `${API}/api/sessions/${sessionId}${path}`,
    {
      headers: {
        "Content-Type": "application/json",
        ...(token ? { "X-Session-Token": token } : {}),
      },
      ...options,
    }
  );

  if (!response.ok) {
    throw new Error(await response.text());
  }

  return response.json();
}

export async function publicApi<T>(
  path: string,
  options?: RequestInit
): Promise<T> {
  // Not every route this hits is session-scoped, but the backend only
  // checks the header on the ones that are — harmless to always send it.
  const token = getSessionToken();

  const response = await fetch(
    `${API}${path}`,
    {
      headers: {
        "Content-Type": "application/json",
        ...(token ? { "X-Session-Token": token } : {}),
      },
      ...options,
    }
  );

  if (!response.ok) {
    throw new Error(await response.text());
  }

  return response.json();
}