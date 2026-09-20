import type { StepMeta, StepMetaParam } from "@/api/customPipeline";
import { KIND_STYLE, familyKind } from "@/lib/stepColors";

/**
 * Parameters injected by the backend executor/wrappers — never shown to the
 * user (the server fills these in at run time).
 */
export const INJECTED_PARAMS = new Set<string>([
  "data",
  "seq_file",
  "seq_file_1",
  "seq_file_2",
  "head_file",
  "tail_file",
  "out_file",
  "output_file",
  "out_args",
  "out_dir",
  "out_name",
  "out_type",
  "file_type",
  "delimiter",
  "ref_dict",
  "ref_db",
  "db_handle",
  "aligner_exec",
  "db_exec",
  "assembly_stats",
  "output_duplicate",
  "output_undetermined",
  "primers",
  "primers_regex",
  "score_dict",
  "process_func",
  "process_args",
  "gap_penalty",
  "dependent",
  // AlignSets / ClusterSets / ConvertHeaders / EstimateError / UnifyHeaders:
  // the wrapper picks the aligner, cluster and consensus callables itself, and
  // the external binaries come from server config, never from the request.
  "align_func",
  "align_args",
  "cluster_func",
  "cluster_args",
  "convert_func",
  "convert_args",
  "collapse_func",
  "cons_func",
  "cons_args",
  "offset_dict",
  "aligner_exec",
  "cluster_exec",
  "nproc",
  "queue_size",
]);

export interface Category {
  key: string;
  label: string;
  /** Canonical oklch color tokens (shared with flowcharts / funnel / progress). */
  color: string;
  tint: string;
  border: string;
  text: string;
}

const CATEGORY_DEF: { prefix: string; label: string }[] = [
  { prefix: "ConvertHeaders", label: "Header conversion" },
  { prefix: "FilterSeq", label: "Quality & filtering" },
  { prefix: "MaskPrimers", label: "Primer masking" },
  { prefix: "PairSeq", label: "Pairing" },
  { prefix: "AssembleSeq", label: "Assembly" },
  { prefix: "ClusterSets", label: "Clustering" },
  { prefix: "AlignSets", label: "Set alignment" },
  { prefix: "BuildConsensus", label: "Consensus" },
  { prefix: "CollapseSeq", label: "Deduplication" },
  { prefix: "ParseHeaders", label: "Headers" },
  { prefix: "UnifyHeaders", label: "Header unification" },
  { prefix: "SplitSeq", label: "Splitting & sorting" },
  { prefix: "EstimateError", label: "Error estimation" },
];

function makeCategory(prefix: string, label: string): Category {
  const style = KIND_STYLE[familyKind(`${prefix}.x`)];
  return { key: prefix, label, ...style };
}

const FALLBACK = makeCategory("Other", "Other");

export function categoryForStep(stepName: string): Category {
  const prefix = stepName.split(".")[0];
  const def = CATEGORY_DEF.find((c) => c.prefix === prefix);
  return def ? makeCategory(def.prefix, def.label) : FALLBACK;
}

/** Ordered list of categories that actually have steps in `metas`. */
export function groupSteps(metas: StepMeta[]): { category: Category; steps: StepMeta[] }[] {
  return CATEGORY_DEF.map((def) => {
    const steps = metas
      .filter((m) => m.step.startsWith(`${def.prefix}.`) && !m.error)
      .sort((a, b) => a.step.localeCompare(b.step));
    return { category: makeCategory(def.prefix, def.label), steps };
  }).filter((g) => g.steps.length > 0);
}

/** Short, human label for a step, e.g. "MaskPrimers.score" → "score". */
export function stepShortLabel(stepName: string): string {
  const [, sub] = stepName.split(".");
  return sub ?? stepName;
}

export function humanizeParam(name: string): string {
  return name
    .replace(/_/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase())
    .replace(/\bId\b/, "ID");
}

/** Params the user should fill in (drops injected/system params). */
export function userParams(meta: StepMeta): StepMetaParam[] {
  return (meta.parameters ?? []).filter((p) => !INJECTED_PARAMS.has(p.name));
}

/** Whether a param is an uploaded-file reference for this step. */
export function isFileParam(meta: StepMeta, paramName: string): boolean {
  if (meta.requires_files?.includes(paramName)) return true;
  return /(_file|_files)$/.test(paramName) && paramName !== "out_file";
}

export type FieldKind = "number" | "boolean" | "array" | "text" | "file";

// pRESTO list params are field/action names (plural). min_field/max_field are
// single field NAMES (not lists), so only match the plural forms.
//
// `values` and `names` matter as much as `fields`: pRESTO pairs them with
// fields positionally via zip(), so a bare string would be zipped character by
// character and ParseHeaders.add would store LENGTH=p for a value of "parsa".
// (The backend wrapper now coerces these too, so a stale client cannot
// reintroduce the truncation -- this keeps the input widget honest as well.)
const LIST_PARAM = /(^fields$|^actions$|^values$|^names$|_fields$|_actions$|^fields_\d$)/;

/**
 * The backend metadata `type` is unreliable for unannotated params (it can be
 * "_empty" or "float | None"), so infer mainly from the default value's runtime
 * type, with name/type-string fallbacks. Numeric strings are coerced
 * server-side, so a missed number only affects the input widget, not the run.
 */
export function fieldKind(meta: StepMeta, p: StepMetaParam): FieldKind {
  if (isFileParam(meta, p.name)) return "file";
  if (typeof p.default === "boolean" || /\bbool/i.test(p.type)) return "boolean";
  if (Array.isArray(p.default) || LIST_PARAM.test(p.name) || /(list|array)/i.test(p.type))
    return "array";
  if (typeof p.default === "number" || /(^int|integer|float|^number|double)/i.test(p.type))
    return "number";
  return "text";
}
