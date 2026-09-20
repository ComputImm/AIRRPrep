import { useQuery } from "@tanstack/react-query";
import { getSessionHistory, type SessionHistoryEntry } from "@/api/jobs";

function isTerminal(status: string): boolean {
  return (
    status === "DONE" ||
    status.startsWith("FAILED") ||
    status.startsWith("Fail ")
  );
}

/**
 * Fetch every job run in the current session (newest first). Polls while any
 * job is still running, then settles. Invalidate ["session-history"] after
 * starting a new job to surface it immediately.
 */
export function useSessionHistory(enabled = true) {
  return useQuery({
    queryKey: ["session-history"],
    queryFn: getSessionHistory,
    enabled,
    refetchInterval: (q) => {
      const data = q.state.data as SessionHistoryEntry[] | undefined;
      if (!data || data.length === 0) return false;
      const anyRunning = data.some(
        (e) => !isTerminal((e.job.status ?? "").toString()),
      );
      return anyRunning ? 2000 : false;
    },
  });
}
