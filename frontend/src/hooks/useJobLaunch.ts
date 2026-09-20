import { useCallback, useState } from "react";
import { readApiError } from "@/api/jobs";
import {
  estimateJob,
  readGateError,
  type EstimateJobRequest,
  type JobEstimate,
} from "@/api/notifications";

/**
 * Wraps "user clicked Run" for every pipeline page.
 *
 * Sizing the run first is what makes the email gate feel like an
 * explanation rather than an obstruction: the dialog can say *how long* and
 * *why* before asking for an address. But the pre-flight estimate is only an
 * affordance — the start endpoint enforces the same rule and answers 428, so
 * a failed or skipped estimate still lands the user in the same dialog
 * rather than starting something it shouldn't.
 */
export function useJobLaunch<T>({
  buildEstimate,
  start,
  onStarted,
}: {
  /** Describe the run for the estimator (file ids plus steps or format_id). */
  buildEstimate: () => EstimateJobRequest;
  /** Start the job. Called once the gate is satisfied. */
  start: () => Promise<T>;
  onStarted?: (result: T) => void;
}) {
  const [gateOpen, setGateOpen] = useState(false);
  const [estimate, setEstimate] = useState<JobEstimate | null>(null);
  const [isLaunching, setIsLaunching] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const runStart = useCallback(async () => {
    setIsLaunching(true);
    setError(null);
    try {
      const result = await start();
      onStarted?.(result);
    } catch (e) {
      // The backend rejected it as gated — either the pre-flight estimate
      // was skipped, or it disagreed with this one. Open the dialog with the
      // authoritative numbers.
      const gate = readGateError(e);
      if (gate) {
        setEstimate(gate);
        setGateOpen(true);
      } else {
        setError(readApiError(e));
      }
    } finally {
      setIsLaunching(false);
    }
  }, [start, onStarted]);

  const launch = useCallback(async () => {
    setIsLaunching(true);
    setError(null);

    let preflight: JobEstimate | null = null;
    try {
      preflight = await estimateJob(buildEstimate());
      setEstimate(preflight);
    } catch {
      // Estimating is best-effort: fall through and let the start endpoint
      // have the final word rather than blocking a legitimate run.
    }

    if (preflight?.requires_email && !preflight.verified_email) {
      setGateOpen(true);
      setIsLaunching(false);
      return;
    }

    await runStart();
  }, [buildEstimate, runStart]);

  return {
    /** Call from the Run button. */
    launch,
    /** Start the job now, skipping the pre-flight — used by the gate dialog. */
    startNow: runStart,
    gateOpen,
    setGateOpen,
    estimate,
    isLaunching,
    error,
    clearError: useCallback(() => setError(null), []),
  };
}
