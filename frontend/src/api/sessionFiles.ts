/**
 * The uploads this session still holds.
 *
 * Sequencing files are large and the connection is often not; re-uploading the
 * same 200 MB FASTQ to try a second pipeline is the single most tedious part
 * of using this app. The backend keeps uploads for a fixed retention window,
 * so they can simply be picked again -- provided the UI can say what each one
 * is and how long it has left, which is what these types carry.
 */

import { publicApi } from "./client";
import { getSessionId } from "./session";

export interface SessionFile {
  file_id: string;
  filename: string;
  /** "fastq" | "fasta" | ... as detected from the file's contents. */
  file_type: string;
  /** Annotations found in the headers (barcode, umi, primer, quality, ...). */
  capabilities: string[];
  size: number;
  /** Unix seconds. */
  created_at: number;
  expires_at: number;
}

export interface SessionFilesResponse {
  files: string[];
  items: SessionFile[];
  retention_days: number;
  storage: { used_bytes: number; limit_bytes: number };
}

export async function listSessionFiles(): Promise<SessionFilesResponse> {
  const sessionId = await getSessionId();
  return publicApi<SessionFilesResponse>(`/api/sessions/${sessionId}/files`);
}

export async function deleteSessionFile(fileId: string) {
  const sessionId = await getSessionId();
  return publicApi<{ deleted: boolean }>(
    `/api/sessions/${sessionId}/files/${fileId}`,
    { method: "DELETE" },
  );
}

export function formatBytes(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes <= 0) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  const i = Math.min(units.length - 1, Math.floor(Math.log(bytes) / Math.log(1024)));
  const value = bytes / 1024 ** i;
  return `${value >= 10 || i === 0 ? Math.round(value) : value.toFixed(1)} ${units[i]}`;
}

/**
 * "3 days left" / "today" -- how long before this upload is deleted.
 *
 * Rounded up so a file with a few hours left never reads as "0 days"; the
 * point is to warn, not to be precise to the minute.
 */
export function formatExpiry(expiresAt: number): string {
  if (!expiresAt) return "";
  const msLeft = expiresAt * 1000 - Date.now();
  if (msLeft <= 0) return "expired";
  const days = Math.ceil(msLeft / 86_400_000);
  if (days <= 1) return "less than a day left";
  return `${days} days left`;
}
