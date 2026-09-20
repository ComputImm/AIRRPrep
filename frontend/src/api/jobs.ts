import { API, publicApi, sessionApi } from "./client";
import { getSessionId, getSessionToken } from "./session";

export interface PipelineStep {
  id: string;
  name: string;
  lanes: string;
  params: Record<string, any>;
}

export interface StartJobRequest {
  session_id: string;
  file_ids: string[];
  convert_to_fasta: boolean;
  steps: PipelineStep[];
  /**
   * Page this run was launched from, and a human name for it. Stored with the
   * tracking code so returning via /track lands the user back here rather
   * than on a generic results screen.
   */
  route?: string;
  label?: string;
}

export interface StartJobResponse {
  job_id: string;
  /** Set only when the session has a verified email; see /api/jobs/estimate. */
  tracking_code?: string | null;
}

export function startJob(data: StartJobRequest) {
  return publicApi<StartJobResponse>("/jobs/start", {
    method: "POST",
    body: JSON.stringify(data),
  });
}

export function getJobStatus(jobId: string) {
  return sessionApi(`/jobs/${jobId}`);
}

/** Per-step pass/fail entry the backend appends to `step_stats`. */
export interface StepStat {
  index: number;
  name: string;
  lanes?: string[];
  before?: number;
  failed?: number;
  remaining?: number;
  by_lane?: Record<string, { before: number; failed: number; remaining: number }>;
  output_paths?: Record<string, string>;
  /**
   * Present only for a step that fanned its lane out into several files
   * (SplitSeq.count, SplitSeq.group without a threshold, ...). Each entry is
   * one downloadable part; `output_paths` still names the single file the
   * pipeline would have carried forward.
   */
  parts?: StepPart[];
}

/** Shape of the job document the backend stores in Redis and returns. */
export interface JobStatusResponse {
  status?: string;
  session_id?: string;
  file_paths?: string[];
  output_file?: string;
  error?: string;
  step_stats?: StepStat[];
  last_step_stats?: Record<string, unknown>;
  /**
   * Set when the user asked to stop. Its own field rather than part of
   * `status`, which the worker owns -- writing both from two processes raced
   * and could leave a finished run reading as "stopping" forever.
   */
  cancel_requested?: boolean;
  /** Set once a run actually stopped without completing. */
  cancelled?: boolean;
  /** "<dataset>_<tracking code>" -- the stem every file of this run shares. */
  run_prefix?: string;
  /**
   * The run's last step fans out, so there is no single final output -- the
   * parts are the result. Recorded by the executor rather than guessed from
   * the last step's `parts`, because a step can legitimately write two files
   * (a thresholded SplitSeq.group) and still be followed by more steps.
   */
  ends_in_split?: boolean;
  pipeline_summary?: Record<string, unknown>;
  [key: string]: unknown;
}

/** Request body for the backend pipeline validator. */
export interface ValidatePipelineRequest {
  chains: 1 | 2;
  file_ids: string[];
  steps: PipelineStep[];
  input_format?: "fasta" | "fastq";
}

/** Summary returned by POST /api/pipeline/custom/validate. */
export interface ValidateSummary {
  missing_required_uploads?: Array<{
    step_index: number;
    step_name: string;
    param: string;
    required?: boolean;
  }>;
  required_uploads?: unknown[];
  sequence_inputs?: unknown;
  [key: string]: unknown;
}

/**
 * Validate a fixed pipeline against the uploaded files using the backend
 * planner (POST /api/pipeline/custom/validate). Throws on invalid pipelines.
 */
export function validatePipeline(data: ValidatePipelineRequest) {
  return publicApi<ValidateSummary>("/api/pipeline/custom/validate", {
    method: "POST",
    body: JSON.stringify(data),
  });
}

/** A past job in the current session, with its full status document. */
export interface SessionHistoryEntry {
  id: string;
  job: JobStatusResponse & {
    created_at?: string;
    steps?: Array<{ name: string; lanes?: string }>;
  };
}

