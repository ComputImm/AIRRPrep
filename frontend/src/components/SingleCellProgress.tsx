import { CheckCircle2, Circle, Loader2, XCircle, Download, RotateCcw } from "lucide-react";
import type { JobProgress } from "@/hooks/useJobProgress";
import { singleCellOutputUrl } from "@/api/singleCell";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import { cn } from "@/lib/utils";

/**
 * Single-cell's job is a short linear pipeline (Parse -> Validate -> Write,
 * with a leading TRUST4 assembly stage for raw-read input), not a
 * user-composed chain of pRESTO steps with per-step pass/fail downloads -- so
 * this is a small dedicated component rather than a reuse of PipelineProgress
 * (which assumes that pRESTO-specific shape). It reuses the useJobProgress
 * HOOK as-is, since that only depends on the generic status/step_stats.length
 * shape.
 */
const DEFAULT_STAGES = ["Parse", "Validate", "Write FASTA + metadata"];

type RowState = "done" | "running" | "failed" | "pending";

function rowState(index: number, progress: JobProgress): RowState {
  const { phase, completedSteps, currentStep } = progress;
  if (phase === "done") return "done";
  if (phase === "failed") {
    const failedIdx = currentStep > 0 ? currentStep - 1 : completedSteps;
    if (index < failedIdx) return "done";
    if (index === failedIdx) return "failed";
    return "pending";
  }
  if (index < completedSteps) return "done";
  if (phase === "processing" && index === completedSteps) return "running";
  return "pending";
}

function RowIcon({ state }: { state: RowState }) {
  switch (state) {
    case "done":
      return <CheckCircle2 className="h-4 w-4 shrink-0 text-primary" />;
    case "running":
      return <Loader2 className="h-4 w-4 shrink-0 animate-spin text-primary" />;
    case "failed":
      return <XCircle className="h-4 w-4 shrink-0 text-destructive" />;
    default:
      return <Circle className="h-4 w-4 shrink-0 text-muted-foreground/40" />;
  }
}

export function SingleCellProgress({
  progress,
  stages = DEFAULT_STAGES,
  sessionId,
  jobId,
  recordCount,
  warnings,
  hasSourceAnnotations,
  onReset,
}: {
  progress: JobProgress;
  /** Stage labels in backend order; a TRUST4 job prepends an assembly stage. */
  stages?: string[];
  sessionId: string;
  jobId: string;
  recordCount?: number;
  warnings?: string[];
  /** Written only when the input carried fields the normalized output omits. */
  hasSourceAnnotations?: boolean;
  onReset: () => void;
}) {
  const { phase, percent } = progress;
  const isTerminal = phase === "done" || phase === "failed";

  return (
    <div
      className="flex flex-col gap-4 rounded-2xl border border-border bg-card p-5"
      style={{ boxShadow: "var(--shadow-card)" }}
    >
      <div className="flex items-center justify-between gap-2">
        <h3 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
          Progress
        </h3>
        <span className="text-xs font-medium text-muted-foreground">{percent}%</span>
      </div>
      <Progress value={percent} />

      {phase === "failed" && progress.error && (
        <p className="rounded-lg border border-destructive/30 bg-destructive/5 px-3 py-2 text-xs leading-relaxed text-destructive">
          {progress.error}
        </p>
      )}

      <ol className="flex flex-col gap-1.5">
        {stages.map((label, idx) => {
          const state = rowState(idx, progress);
          return (
            <li
              key={label}
              className={cn(
                "flex items-center gap-2 rounded-lg px-2 py-1.5 text-sm",
                state === "running" && "font-medium text-foreground",
                state === "done" && "text-foreground/80",
                state === "failed" && "font-medium text-destructive",
                state === "pending" && "text-muted-foreground",
              )}
            >
              <RowIcon state={state} />
              {label}
            </li>
          );
        })}
      </ol>

      {phase === "done" && (
        <div className="flex flex-col gap-3 border-t border-border/60 pt-3">
          {typeof recordCount === "number" && (
            <p className="text-sm text-foreground">
              <span className="font-semibold">{recordCount}</span> sequences
              written to the normalized output.
            </p>
          )}
          {warnings && warnings.length > 0 && (
            <ul className="flex flex-col gap-1 rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs text-amber-700">
              {warnings.map((w, i) => (
                <li key={i}>{w}</li>
              ))}
            </ul>
          )}
          <div className="flex flex-wrap gap-2">
            <a
              href={singleCellOutputUrl(sessionId, jobId, "final.fasta")}
              download
              className="inline-flex items-center gap-1.5 rounded-lg border border-primary/40 bg-primary/5 px-3 py-1.5 text-sm font-medium text-primary transition-colors hover:bg-primary/10"
            >
              <Download className="h-4 w-4" />
              Download FASTA
            </a>
            <a
              href={singleCellOutputUrl(sessionId, jobId, "metadata.tsv")}
              download
              className="inline-flex items-center gap-1.5 rounded-lg border border-primary/40 bg-primary/5 px-3 py-1.5 text-sm font-medium text-primary transition-colors hover:bg-primary/10"
            >
              <Download className="h-4 w-4" />
              Download metadata TSV
            </a>
            {hasSourceAnnotations && (
              <a
                href={singleCellOutputUrl(
                  sessionId,
                  jobId,
                  "source_annotations.tsv",
                )}
                download
                title="Every field the uploaded file carried, including the upstream V(D)J calls and CDR3s the normalized output omits, keyed on the same sequence_id."
                className="inline-flex items-center gap-1.5 rounded-lg border border-primary/40 bg-primary/5 px-3 py-1.5 text-sm font-medium text-primary transition-colors hover:bg-primary/10"
              >
                <Download className="h-4 w-4" />
                Download source annotations
              </a>
            )}
            <a
              href={singleCellOutputUrl(sessionId, jobId, "provenance.json")}
              download
              className="inline-flex items-center gap-1.5 rounded-lg border border-border px-3 py-1.5 text-sm font-medium text-muted-foreground transition-colors hover:bg-muted"
            >
              <Download className="h-4 w-4" />
              Download provenance
            </a>
          </div>
        </div>
      )}

      {isTerminal && (
        <Button variant="outline" size="sm" onClick={onReset} className="gap-1.5">
          <RotateCcw className="h-3.5 w-3.5" />
          Run a new preprocessing job
        </Button>
      )}
    </div>
  );
}
