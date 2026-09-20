/**
 * Single source of truth for step colors across the whole app.
 *
 * The palette and the family→color mapping mirror the ready-made pipeline
 * flowcharts (race / umi / nonumi), so a given step family has the SAME color
 * everywhere: flowcharts, the live progress panel, the retention funnel, and
 * the custom builder.
 */

export type StepKind = "pink" | "orange" | "green" | "blue";

export interface KindStyle {
  /** solid accent (dots, funnel fills). */
  color: string;
  /** light background tint. */
  tint: string;
  /** border color. */
  border: string;
  /** readable text color on the tint. */
  text: string;
}

export const KIND_STYLE: Record<StepKind, KindStyle> = {
  pink: {
    color: "oklch(0.62 0.19 5)",
    tint: "oklch(0.94 0.06 5)",
    border: "oklch(0.72 0.18 0)",
    text: "oklch(0.38 0.16 0)",
  },
  orange: {
    color: "oklch(0.66 0.15 60)",
    tint: "oklch(0.95 0.08 65)",
    border: "oklch(0.78 0.14 60)",
    text: "oklch(0.38 0.13 50)",
  },
  green: {
    color: "oklch(0.6 0.13 165)",
    tint: "oklch(0.93 0.09 170)",
    border: "oklch(0.72 0.13 165)",
    text: "oklch(0.32 0.11 165)",
  },
  blue: {
    color: "oklch(0.55 0.14 235)",
    tint: "oklch(0.92 0.08 225)",
    border: "oklch(0.65 0.13 230)",
    text: "oklch(0.3 0.13 235)",
  },
};

const FAMILY_KIND: Record<string, StepKind> = {
  FilterSeq: "pink",
  MaskPrimers: "pink",
  PairSeq: "orange",
  BuildConsensus: "orange",
  AlignSets: "orange",
  ClusterSets: "orange",
  AssembleSeq: "green",
  CollapseSeq: "blue",
  ParseHeaders: "blue",
  ConvertHeaders: "blue",
  UnifyHeaders: "blue",
  SplitSeq: "blue",
  EstimateError: "blue",
};

/** Color family for a step, inferred from its backend name (e.g. "FilterSeq.quality"). */
export function familyKind(stepName: string): StepKind {
  return FAMILY_KIND[stepName.split(".")[0]] ?? "blue";
}

export function stepStyle(stepName: string): KindStyle {
  return KIND_STYLE[familyKind(stepName)];
}
