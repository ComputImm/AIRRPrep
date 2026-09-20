import { publicApi } from "./client";
import type { PipelineStep } from "./jobs";

/** One step's metadata as returned by GET /steps. */
export interface StepMetaParam {
  name: string;
  required: boolean;
  default: unknown;
  type: string;
  kind: string;
  /**
   * "single" | "list" | null -- set when this param names an existing (or
   * new) sequence header field, e.g. SplitSeq's `field` or ParseHeaders'
   * `fields`. The UI renders these as a dropdown of the pipeline's actual
   * known fields at this stage (PlannerStateResponse.lane_fields) instead of
   * a free-text box; null means it's an ordinary param.
   */
  field_kind?: "single" | "list" | null;
}

export interface StepMeta {
  step: string;
  function?: string;
  module?: string;
  description?: string;
  stream_behavior: "per_lane" | "paired_io" | "merge_paired";
  requires_files: string[];
  /** External binaries the step shells out to (muscle, usearch, …). */
  requires_executable?: string[];
  /** "same" keeps the lane's format; "tab" ends the sequence stream (TSV). */
  output_type?: string;
  /**
   * "always" | "conditional" | null -- whether this step fans its lane out
   * into several files, which ends the pipeline. "conditional" depends on the
   * parameters; see src/lib/splitting.ts.
   */
  splits_output?: "always" | "conditional" | null;
  parameters: StepMetaParam[];
  error?: string;
}

/** A step the planner says is valid as the next pipeline step. */
export interface ValidNextStep {
  step: string;
  allowed_lanes: string[];
  requires_capabilities: string[];
  requires_any_capabilities: string[];
  produces_capabilities: string[];
  requires_files: string[];
  requires_executable?: string[];
  input_types: string[];
  output_type: string;
  stream_behavior: "per_lane" | "paired_io" | "merge_paired";
  splits_output?: "always" | "conditional" | null;
}

export interface PlannerStateResponse {
  stream_mode: "single" | "dual";
  input_format: string;
  lane_file_types: Record<string, string>;
  lane_capabilities: Record<string, string[]>;
  /** Concrete annotation field names known to exist in each lane right now. */
  lane_fields: Record<string, string[]>;
  /**
   * False when a lane's field list may be incomplete (an unrecognized or
   * not-yet-normalized header format) -- the dropdown should still allow a
   * typed/custom value in that case rather than only its known options.
   */
  lane_fields_confident: Record<string, boolean>;
  lane_file_ids: Record<string, string>;
  valid_next_steps: ValidNextStep[];
  /**
   * Name of the step that fanned the lane out, once one has. Nothing may
   * follow it, so `valid_next_steps` is empty -- this is what lets the UI say
   * why instead of leaving every component silently locked.
   */
  terminated_by?: string | null;
}

export interface CustomInitResponse extends PlannerStateResponse {
  chains: number;
  message: string;
}

/** All pipeline steps with parameter metadata (drives the palette + forms). */
export function getAllSteps() {
  return publicApi<StepMeta[]>("/steps");
}

export function customInit(body: { chains: 1 | 2; file_ids: string[] }) {
  return publicApi<CustomInitResponse>("/api/pipeline/custom/init", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export interface CustomNextStepsBody {
  chains: 1 | 2;
  file_ids: string[];
  steps: PipelineStep[];
  draft_step?: PipelineStep;
  input_format?: "fasta" | "fastq";
}

/**
 * Recompute valid next steps for a pipeline prefix. When `draft_step` is
 * supplied the backend validates it first (400 if it does not fit) and returns
 * the state as if it were appended.
 */
export function customNextSteps(body: CustomNextStepsBody) {
  return publicApi<PlannerStateResponse>("/api/pipeline/custom/next-steps", {
    method: "POST",
    body: JSON.stringify(body),
  });
}
