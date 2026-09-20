import { useEffect } from "react";
import { useLocation } from "@tanstack/react-router";

/**
 * Adopt a `?job=` id from the URL into a page's own job state.
 *
 * This is what makes returning via a tracking code land the user on the page
 * they started from, in the state they left it: /track resolves the code to
 * a route plus a job id and navigates here, and the page then renders its
 * normal progress panel against that job. No separate results screen, no
 * second rendering path to keep in step with the live one.
 *
 * Only applied while the page has no job of its own, so it can never stomp
 * on a run the user just started in this tab.
 */
export function useResumedJob(
  jobId: string | null,
  setJobId: (id: string) => void,
) {
  const resumedJobId = useLocation({
    select: (location) => {
      const search = location.search as Record<string, unknown> | undefined;
      const job = search?.job;
      return typeof job === "string" && job ? job : null;
    },
  });

  useEffect(() => {
    if (resumedJobId && !jobId) {
      setJobId(resumedJobId);
    }
  }, [resumedJobId, jobId, setJobId]);

  return resumedJobId;
}