/** List every job run in the current session, newest first. */
export async function getSessionHistory(): Promise<SessionHistoryEntry[]> {
  const sessionId = await getSessionId();
  const { jobs } = await publicApi<{ session_id: string; jobs: string[] }>(
    `/api/sessions/${sessionId}/jobs`,
  );
  const ids = jobs ?? [];
  const docs = await Promise.all(
    ids.map((id) =>
      publicApi<SessionHistoryEntry["job"]>(
        `/sessions/${sessionId}/jobs/${id}`,
      ).catch(() => null),
    ),
  );
  const entries = ids
    .map((id, i) => ({ id, job: docs[i] }))
    .filter((e): e is SessionHistoryEntry => e.job != null);

  // Newest first by created_at when present, otherwise keep append order reversed.
  entries.sort((a, b) => {
    const ta = Date.parse(a.job.created_at ?? "") || 0;
    const tb = Date.parse(b.job.created_at ?? "") || 0;
    return tb - ta;
  });
  return entries;
}

/**
 * Build a URL that downloads a single step's pass / fail output file.
 * Backed by the additive endpoint in presto-backend/app/api/jobs.py.
 *
 * These URLs are used directly as `<a href>` targets, which can't set
 * custom headers — so the session token travels as a query param instead.
 */
export function stepFileUrl(
  sessionId: string,
  jobId: string,
  stepIndex: number,
  kind: "pass" | "fail",
  lane?: string,
): string {
  const params = new URLSearchParams({ kind });
  if (lane) params.set("lane", lane);
  const token = getSessionToken();
  if (token) params.set("token", token);
  return `${API}/sessions/${sessionId}/jobs/${jobId}/steps/${stepIndex}/download?${params.toString()}`;
}

/** URL that downloads a job's final output file. */
export function jobOutputUrl(sessionId: string, jobId: string): string {
  const token = getSessionToken();
  const suffix = token ? `?token=${encodeURIComponent(token)}` : "";
  return `${API}/sessions/${sessionId}/jobs/${jobId}/download${suffix}`;
}

/** Pull a human-readable message out of a thrown API error (FastAPI detail). */
export function readApiError(error: unknown): string {
  if (error instanceof Error) {
    try {
      const parsed = JSON.parse(error.message);
      const detail = parsed?.detail;
      if (typeof detail === "string") return detail;
      if (detail && typeof detail === "object") {
        // Structured errors (the launch gate, the anti-bot check) carry both
        // a machine-readable `error` code and a sentence meant for the user.
        // Show the sentence — `error` is for branching on, and putting
        // "captcha_failed" in front of someone helps nobody.
        if (typeof detail.message === "string") return detail.message;
        if (typeof detail.error === "string") return detail.error;
        return JSON.stringify(detail);
      }
    } catch {
      /* not JSON */
    }
    return error.message;
  }
  return "Request failed";
}

/**
 * Poll the live status of a running job.
 *
 * The backend exposes this at the application root (no `/api` prefix):
 *   GET /sessions/{session_id}/jobs/{job_id}   (see presto-backend/main.py)
 */
export async function getJobProgress(
  jobId: string,
): Promise<JobStatusResponse> {
  const sessionId = await getSessionId();
  return publicApi<JobStatusResponse>(`/sessions/${sessionId}/jobs/${jobId}`);
}
/**
 * One file written by a step that split its lane into several
 * (SplitSeq.count, SplitSeq.group, ...). `label` is what pRESTO called the
 * part -- "part3", "atleast-2", the annotation value it grouped on.
 */
export interface StepPart {
  label: string;
  lane?: string | null;
  name: string;
  sequences?: number;
}

/** URL that downloads one part of a splitting step's output. */
export function stepPartUrl(
  sessionId: string,
  jobId: string,
  stepIndex: number,
  part: string,
): string {
  const params = new URLSearchParams({ part });
  const token = getSessionToken();
  if (token) params.set("token", token);
  return `${API}/sessions/${sessionId}/jobs/${jobId}/steps/${stepIndex}/download?${params.toString()}`;
}

/**
 * URL for a zip of everything the run produced.
 *
 * `scope: "all"` also includes the uploaded inputs, which is rarely what
 * someone wants back -- they already have those.
 */
export function jobArchiveUrl(
  sessionId: string,
  jobId: string,
  scope: "outputs" | "all" = "outputs",
): string {
  const params = new URLSearchParams({ scope });
  const token = getSessionToken();
  if (token) params.set("token", token);
  return `${API}/sessions/${sessionId}/jobs/${jobId}/download-all?${params.toString()}`;
}

/** Ask the backend to stop a running job at its next step boundary. */
export async function cancelJob(jobId: string) {
  const sessionId = await getSessionId();
  return publicApi<{ job_id: string; status: string; message: string }>(
    `/sessions/${sessionId}/jobs/${jobId}/cancel`,
    { method: "POST" },
  );
}
