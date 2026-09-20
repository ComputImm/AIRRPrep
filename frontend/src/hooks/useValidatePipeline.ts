import { useMutation } from "@tanstack/react-query";
import { validatePipeline } from "@/api/jobs";

export function useValidatePipeline() {
  return useMutation({ mutationFn: validatePipeline });
}
