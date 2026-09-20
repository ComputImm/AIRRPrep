import { useMutation } from "@tanstack/react-query";
import { startJob } from "@/api/jobs";

export function useStartJob() {
  return useMutation({
    mutationFn: startJob,
  });
}