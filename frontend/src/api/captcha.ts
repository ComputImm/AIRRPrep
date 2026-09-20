import { API } from "./client";

/**
 * Client for the self-hosted anti-bot challenge
 * (presto-backend/app/core/captcha.py).
 */

export interface Captcha {
  captcha_id: string;
  /** `data:image/svg+xml;base64,...` — goes straight into an <img src>. */
  image: string;
  expires_in: number;
}

/**
 * Fetch a fresh challenge.
 *
 * Not routed through `publicApi`: this is the one thing a caller needs
 * *before* they can prove anything, so it must work with no session at all
 * (the /track page is reached from an email, in a browser that has never
 * seen this app).
 */
export async function getCaptcha(): Promise<Captcha> {
  const response = await fetch(`${API}/api/captcha/new`);
  if (!response.ok) throw new Error(await response.text());
  return response.json();
}

/** True if a failed request was the CAPTCHA rejecting us. */
export function isCaptchaError(error: unknown): boolean {
  if (!(error instanceof Error)) return false;
  try {
    return JSON.parse(error.message)?.detail?.error === "captcha_failed";
  } catch {
    return false;
  }
}
