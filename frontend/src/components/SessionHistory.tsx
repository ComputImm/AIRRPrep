import { useState } from "react";
import {
  CheckCircle2,
  AlertTriangle,
  Loader2,
  ChevronDown,
  ChevronRight,
  Download,
  FileArchive,
  History,
  Scissors,
  StopCircle,
} from "lucide-react";
import {
  jobArchiveUrl,
  jobOutputUrl,
  stepFileUrl,
  stepPartUrl,
  type SessionHistoryEntry,
  type StepStat,
} from "@/api/jobs";
import { singleCellOutputUrl } from "@/api/singleCell";
import { StepFunnel } from "@/components/StepFunnel";
import { cn } from "@/lib/utils";

type Phase = "queued" | "processing" | "done" | "failed" | "cancelled";

function phaseOf(status: string): Phase {
  if (status === "DONE") return "done";
  if (status.startsWith("CANCELLED")) return "cancelled";
  if (status.startsWith("FAILED") || status.startsWith("Fail ")) return "failed";
  if (status.startsWith("PROCESSING") || status.startsWith("DONE ")) return "processing";
  return "queued";
}

const PHASE_STYLE: Record<Phase, string> = {
  queued: "bg-muted text-muted-foreground",
  processing: "bg-primary/10 text-primary",
  done: "bg-emerald-500/10 text-emerald-600",
  failed: "bg-destructive/10 text-destructive",
  // Stopped deliberately, so amber rather than the red used for a failure.
  cancelled: "bg-amber-500/10 text-amber-600",
};

const PHASE_LABEL: Record<Phase, string> = {
  queued: "Queued",
  processing: "Running",
  done: "Completed",
  failed: "Failed",
  cancelled: "Stopped",
};

/**
 * Steps whose output is a table (TSV), not reads.
 *
 * They have no pass/fail split at all -- every input row either became a table
 * row or was not annotated -- so a "Fail" link here would only ever 404.
 */
function isTableStep(name: string): boolean {
  return (
    name === "ParseHeaders.table" ||
    name === "AlignSets.table" ||
    name.startsWith("EstimateError.")
  );
}

function formatWhen(value?: string): string {
  if (!value) return "";
  const t = Date.parse(value);
  if (!Number.isFinite(t)) return value;
  return new Date(t).toLocaleString();
}

function StepDownloads({
  stat,
  sessionId,
  jobId,
}: {
  stat: StepStat;
  sessionId: string;
  jobId: string;
}) {
  const passLanes = Object.keys(stat.output_paths ?? {}).filter(
    (lane) => !lane.endsWith("_fail"),
  );
  const multi = passLanes.length > 1;
  const parts = stat.parts ?? [];
  const table = isTableStep(stat.name);
  const showFail = !table && (stat.failed ?? 0) > 0;
  if (passLanes.length === 0 && parts.length === 0) return null;

  // A step that fanned its lane out wrote N files, not one: list every part
  // rather than only the one the pipeline would have carried forward.
  if (parts.length > 0) {
    return (
      <div className="flex flex-wrap items-center gap-1.5">
        <span className="inline-flex items-center gap-1 text-[11px] text-muted-foreground">
          <Scissors className="h-3 w-3" />
          {stat.index}. {stat.name} ({parts.length} files)
        </span>
        {parts.map((part) => (
          <a
            key={part.label}
            href={stepPartUrl(sessionId, jobId, stat.index, part.label)}
            download
            className="inline-flex items-center gap-1 rounded-md border border-primary/30 px-1.5 py-0.5 text-[10px] font-medium text-primary transition-colors hover:bg-primary/10"
          >
            <Download className="h-3 w-3" />
            {part.label}
            {part.sequences != null && (
              <span className="opacity-70">({part.sequences})</span>
            )}
          </a>
        ))}
      </div>
    );
  }

  return (
    <div className="flex flex-wrap items-center gap-1.5">
      <span className="text-[11px] text-muted-foreground">
        {stat.index}. {stat.name}
      </span>
      {passLanes.map((lane) => (
        <a
          key={`p-${lane}`}
          href={stepFileUrl(sessionId, jobId, stat.index, "pass", lane)}
          download
          className="inline-flex items-center gap-1 rounded-md border border-primary/30 px-1.5 py-0.5 text-[10px] font-medium text-primary transition-colors hover:bg-primary/10"
        >
          <Download className="h-3 w-3" />
          {table ? "TSV" : multi ? `Pass ${lane}` : "Pass"}
        </a>
      ))}
      {showFail &&
        passLanes.map((lane) => (
          <a
            key={`f-${lane}`}
            href={stepFileUrl(sessionId, jobId, stat.index, "fail", lane)}
            download
            className="inline-flex items-center gap-1 rounded-md border border-destructive/30 px-1.5 py-0.5 text-[10px] font-medium text-destructive transition-colors hover:bg-destructive/10"
          >
            <Download className="h-3 w-3" />
            {multi ? `Fail ${lane}` : "Fail"}
          </a>
        ))}
    </div>
  );
}

