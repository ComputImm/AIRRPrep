import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  getJobProgress,
  type JobStatusResponse,
  type StepStat,
} from "@/api/jobs";

export type JobPhase = "queued" | "processing" | "done" | "failed" | "cancelled";

export interface JobProgress {
  /** High level state of the whole job. */
  phase: JobPhase;
  /** 0–100 overall completion. */
  percent: number;
  /** Number of steps that have fully finished. */
  completedSteps: number;
  /** 1-based index of the step currently running (0 if none yet). */
  currentStep: number;
  /** Total number of steps in the pipeline. */
  totalSteps: number;
  /** Backend step name of the active step, e.g. "BuildConsensus.default". */
  currentStepName: string;
  /** Raw status string from the backend. */
  statusText: string;
  /** Error detail when the job failed. */
  error?: string;
  /** Session that owns the job (needed to build download URLs). */
  sessionId?: string;
  /** Per-step pass/fail entries reported by the backend so far. */
  stepStats: StepStat[];
  /** Whether the first status response is still loading. */
  isLoading: boolean;
  /**
   * The raw job document. Needed by pages whose step list lives in component
   * state rather than a static table — on a resumed run (see
   * useResumedJob.ts) that state is empty, and the pipeline can only be
   * recovered from what the backend stored.
   */
  raw?: JobStatusResponse;
}

const STEP_RE = /STEP\s+(\d+)\s+OF\s+(\d+)/i;
const NAME_RE = /^(?:PROCESSING|DONE|Fail)\s+(\S+)/;

function isTerminal(status: string): boolean {
  return (
    status === "DONE" ||
    status.startsWith("FAILED") ||
    status.startsWith("Fail ") ||
    // A run the user stopped is over; polling it forever would keep the
    // spinner turning on a job no worker is touching any more.
    status.startsWith("CANCELLED")
  );
}

export function parseJobProgress(
  data: JobStatusResponse | undefined,
  totalStepsFallback: number,
  isLoading: boolean,
): JobProgress {
  const status = (data?.status ?? "").toString();
  const completedSteps = data?.step_stats?.length ?? 0;

  const stepMatch = status.match(STEP_RE);
  const totalSteps = stepMatch ? Number(stepMatch[2]) : totalStepsFallback;
  const parsedCurrent = stepMatch ? Number(stepMatch[1]) : 0;

  const nameMatch = status.match(NAME_RE);
  const currentStepName = nameMatch ? nameMatch[1] : "";

  let phase: JobPhase;
  if (status === "DONE") {
    phase = "done";
  } else if (status.startsWith("CANCELLED")) {
    phase = "cancelled";
  } else if (status.startsWith("FAILED") || status.startsWith("Fail ")) {
    phase = "failed";
  } else if (status.startsWith("PROCESSING") || status.startsWith("DONE ")) {
    phase = "processing";
  } else {
    phase = "queued";
  }

  // The job finished the last step but the overall "DONE" flag may not have
  // landed yet — treat that as done so the bar reaches 100%.
  if (phase === "processing" && totalSteps > 0 && completedSteps >= totalSteps) {
    phase = "done";
  }

  let currentStep = parsedCurrent;
  if (phase === "processing" && !currentStep) {
    currentStep = completedSteps + 1;
  }

  let value: number;
  if (phase === "cancelled") {
    // Freeze the bar where the run actually stopped rather than snapping it
    // to 0 or 100 -- the finished steps are real and still downloadable.
    value = completedSteps;
  } else if (phase === "done") {
    value = totalSteps;
  } else if (status.startsWith("PROCESSING ")) {
    // A step is mid-flight: give it half credit so the bar advances when a
    // step starts, not only when it finishes.
    value = completedSteps + 0.5;
  } else {
    value = completedSteps;
  }

  const percent =
    totalSteps > 0 ? Math.min(100, Math.round((value / totalSteps) * 100)) : 0;

  return {
    phase,
    percent,
    completedSteps,
    currentStep,
    totalSteps,
    currentStepName,
    statusText: status,
    error: data?.error,
    sessionId: data?.session_id,
    stepStats: data?.step_stats ?? [],
    isLoading,
    raw: data,
  };
}

/**
 * Poll a job's status from the backend and expose it as structured progress.
 * Polling stops automatically once the job reaches a terminal state.
 */
export function useJobProgress(
  jobId: string | null,
  totalStepsFallback: number,
): JobProgress {
  const query = useQuery({
    queryKey: ["job-progress", jobId],
    queryFn: () => getJobProgress(jobId as string),
    enabled: !!jobId,
    refetchInterval: (q) => {
      const status = (q.state.data as JobStatusResponse | undefined)?.status ?? "";
      return isTerminal(status.toString()) ? false : 1000;
    },
  });

  return useMemo(
    () =>
      parseJobProgress(
        query.data,
        totalStepsFallback,
        !!jobId && query.isLoading,
      ),
    [query.data, totalStepsFallback, jobId, query.isLoading],
  );
}
