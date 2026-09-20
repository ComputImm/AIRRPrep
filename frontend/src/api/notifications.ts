import { API, publicApi } from "./client";
import { getSessionId } from "./session";

/**
 * Client for the "this will take a while — leave us your email" flow.
 * Backed by presto-backend/app/api/notifications.py.
 */

/** What the backend thinks a run will cost, and whether it is gated. */
export interface JobEstimate {
  total_input_bytes: number;
  total_input_mb: number;
  estimated_seconds: number;
  /** True when a verified address is required before this may start. */
  requires_email: boolean;
  /** Slow components in this pipeline, e.g. ["BuildConsensus"]. */
  heavy_steps: string[];
  /** Short phrases explaining why the gate applied. */
  reasons: string[];
  /** Address this session has already verified, if any. */
  verified_email: string | null;
}

export interface EstimateJobRequest {
  file_ids: string[];
  /** Bulk runs: the assembled pipeline. Omit for single-cell. */
  steps?: unknown[];
  /** Single-cell runs: set this instead of `steps`. */
  format_id?: string;
}

export async function estimateJob(
  data: EstimateJobRequest,
): Promise<JobEstimate> {
  const session_id = await getSessionId();
  return publicApi<JobEstimate>("/api/jobs/estimate", {
    method: "POST",
    body: JSON.stringify({ session_id, ...data }),
  });
}

/** Anti-bot answer that must accompany the two guarded requests. */
export interface CaptchaAnswer {
  captcha_id: string | null;
  captcha_answer: string;
}

export async function requestEmailCode(email: string, captcha: CaptchaAnswer) {
  const session_id = await getSessionId();
  return publicApi<{ sent: boolean; email: string }>("/api/email/request-code", {
    method: "POST",
    body: JSON.stringify({ session_id, email, ...captcha }),
  });
}

export async function verifyEmailCode(email: string, code: string) {
  const session_id = await getSessionId();
  return publicApi<{ verified: boolean; email: string }>(
    "/api/email/verify-code",
    {
      method: "POST",
      body: JSON.stringify({ session_id, email, code }),
    },
  );
}

export async function getEmailStatus() {
  const session_id = await getSessionId();
  return publicApi<{ verified_email: string | null }>(
    `/api/email/status?session_id=${encodeURIComponent(session_id)}`,
  );
}

/** What a tracking code resolves to once the matching email is supplied. */
export interface ResumeResult {
  session_id: string;
  job_id: string;
  /** Fresh token for the recovered session — the caller must store it. */
  session_token: string;
  /** Frontend path the run was started from, e.g. "/pipeline/umi-miseq-2x250". */
  route: string;
  label: string;
  status: string | null;
}

/**
 * Trade a tracking code plus the address it was issued to for access to the
 * run.
 *
 * Deliberately not routed through `publicApi`: that helper attaches the
 * current session's token, and recovery has to work in a browser that has
 * never held one.
 */
export async function resumeFromTrackingCode(
  code: string,
  email: string,
  captcha: CaptchaAnswer,
): Promise<ResumeResult> {
  const response = await fetch(`${API}/api/tracking/resume`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      code: code.trim(),
      email: email.trim(),
      ...captcha,
    }),
  });

  if (!response.ok) {
    throw new Error(await response.text());
  }

  return response.json();
}

/**
 * Pull the estimate out of the 428 the start endpoints return when a run is
 * gated, so the caller can open the dialog with the real numbers rather than
 * a generic "email required".
 */
export function readGateError(error: unknown): JobEstimate | null {
  if (!(error instanceof Error)) return null;
  try {
    const detail = JSON.parse(error.message)?.detail;
    if (detail?.error === "email_verification_required" && detail.estimate) {
      return { ...detail.estimate, verified_email: null } as JobEstimate;
    }
  } catch {
    /* not the gate error */
  }
  return null;
}

/** "about 35 minutes" — mirrors the backend's own coarse phrasing. */
export function formatDuration(seconds: number): string {
  if (seconds < 90) return "less than a minute";
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `about ${minutes} minutes`;
  const hours = seconds / 3600;
  if (hours < 2) return "about an hour";
  if (hours < 24) return `about ${Math.round(hours)} hours`;
  return `about ${Math.round(hours / 24)} days`;
}
