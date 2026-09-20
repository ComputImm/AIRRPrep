import type { StartJobRequest, PipelineStep } from "@/api/jobs";
import type { ProgressStepDescriptor } from "@/components/PipelineProgress";

interface Umi2x250Files {
  read1: any;
  read2: any;
  cprimer: any;
  vprimer: any;
}

interface Umi2x250Options {
  sessionId?: string;
  convertToFasta?: boolean;
}

/**
 * UMI-barcoded Illumina MiSeq 2×250 BCR mRNA.
 *
 * Mirrors the pRESTO reference script:
 *   FilterSeq quality (R1, R2) → MaskPrimers score (C, V) → PairSeq →
 *   BuildConsensus (R1, R2) → PairSeq → AssemblePairs align →
 *   ParseHeaders collapse → CollapseSeq → SplitSeq group →
 *   ParseHeaders table
 */
export function buildUmi2x250Payload(
  files: Umi2x250Files,
  options: Umi2x250Options = {},
): StartJobRequest {
  const steps: PipelineStep[] = [
    {
      id: "step1_r1_quality",
      name: "FilterSeq.quality",
      lanes: "R1",
      params: { min_qual: 20 ,missing_chars:'#'},
    },
    {
      id: "step2_r2_quality",
      name: "FilterSeq.quality",
      lanes: "R2",
      params: { min_qual: 20 ,missing_chars:'#'},
    },
    {
      id: "step3_r1_primers",
      name: "MaskPrimers.score",
      lanes: "R1",
      params: {
        primer_file: files.cprimer.id,
        start: 15,
        mode: "cut",
        barcode: true,
      },
    },
    {
      id: "step4_r2_primers",
      name: "MaskPrimers.score",
      lanes: "R2",
      params: {
        primer_file: files.vprimer.id,
        start: 0,
        mode: "mask",
      },
    },
    {
      id: "step5_pair",
      name: "PairSeq.default",
      lanes: "paired",
      params: {
        fields_1: ["BARCODE"],
        coord_type: "sra",
      },
    },
    {
      id: "step6_build_consensus_r1",
      name: "BuildConsensus.default",
      lanes: "R1",
      params: {
        barcode_field: "BARCODE",
        primer_field: "PRIMER",
        primer_freq: 0.6,
        max_error: 0.1,
        max_gap: 0.5,
      },
    },
    {
      id: "step7_build_consensus_r2",
      name: "BuildConsensus.default",
      lanes: "R2",
      params: {
        barcode_field: "BARCODE",
        max_error: 0.1,
        max_gap: 0.5,
      },
    },
    {
      id: "step8_pair_consensus",
      name: "PairSeq.default",
      lanes: "paired",
      params: { coord_type: "presto" },
    },
    {
      id: "step9_assemble",
      name: "AssembleSeq.align",
      lanes: "paired",
      params: {
        // Script: -1 R2 -2 R1 → head=R2, tail=R1
        swap_head_tail: true,
        rc: "tail",
        head_fields: ["CONSCOUNT"],
        tail_fields: ["CONSCOUNT", "PRCONS"],
      },
    },
    {
      id: "step10_collapse_headers",
      name: "ParseHeaders.collapse",
      lanes: "paired",
      params: {
        fields: ["CONSCOUNT"],
        actions: ["min"],
      },
    },
    {
      id: "step11_collapse_seq",
      name: "CollapseSeq.default",
      lanes: "paired",
      params: {
        max_missing: 20,
        inner: true,
        uniq_fields: ["PRCONS"],
        copy_fields: ["CONSCOUNT"],
        copy_actions: ["sum"],
      },
    },
    {
      id: "step12_group_consensus",
      name: "SplitSeq.group",
      lanes: "paired",
      params: {
        field: "CONSCOUNT",
        threshold: 2,
      },
    },
    {
      id: "step13_export_table",
      name: "ParseHeaders.table",
      lanes: "paired",
      params: {
        fields: ["ID", "PRCONS", "CONSCOUNT", "DUPCOUNT"],
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
export const UMI_2X250_PROGRESS_STEPS: ProgressStepDescriptor[] = [
  { name: "FilterSeq.quality", label: "FilterSeq quality", sub: "Read 1", color: "pink" },
  { name: "FilterSeq.quality", label: "FilterSeq quality", sub: "Read 2", color: "pink" },
  { name: "MaskPrimers.score", label: "MaskPrimers score", sub: "C-region primer", color: "pink" },
  { name: "MaskPrimers.score", label: "MaskPrimers score", sub: "V-segment primer", color: "pink" },
  { name: "PairSeq.default", label: "PairSeq", sub: "BARCODE", color: "orange" },
  { name: "BuildConsensus.default", label: "BuildConsensus", sub: "Read 1", color: "orange" },
  { name: "BuildConsensus.default", label: "BuildConsensus", sub: "Read 2", color: "orange" },
  { name: "PairSeq.default", label: "PairSeq", sub: "consensus", color: "orange" },
  { name: "AssembleSeq.align", label: "AssemblePairs align", color: "green" },
  { name: "ParseHeaders.collapse", label: "ParseHeaders collapse", color: "blue" },
  { name: "CollapseSeq.default", label: "CollapseSeq", color: "blue" },
  { name: "SplitSeq.group", label: "SplitSeq group", color: "blue" },
  { name: "ParseHeaders.table", label: "ParseHeaders table", color: "blue" },
];