/**
 * Single-cell jobs go through a fixed 3-stage (Parse/Validate/Write)
 * pipeline, not pRESTO steps with per-lane pass/fail counts -- StepFunnel's
 * before/failed/remaining bars and StepDownloads' step-index download links
 * don't apply, so this renders a simpler summary + the two final downloads
 * instead.
 */
 function SingleCellHistoryDetails({
  entry,
  sessionId,
}: {
  entry: SessionHistoryEntry;
  sessionId: string;
}) {
  const phase = phaseOf((entry.job.status ?? "").toString());

  const recordCount = entry.job.record_count as number | undefined;

  const warnings =
    (entry.job.warnings as string[] | undefined) ?? [];

  const error =
    typeof entry.job.error === "string"
      ? entry.job.error.trim()
      : "";

  return (
    <div className="flex flex-col gap-3">
      {phase === "failed" && error && (
        <div className="rounded-lg border border-destructive/30 bg-destructive/5 px-3 py-2">
          <div className="flex items-start gap-2">
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-destructive" />
            <div className="min-w-0">
              <p className="text-xs font-semibold text-destructive">
                Pipeline failed
              </p>
              <p className="mt-1 break-words text-sm text-destructive">
                {error}
              </p>
            </div>
          </div>
        </div>
      )}

      {phase === "failed" && !error && (
        <p className="rounded-lg border border-destructive/30 bg-destructive/5 px-3 py-2 text-sm text-destructive">
          The pipeline failed without a detailed error message.
        </p>
      )}

      {typeof recordCount === "number" && (
        <p className="text-sm text-foreground">
          <span className="font-semibold">{recordCount}</span> sequences in
          the normalized output.
        </p>
      )}

      {warnings.length > 0 && (
        <ul className="flex flex-col gap-1 rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs text-amber-700">
          {warnings.map((w, i) => (
            <li key={i}>{w}</li>
          ))}
        </ul>
      )}

      {phase === "done" && sessionId && (
        <div className="flex flex-wrap gap-2">
          <a
            href={singleCellOutputUrl(
              sessionId,
              entry.id,
              "final.fasta",
            )}
            download
            className="inline-flex w-fit items-center gap-2 rounded-lg border border-primary/40 bg-primary/5 px-3 py-1.5 text-sm font-medium text-primary transition-colors hover:bg-primary/10"
          >
            <Download className="h-4 w-4" />
            Download FASTA
          </a>

          <a
            href={singleCellOutputUrl(
              sessionId,
              entry.id,
              "metadata.tsv",
            )}
            download
            className="inline-flex w-fit items-center gap-2 rounded-lg border border-primary/40 bg-primary/5 px-3 py-1.5 text-sm font-medium text-primary transition-colors hover:bg-primary/10"
          >
            <Download className="h-4 w-4" />
            Download metadata TSV
          </a>
        </div>
      )}
    </div>
  );
}

