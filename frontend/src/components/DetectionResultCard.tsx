import { CheckCircle2, Circle, AlertTriangle, Loader2 } from "lucide-react";
import type { DetectionResult, SingleCellFormatId } from "@/api/singleCell";
import { KIND_STYLE, type StepKind } from "@/lib/stepColors";
import { cn } from "@/lib/utils";

/** Maps a detected single-cell format onto the app-wide step color palette. */
function formatKind(formatId: SingleCellFormatId | null): StepKind {
  if (!formatId) return "blue";
  if (formatId.startsWith("cellranger")) return "blue";
  if (formatId === "trust4" || formatId === "fastq_10x" || formatId === "bam_10x") {
    return "orange";
  }
  return "green";
}

export function DetectionResultCard({
  result,
  isLoading,
}: {
  result: DetectionResult | undefined;
  isLoading: boolean;
}) {
  if (isLoading) {
    return (
      <div
        className="flex items-center gap-2 rounded-2xl border border-border bg-card p-5 text-sm text-muted-foreground"
        style={{ boxShadow: "var(--shadow-card)" }}
      >
        <Loader2 className="h-4 w-4 animate-spin" />
        Detecting input format…
      </div>
    );
  }

  if (!result) return null;

  const kind = formatKind(result.format_id);
  const style = KIND_STYLE[kind];

  return (
    <div
      className="rounded-2xl border border-border bg-card p-5"
      style={{ boxShadow: "var(--shadow-card)" }}
    >
      <div className="flex items-center justify-between gap-3">
        <h3 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
          Detected format
        </h3>
        {result.format_id && (
          <span
            className="inline-flex items-center rounded-full px-2.5 py-1 text-[11px] font-semibold uppercase tracking-wide"
            style={{ background: style.tint, color: style.text }}
          >
            {result.label}
          </span>
        )}
      </div>

      {!result.format_id && (
        <p className="mt-3 text-sm text-muted-foreground">
          {result.label
            ? `Closest match: ${result.label}. Upload the missing file(s) below to continue.`
            : "Upload files to detect a single-cell input format."}
        </p>
      )}

      {(result.matched_files.length > 0 || result.missing_files.length > 0) && (
        <ul className="mt-4 flex flex-col gap-1.5">
          {result.matched_files.map((f) => (
            <li
              key={f.file_id}
              className="flex items-center gap-2 text-sm text-foreground"
            >
              <CheckCircle2 className="h-4 w-4 shrink-0 text-primary" />
              <span className="truncate">{f.filename}</span>
              <span className="text-xs text-muted-foreground">({f.role})</span>
            </li>
          ))}
          {result.missing_files.map((f) => (
            <li
              key={f.role}
              className={cn(
                "flex items-center gap-2 text-sm",
                f.required ? "text-muted-foreground" : "text-muted-foreground/70",
              )}
            >
              <Circle className="h-4 w-4 shrink-0" />
              <span>{f.description}</span>
              <span className="text-xs">
                ({f.required ? "required" : "optional"})
              </span>
            </li>
          ))}
        </ul>
      )}

      {result.ambiguous_format_ids.length > 0 && (
        <p className="mt-4 flex items-start gap-2 rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs leading-relaxed text-amber-700">
          <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          This file set also matches: {result.ambiguous_format_ids.join(", ")}.
          Remove the extra files if {result.label} isn't what you intended.
        </p>
      )}

      {result.requires_trust4 && !result.trust4_available && (
        <p className="mt-4 flex items-start gap-2 rounded-lg border border-destructive/30 bg-destructive/5 px-3 py-2 text-xs leading-relaxed text-destructive">
          <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          This format requires TRUST4 assembly, which this server cannot run
          right now — see the assembly settings below for what's missing.
          Alternatively, run TRUST4 externally and upload its output instead
          (*_annot.fa + *_barcode_report.tsv).
        </p>
      )}
    </div>
  );
}
