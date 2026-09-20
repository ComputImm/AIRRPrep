import { useRef, useState } from "react";
import { toPng } from "html-to-image";
import {
  CheckCircle2,
  Loader2,
  Circle,
  AlertTriangle,
  XCircle,
  Download,
  FileArchive,
  RotateCcw,
  Scissors,
  StopCircle,
  Table2,
} from "lucide-react";
import {
  cancelJob,
  jobArchiveUrl,
  stepFileUrl,
  stepPartUrl,
  type StepStat,
} from "@/api/jobs";
import type { JobProgress } from "@/hooks/useJobProgress";
import { Progress } from "@/components/ui/progress";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { KIND_STYLE, type StepKind } from "@/lib/stepColors";

export type NodeKind = StepKind;

/** Static, file-independent description of a pipeline step for the panel. */
export interface ProgressStepDescriptor {
  /** Backend step name, e.g. "FilterSeq.quality". */
  name: string;
  /** Human label shown in the panel. */
  label: string;
  /** Optional second line, e.g. "C-region primer". */
  sub?: string;
  /** Color family that matches the step's node in the flowchart. */
  color: NodeKind;
}

type RowState = "done" | "running" | "failed" | "pending";

/** Steps whose output is a table (TSV), not reads -- no pass/fail split. */
function isTableStep(name: string): boolean {
  return (
    name === "ParseHeaders.table" ||
    name === "AlignSets.table" ||
    name.startsWith("EstimateError.")
  );
}

function rowState(index: number, progress: JobProgress): RowState {
  const { phase, completedSteps, currentStep } = progress;

  if (phase === "done") return "done";

  // A stopped run finished some steps and never started the others; nothing
  // failed, so no row should be marked as such.
  if (phase === "cancelled") {
    return index < completedSteps ? "done" : "pending";
  }

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

const PHASE_LABEL: Record<JobProgress["phase"], string> = {
  queued: "Queued",
  processing: "Running",
  done: "Completed",
  failed: "Failed",
  cancelled: "Stopped",
};

function PhaseBadge({ phase }: { phase: JobProgress["phase"] }) {
  const styles: Record<JobProgress["phase"], string> = {
    queued: "bg-muted text-muted-foreground",
    processing: "bg-primary/10 text-primary",
    done: "bg-emerald-500/10 text-emerald-600",
    failed: "bg-destructive/10 text-destructive",
    // Stopped on purpose, so amber rather than the red used for a failure.
    cancelled: "bg-amber-500/10 text-amber-600",
  };
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[11px] font-semibold uppercase tracking-wide",
        styles[phase],
      )}
    >
      {phase === "processing" && <Loader2 className="h-3 w-3 animate-spin" />}
      {phase === "done" && <CheckCircle2 className="h-3 w-3" />}
      {phase === "failed" && <AlertTriangle className="h-3 w-3" />}
      {phase === "cancelled" && <StopCircle className="h-3 w-3" />}
      {PHASE_LABEL[phase]}
    </span>
  );
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

/** A compact download link styled as a chip. */
function DownloadChip({
  href,
  label,
  tone,
  icon = "download",
}: {
  href: string;
  label: string;
  tone: "pass" | "fail";
  icon?: "download" | "table";
}) {
  return (
    <a
      href={href}
      download
      className={cn(
        "inline-flex items-center gap-1 rounded-md border px-1.5 py-0.5 text-[10px] font-medium transition-colors",
        tone === "pass"
          ? "border-primary/30 text-primary hover:bg-primary/10"
          : "border-destructive/30 text-destructive hover:bg-destructive/10",
      )}
    >
      {icon === "table" ? (
        <Table2 className="h-3 w-3" />
      ) : (
        <Download className="h-3 w-3" />
      )}
      {label}
    </a>
  );
}

/**
 * Counts and download chips for a finished step.
 *
 * Three shapes of step end up here and they are not interchangeable:
 *
 * - an ordinary filter, with a pass file and (when anything failed) a fail one;
 * - a table step, which turned reads into TSV rows and has no fail file at all,
 *   so offering "Fail" would only ever 404;
 * - a splitting step, which wrote N part files rather than one, each listed
 *   with its own label and record count.
 */