function HistoryRow({ entry }: { entry: SessionHistoryEntry }) {
  const [open, setOpen] = useState(false);
  const status = (entry.job.status ?? "").toString();
  const phase = phaseOf(status);
  const isSingleCell = entry.job.module === "single_cell";
  const stepStats = entry.job.step_stats ?? [];
  // Single-cell jobs are created with an empty `steps` array (they don't
  // use the bulk pRESTO step-chain field) -- `|| ` (not `??`) so the 0-length
  // case falls back to stepStats.length instead of showing "N/0 steps".
  const totalSteps = entry.job.steps?.length || stepStats.length;
  const sessionId = entry.job.session_id ?? "";
  // A run whose last step fanned out has no single final output to offer.
  // Read from the run rather than counted off the last step's parts: a
  // thresholded SplitSeq.group writes two files and still has a final output.
  const endsInSplit = entry.job.ends_in_split === true;

  return (
    <li className="rounded-xl border border-border/70 bg-background">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-3 px-4 py-3 text-left"
      >
        {open ? (
          <ChevronDown className=" h-4 w-4 shrink-0 text-muted-foreground" />
        ) : (
          <ChevronRight className="h-4 w-4 shrink-0 text-muted-foreground" />
        )}
        <span
          className={cn(
            "inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[11px] font-semibold uppercase tracking-wide",
            PHASE_STYLE[phase],
          )}
        >
          {phase === "processing" && <Loader2 className="h-3 w-3 animate-spin" />}
          {phase === "done" && <CheckCircle2 className="h-3 w-3" />}
          {phase === "failed" && <AlertTriangle className="h-3 w-3" />}
          {phase === "cancelled" && <StopCircle className="h-3 w-3" />}
          {PHASE_LABEL[phase]}
        </span>
        <span className="min-w-0 flex-1 truncate text-sm text-foreground">
          {stepStats.length}/{totalSteps} steps
          <span className="ml-2 font-mono text-xs text-muted-foreground">
            {entry.id.slice(0, 8)}
          </span>
        </span>
        <span className="shrink-0 text-xs text-muted-foreground">
          {formatWhen(entry.job.created_at)}
        </span>
      </button>

      {open && (
        <div className="border-t border-border/60 px-4 py-4">
          

          {isSingleCell ? (
            <SingleCellHistoryDetails entry={entry} sessionId={sessionId} />
          ) : stepStats.length > 0 ? (
            <div className="flex item center grid gap-5 ">
              <StepFunnel stepStats={stepStats} showDownload={true}  />
              <div className="flex flex-col gap-3">
                <div className="flex flex-wrap gap-2">
                  {phase === "done" && sessionId && !endsInSplit && (
                    <a
                      href={jobOutputUrl(sessionId, entry.id)}
                      download
                      className="inline-flex w-fit items-center gap-2 rounded-lg border border-primary/40 bg-primary/5 px-3 py-1.5 text-sm font-medium text-primary transition-colors hover:bg-primary/10"
                    >
                      <Download className="h-4 w-4" />
                      Download final output
                    </a>
                  )}
                  {/* Offered for stopped and failed runs too: the steps that
                      did finish produced real files worth keeping. */}
                  {sessionId && (
                    <a
                      href={jobArchiveUrl(sessionId, entry.id, "outputs")}
                      download
                      className="inline-flex w-fit items-center gap-2 rounded-lg border border-primary/40 bg-primary/5 px-3 py-1.5 text-sm font-medium text-primary transition-colors hover:bg-primary/10"
                    >
                      <FileArchive className="h-4 w-4" />
                      Download all results (.zip)
                    </a>
                  )}
                </div>
                {endsInSplit && (
                  <p className="text-xs text-muted-foreground">
                    This run ends in a split, so there is no single final
                    output. The parts listed below are the result.
                  </p>
                )}
                <div className="flex flex-col gap-2">
                  <h4 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                    Per-step files
                  </h4>
                  {sessionId &&
                    stepStats.map((stat) => (
                      <StepDownloads
                        key={stat.index}
                        stat={stat}
                        sessionId={sessionId}
                        jobId={entry.id}
                      />
                    ))}
                </div>
              </div>
            </div>
          ) : (
            <p className="text-sm text-muted-foreground">
              No step results recorded for this run yet.
            </p>
          )}
        </div>
      )}
    </li>
  );
}

export function SessionHistory({ entries }: { entries: SessionHistoryEntry[] }) {
  if (entries.length === 0) return null;

  return (
    <section className="mt-12">
      <div className="flex items-center gap-2">
        <History className="h-4 w-4 text-muted-foreground" />
        <h2 className="text-xl font-semibold tracking-tight text-foreground">
          Session history
        </h2>
      </div>
      <p className="mt-1.5 text-sm text-muted-foreground">
        Every pipeline run in this session, with its sequence-retention funnel
        and downloadable outputs.
      </p>
      <ul className="mt-5 flex flex-col gap-2">
        {entries.map((entry) => (
          <HistoryRow key={entry.id} entry={entry} />
        ))}
      </ul>
    </section>
  );
}
