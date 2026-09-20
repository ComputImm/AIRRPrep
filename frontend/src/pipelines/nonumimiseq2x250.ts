import type { StartJobRequest, PipelineStep } from "@/api/jobs";
import type { ProgressStepDescriptor } from "@/components/PipelineProgress";

interface NonUmi2x250Files {
  read1: any;
  read2: any;
  vprimer: any;
  cprimer: any;
}

interface NonUmi2x250Options {
  sessionId?: string;
  convertToFasta?: boolean;
}

/**
 * Non-UMI Illumina MiSeq 2×250 BCR mRNA.
 *
 * Mirrors the pRESTO reference script:
 *   AssemblePairs align → FilterSeq quality → MaskPrimers score (V FWD) →
 *   MaskPrimers score (C REV) → CollapseSeq → SplitSeq group →
 *   ParseHeaders table
 */
export function buildNonUmi2x250Payload(
  files: NonUmi2x250Files,
  options: NonUmi2x250Options = {},
): StartJobRequest {
  const steps: PipelineStep[] = [
    {
      id: "step1_assemble",
      name: "AssembleSeq.align",
      lanes: "paired",
      params: {
        // Script: -1 read2 -2 read1 → head=read2, tail=read1
        swap_head_tail: true,
        rc: "tail",
      },
    },
    {
      id: "step2_quality",
      name: "FilterSeq.quality",
      lanes: "paired",
      params: { min_qual: 20 },
    },
    {
      id: "step3_v_primers",
      name: "MaskPrimers.score",
      lanes: "paired",
      params: {
        primer_file: files.vprimer.id,
        start: 4,
        mode: "mask",
        primer_field: "VPRIMER",
      },
    },
    {
      id: "step4_c_primers",
      name: "MaskPrimers.score",
      lanes: "paired",
      params: {
        primer_file: files.cprimer.id,
        start: 4,
        mode: "cut",
        rev_primer: true,
        primer_field: "CPRIMER",
      },
    },
    {
      id: "step5_collapse_seq",
      name: "CollapseSeq.default",
      lanes: "paired",
      params: {
        max_missing: 20,
        inner: true,
        uniq_fields: ["CPRIMER"],
        copy_fields: ["VPRIMER"],
        copy_actions: ["set"],
      },
    },
    {
      id: "step6_group",
      name: "SplitSeq.group",
      lanes: "paired",
      params: {
        field: "DUPCOUNT",
        threshold: 2,
      },
    },
    {
      id: "step7_export_table",
      name: "ParseHeaders.table",
      lanes: "paired",
      params: {
        fields: ["ID", "DUPCOUNT", "CPRIMER", "VPRIMER"],
      },
    },
  ];

  return {
    session_id: options.sessionId ?? "",
    file_ids: [files.read1.id, files.read2.id],
    convert_to_fasta: options.convertToFasta ?? false,
    steps,
  };
}

/** Static labels + flowchart colors for the progress panel (file-independent). */
export const NONUMI_2X250_PROGRESS_STEPS: ProgressStepDescriptor[] = [
  { name: "AssembleSeq.align", label: "AssemblePairs align", color: "green" },
  { name: "FilterSeq.quality", label: "FilterSeq quality", color: "pink" },
  { name: "MaskPrimers.score", label: "MaskPrimers score", sub: "V-segment primer", color: "pink" },
  { name: "MaskPrimers.score", label: "MaskPrimers score", sub: "C-region primer (rev)", color: "pink" },
  { name: "CollapseSeq.default", label: "CollapseSeq", color: "blue" },
  { name: "SplitSeq.group", label: "SplitSeq group", color: "blue" },
  { name: "ParseHeaders.table", label: "ParseHeaders table", color: "blue" },
];
