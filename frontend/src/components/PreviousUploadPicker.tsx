import { useEffect, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertCircle, Clock, HardDrive, History, Loader2, Trash2, X } from "lucide-react";
import {
  deleteSessionFile,
  formatBytes,
  formatExpiry,
  listSessionFiles,
  type SessionFile,
} from "@/api/sessionFiles";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

/**
 * Pick a file this session already uploaded instead of sending it again.
 *
 * Sequencing files are large and uploads are slow, so trying a second pipeline
 * on the same reads should not mean waiting through the same transfer. The
 * backend keeps uploads for a fixed retention window; this lists what is left,
 * with each file's detected format, the annotations found in its headers, and
 * how long before it is deleted -- enough to choose the right one without
 * opening it, and enough warning to re-upload before it disappears.
 */
export function usePreviousUploads(enabled = true) {
  return useQuery({
    queryKey: ["session-files"],
    queryFn: listSessionFiles,
    enabled,
    staleTime: 15_000,
  });
}

export function PreviousUploadPicker({
  open,
  onClose,
  onPick,
  /** Files already chosen for another lane, so the same file isn't picked twice. */
  excludeIds = [],
  title = "Use a previously uploaded file",
}: {
  open: boolean;
  onClose: () => void;
  onPick: (file: SessionFile) => void;
  excludeIds?: string[];
  title?: string;
}) {
  const queryClient = useQueryClient();
  const { data, isLoading, error } = usePreviousUploads(open);
  const [deleting, setDeleting] = useState<string | null>(null);

  // Escape closes, like every other dismissible layer in the app.
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;

  const items = data?.items ?? [];
  const used = data?.storage.used_bytes ?? 0;
  const limit = data?.storage.limit_bytes ?? 0;

  const handleDelete = async (fileId: string) => {
    setDeleting(fileId);
    try {
      await deleteSessionFile(fileId);
      await queryClient.invalidateQueries({ queryKey: ["session-files"] });
    } catch {
      /* the row stays; the list refetches on next open */
    } finally {
      setDeleting(null);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      onClick={onClose}
    >
      <div
        className="max-h-[80vh] w-full max-w-2xl overflow-y-auto rounded-2xl border border-border bg-card p-6 shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start justify-between gap-3">
          <div>
            <h3 className="inline-flex items-center gap-2 text-lg font-semibold text-foreground">
              <History className="h-4 w-4" /> {title}
            </h3>
            <p className="mt-1 text-sm text-muted-foreground">
              Files stay on the server for {data?.retention_days ?? 10} days after
              upload, then they are deleted.
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="text-muted-foreground hover:text-foreground"
            aria-label="Close"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        {limit > 0 && (
          <p className="mt-3 inline-flex items-center gap-1.5 text-xs text-muted-foreground">
            <HardDrive className="h-3.5 w-3.5" />
            {formatBytes(used)} of {formatBytes(limit)} used by this session
          </p>
        )}

        <div className="mt-4">
          {isLoading ? (
            <p className="inline-flex items-center gap-2 text-sm text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" /> Loading your uploads…
            </p>
          ) : error ? (
            <p className="inline-flex items-center gap-2 text-sm text-destructive">
              <AlertCircle className="h-4 w-4" /> Could not load your uploads.
            </p>
          ) : items.length === 0 ? (
            <p className="rounded-lg border border-dashed border-border px-3 py-8 text-center text-sm text-muted-foreground">
              Nothing uploaded in this session yet.
            </p>
          ) : (
            <ul className="flex flex-col gap-2">
              {items.map((file) => {
                const alreadyUsed = excludeIds.includes(file.file_id);
                const expiring = formatExpiry(file.expires_at);
                const soon = expiring.startsWith("less than");
                return (
                  <li
                    key={file.file_id}
                    className={cn(
                      "flex items-center gap-3 rounded-xl border px-3 py-2.5",
                      alreadyUsed ? "border-border/60 opacity-60" : "border-border",
                    )}
                  >
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="truncate text-sm font-medium text-foreground">
                          {file.filename}
                        </span>
                        <span className="rounded-full bg-muted px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
                          {file.file_type}
                        </span>
                        {alreadyUsed && (
                          <span className="rounded-full bg-primary/10 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-primary">
                            In use
                          </span>
                        )}
                      </div>
                      <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-muted-foreground">
                        <span>{formatBytes(file.size)}</span>
                        <span
                          className={cn(
                            "inline-flex items-center gap-1",
                            soon && "font-medium text-amber-600",
                          )}
                        >
                          <Clock className="h-3 w-3" />
                          {expiring}
                        </span>
                        {file.capabilities.length > 0 && (
                          <span className="truncate">
                            {file.capabilities.join(" · ")}
                          </span>
                        )}
                      </div>
                    </div>

                    <Button
                      size="sm"
                      variant={alreadyUsed ? "outline" : "default"}
                      disabled={alreadyUsed}
                      onClick={() => {
                        onPick(file);
                        onClose();
                      }}
                    >
                      Use
                    </Button>
                    <button
                      type="button"
                      title="Delete this upload from the server"
                      onClick={() => handleDelete(file.file_id)}
                      disabled={deleting === file.file_id}
                      className="text-muted-foreground transition-colors hover:text-destructive disabled:opacity-50"
                    >
                      {deleting === file.file_id ? (
                        <Loader2 className="h-4 w-4 animate-spin" />
                      ) : (
                        <Trash2 className="h-4 w-4" />
                      )}
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      </div>
    </div>
  );
}
