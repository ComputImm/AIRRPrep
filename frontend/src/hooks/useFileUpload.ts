import { useMutation } from "@tanstack/react-query";
import { uploadFile } from "@/api/files";

export function useFileUpload() {
  return useMutation({
    mutationFn: uploadFile,
  });
}