function StepDetails({
  stat,
  sessionId,
  jobId,
}: {
  stat: StepStat;
  sessionId?: string;
  jobId: string;
}) {
  const passLanes = Object.keys(stat.output_paths ?? {}).filter(
    (lane) => !lane.endsWith("_fail"),
  );
  const multiLane = passLanes.length > 1;
  const parts = stat.parts ?? [];
  const table = isTableStep(stat.name);
  const showFail = !table && (stat.failed ?? 0) > 0;

  return (
    <div className="ml-6 mt-1 flex min-w-0 flex-col gap-1">
      <div className="flex min-w-0 flex-wrap items-center gap-x-2 text-[10px] font-medium">
        {table ? (
          <span className="text-emerald-600">{stat.remaining ?? 0} rows</span>
        ) : (
          <>
            <span className="text-emerald-600">pass {stat.remaining ?? 0}</span>
            <span className="text-muted-foreground/50">·</span>
            <span className="text-destructive">fail {stat.failed ?? 0}</span>
          </>
        )}
        {parts.length > 0 && (
          <>
            <span className="text-muted-foreground/50">·</span>
            <span className="inline-flex items-center gap-1 text-muted-foreground">
              <Scissors className="h-3 w-3" />
              {parts.length} files
            </span>
          </>
        )}
      </div>

      {sessionId && parts.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {parts.map((part) => (
            <DownloadChip
              key={part.label}
              tone="pass"
              href={stepPartUrl(sessionId, jobId, stat.index, part.label)}
              label={
                part.sequences != null
                  ? `${part.label} (${part.sequences})`
                  : part.label
              }
            />
          ))}
        </div>
      )}

      {sessionId && parts.length === 0 && passLanes.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {passLanes.map((lane) => (
            <DownloadChip
              key={`pass-${lane}`}
              tone="pass"
              icon={table ? "table" : "download"}
              href={stepFileUrl(sessionId, jobId, stat.index, "pass", lane)}
              label={table ? "TSV" : multiLane ? `Pass ${lane}` : "Pass"}
            />
          ))}
          {showFail &&
            passLanes.map((lane) => (
              <DownloadChip
                key={`fail-${lane}`}
                tone="fail"
                href={stepFileUrl(sessionId, jobId, stat.index, "fail", lane)}
                label={multiLane ? `Fail ${lane}` : "Fail"}
              />
            ))}
        </div>
      )}
    </div>
  );
}

