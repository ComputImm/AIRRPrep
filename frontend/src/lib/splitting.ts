/**
 * Which steps fan one lane out into several files.
 *
 * Mirrors app/pipeline/splitting.py so the builder can warn *before* a step is
 * added rather than letting the backend reject the next one with no
 * explanation. The backend stays the authority -- this only decides what the
 * dialog says.
 *
 * A fan-out ends the pipeline: the lane is now N files, not one stream, and
 * carrying every part through the remaining steps would multiply the work by a
 * number nobody chose (SplitSeq.group on a free-text annotation is one file
 * per distinct value). The parts are the run's output and each is downloadable.
 */

/** How many outputs a max_count parameter asks for. */
function countOf(value: unknown): number {
  if (value == null || value === "") return 0;
  if (Array.isArray(value)) return value.filter((v) => v != null && v !== "").length;
  if (typeof value === "string") {
    return value.split(",").map((v) => v.trim()).filter(Boolean).length;
  }
  return 1;
}

const isBlank = (v: unknown) => v == null || v === "";

/** True when this step, with these parameters, writes more than one file. */
export function stepSplitsOutput(step: string, params: Record<string, unknown>): boolean {
  switch (step) {
    case "SplitSeq.count":
      return true;
    case "SplitSeq.group":
      // A numeric threshold is the bounded two-way under/at-least split (the
      // DUPCOUNT >= 2 idiom), which carries the at-least part forward.
      return isBlank(params.threshold);
    case "SplitSeq.sort":
      return !isBlank(params.max_count);
    case "SplitSeq.sample":
    case "SplitSeq.samplepair":
      return countOf(params.max_count) > 1;
    default:
      return false;
  }
}

/** One sentence saying why this step will end the pipeline. */
export function splitReason(step: string, params: Record<string, unknown>): string | null {
  if (!stepSplitsOutput(step, params)) return null;
  switch (step) {
    case "SplitSeq.count": {
      const max = params.max_count;
      return isBlank(max)
        ? "This writes one file per partition."
        : `This writes one file per ${max} reads — 20,000 reads at ${max} gives ${Math.ceil(
            20000 / Number(max),
          )} files.`;
    }
    case "SplitSeq.group": {
      const field = params.field ? String(params.field).toUpperCase() : "the field";
      return `Without a threshold this writes one file per distinct value of ${field}.`;
    }
    case "SplitSeq.sort":
      return `Sorting with a max count of ${params.max_count} also partitions the reads into separate files.`;
    default:
      return `Asking for ${countOf(params.max_count)} sample sizes writes one output per size.`;
  }
}

/** The note shown under a step that will end the pipeline. */
export function splitWarning(step: string, params: Record<string, unknown>): string | null {
  const reason = splitReason(step, params);
  if (!reason) return null;
  return `${reason} The pipeline ends here — every part is downloadable, and you can start a new run from whichever one you need.`;
}

/**
 * Whether a step *might* split, from its contract alone.
 *
 * "always" is unconditional; "conditional" depends on the parameters, so the
 * dialog shows a softer note that sharpens once a value is typed.
 */
export type SplitMode = "always" | "conditional" | null;

export function splitHint(mode: SplitMode): string | null {
  if (mode === "always") {
    return "This step splits its output into several files and ends the pipeline.";
  }
  if (mode === "conditional") {
    return "Depending on the parameters below, this step may split its output into several files and end the pipeline.";
  }
  return null;
}