export function PipelineProgress({
  progress,
  steps,
  jobId,
  onReset,
}: {
  progress: JobProgress;
  steps: ProgressStepDescriptor[];
  jobId: string;
  onReset: () => void;
}) {
  const { phase, percent, currentStep, totalSteps, isLoading } = progress;
  const isTerminal =
    phase === "done" || phase === "failed" || phase === "cancelled";
  const [stopping, setStopping] = useState(false);
  const [stopError, setStopError] = useState<string | null>(null);
  // Read from the job document rather than the status text: `status` belongs
  // to the worker (see app/api/jobs.py), so a stop is recorded as its own flag.
  const stopRequested =
    stopping || progress.raw?.cancel_requested === true;

  // Stopping is a step-boundary operation on the backend, so the run keeps
  // going for as long as the current step takes. Saying so up front is the
  // difference between "it ignored me" and "it heard me".
  const handleStop = async () => {
    setStopping(true);
    setStopError(null);
    try {
      await cancelJob(jobId);
    } catch (e) {
      setStopping(false);
      setStopError(
        e instanceof Error ? "Could not stop the run." : "Could not stop the run.",
      );
    }
  };
  const progressRef = useRef<HTMLDivElement>(null);
  const [downloadingProgress, setDownloadingProgress] = useState(false);
   const handleDownloadProgress = async () => {
    if (!progressRef.current) return;
    setDownloadingProgress(true);
    try {
      await new Promise(resolve => setTimeout(resolve, 150));
      
      const dataUrl = await toPng(progressRef.current, {
        pixelRatio: 2.5,
        backgroundColor: "#ffffff",
        cacheBust: true,
      });
      
      const a = document.createElement("a");
      a.download = `pipeline-progress-${new Date().toISOString().slice(0,10)}.png`;
      a.href = dataUrl;
      a.click();
    } catch (e) {
      console.error("Download progress chart failed", e);
    } finally {
      setDownloadingProgress(false);
    }
  };
  return (
    <aside
    ref={progressRef}
      className="flex h-fit w-full min-w-0 flex-col gap-4 rounded-2xl border border-border bg-card p-5 lg:sticky lg:top-6"
      style={{ boxShadow: "var(--shadow-card)" }}
      aria-label="Pipeline progress"
    >
      <div className="flex items-center justify-between gap-2">
        <h3 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
          Progress
        </h3>
        {/* <div className="flex items-center gap-2">  
          <Button 
            size="sm"
            variant="ghost"
            onClick={handleDownloadProgress}
            disabled={downloadingProgress}
            className="h-7 gap-1 px-2 text-xs"
            title="Download progress chart as PNG"
          >
            {downloadingProgress ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <Download className="h-3.5 w-3.5" />
            )}
            <span className="hidden sm:inline">PNG</span>
          </Button>
          <PhaseBadge phase={phase} />
        </div>  */}
        <PhaseBadge phase={phase} />
      </div>

      <div>
        <div className="flex flex-wrap items-end justify-between gap-x-2">
          <span className="text-3xl font-semibold tabular-nums text-foreground">
            {percent}%
          </span>
          <span className="text-xs font-medium text-muted-foreground">
            {phase === "done"
              ? `${totalSteps} / ${totalSteps} steps`
              : `Step ${Math.min(Math.max(currentStep, 0), totalSteps)} / ${totalSteps}`}
          </span>
        </div>
        <Progress value={percent} className="mt-2" />
      </div>

      {isLoading && (
        <p className="text-xs text-muted-foreground">Connecting to backend…</p>
      )}

      {phase === "cancelled" && (
        <p className="rounded-lg border border-amber-500/30 bg-amber-500/5 px-3 py-2 text-xs leading-relaxed text-amber-700">
          You stopped this run. The steps that finished are below and their
          files are still downloadable.
        </p>
      )}

      {phase === "failed" && progress.statusText && (
        <p className="rounded-lg border border-destructive/30 bg-destructive/5 px-3 py-2 text-xs leading-relaxed text-destructive">
          {progress.statusText}
        </p>
      )}

      <ol className="flex max-h-[30rem] min-w-0 flex-col gap-1.5 overflow-y-auto pr-1">
        {steps.map((step, idx) => {
          const state = rowState(idx, progress);
          const stat = progress.stepStats.find((s) => s.index === idx + 1);
          return (
            <li key={`${step.name}-${idx}`} className="min-w-0">
              <div
                className={cn(
                  "flex min-w-0 items-center gap-2 rounded-lg border-l-[3px] px-2 py-1.5 text-xs transition-colors",
                  state === "running" && "font-medium text-foreground",
                  state === "done" && "text-foreground/80",
                  state === "failed" && "font-medium text-destructive",
                  state === "pending" && "text-muted-foreground",
                )}
                style={{
                  borderLeftColor: KIND_STYLE[step.color].border,
                  background:
                    state === "running" || state === "done"
                      ? KIND_STYLE[step.color].tint
                      : "transparent",
                }}
              >
                <RowIcon state={state} />
                <span
                  className="min-w-0 flex-1 truncate"
                  title={step.sub ? `${step.label} · ${step.sub}` : step.label}
                >
                  <span className="tabular-nums text-muted-foreground/70">
                    {idx + 1}.
                  </span>{" "}
                  {step.label}
                  {step.sub && (
                    <span className="text-muted-foreground/70"> · {step.sub}</span>
                  )}
                </span>
              </div>
              {stat && (state === "done" || state === "failed") && (
                <StepDetails
                  stat={stat}
                  sessionId={progress.sessionId}
                  jobId={jobId}
                />
              )}
            </li>
          );
        })}
      </ol>

      {/* Everything this run produced, in one archive: per-step outputs plus
          the final result. A run that ended in a split has no single final
          output, which makes this the only way to take all of it at once. */}
      {progress.sessionId && progress.stepStats.length > 0 && (
        <a
          href={jobArchiveUrl(progress.sessionId, jobId, "outputs")}
          download
          className="inline-flex w-full items-center justify-center gap-2 rounded-lg border border-primary/40 bg-primary/5 px-3 py-2 text-xs font-medium text-primary transition-colors hover:bg-primary/10"
        >
          <FileArchive className="h-4 w-4" />
          Download all results (.zip)
        </a>
      )}

      {!isTerminal && (
        <div className="flex flex-col gap-1.5">
          <Button
            variant="outline"
            size="sm"
            onClick={handleStop}
            disabled={stopRequested}
            className="gap-1.5 border-destructive/40 text-destructive hover:bg-destructive/10 hover:text-destructive"
          >
            {stopRequested ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <StopCircle className="h-3.5 w-3.5" />
            )}
            {stopRequested ? "Stopping…" : "Stop this run"}
          </Button>
          {stopRequested && (
            <p className="text-[11px] leading-snug text-muted-foreground">
              The run stops after the step in progress finishes. Everything
              completed so far stays downloadable.
            </p>
          )}
          {stopError && (
            <p className="text-[11px] text-destructive">{stopError}</p>
          )}
        </div>
      )}

      {isTerminal && (
        <Button
          variant="outline"
          size="sm"
          onClick={onReset}
          className="mt-1 gap-1.5"
        >
          <RotateCcw className="h-3.5 w-3.5" />
          Run a new pipeline
        </Button>
      )}
    </aside>
  );
}
