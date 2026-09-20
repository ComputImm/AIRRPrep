import type { StartJobRequest, PipelineStep } from "@/api/jobs";
import type { ProgressStepDescriptor } from "@/components/PipelineProgress";

interface UploadedFile {
  id: string;
}

interface Race325275Files {
  read1: any ;
  read2: any;
  primerR1: any;
  primerR2: any;
  reference: any;
  cRegion: any;
}

interface Race325275Options {
    sessionId?: string;

  convertToFasta?: boolean;
}

export function buildRace325275Payload(
  files:Race325275Files,
  
  options: Race325275Options = {}
): StartJobRequest {

  const steps: PipelineStep[] = [
    
    {
      id: "step1_r1_quality",
      name: "FilterSeq.quality",
      lanes: "R1",
      params: {
        min_qual: 20
      },
    },

    {
      id: "step2_r2_quality",
      name: "FilterSeq.quality",
      lanes: "R2",
      params: {
        min_qual: 20
      },
    },

    {
      id: "step3_r1_primers",
      name: "MaskPrimers.score",
      lanes: "R1",
      params: {
        primer_file: files.primerR1.id,
        start: 0,
        mode: "cut",
      },
    },

    {
      id: "step4_r2_primers",
      name: "MaskPrimers.score",
      lanes: "R2",
      params: {
        primer_file: files.primerR2.id,
        start: 17,
        barcode: true,
        mode: "cut",
        max_error: 0.5,
      },
    },

    {
      id: "step5_pair",
      name: "PairSeq.default",
      lanes: "paired",
      params: {
        fields_2: ["BARCODE"],
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
      params: {
        coord_type: "presto",
      },
    },

    {
      id: "step9_assemble",
      name: "AssembleSeq.sequential",
      lanes: "paired",
      params: {
        ref_file: files.reference.id,
        rc: "tail",
        scan_reverse: true,
        swap_head_tail: true,
        head_fields: ["CONSCOUNT"],
        tail_fields: ["CONSCOUNT", "PRCONS"],
        aligner: "blastn",
      },
    },

    {
      id: "step10_c_region",
      name: "MaskPrimers.align",
      lanes: "paired",
      params: {
        primer_file: files.cRegion.id,
        max_len: 100,
        max_error: 0.3,
        mode: "tag",
        rev_primer: true,
        skip_rc: true,
        primer_field: "CREGION",
      },
    },

    {
      id: "step11_collapse_headers",
      name: "ParseHeaders.collapse",
      lanes: "paired",
      params: {
        fields: ["CONSCOUNT"],
        actions: ["min"],
      },
    },

    {
      id: "step12_collapse_seq",
      name: "CollapseSeq.default",
      lanes: "paired",
      params: {
        max_missing: 20,
        inner: true,
        uniq_fields: ["CREGION"],
        copy_fields: ["CONSCOUNT"],
        copy_actions: ["sum"],
      },
    },

    {
      id: "step13_group_consensus",
      name: "SplitSeq.group",
      lanes: "paired",
      params: {
        field: "CONSCOUNT",
        threshold: 2,
      },
    },

    {
      id: "step14_export_table",
      name: "ParseHeaders.table",
      lanes: "paired",
      params: {
        fields: [
          "ID",
          "CREGION",
          "CONSCOUNT",
          "DUPCOUNT",
        ],
      },
    },
  ];

  return {
    session_id: options.sessionId ?? "",
    file_ids: [
      files.read1.id,
      files.read2.id,
    ],

    convert_to_fasta: options.convertToFasta ?? false,

    steps,
  };
}

/** Static labels + flowchart colors for the progress panel (file-independent). */
export const RACE_325275_PROGRESS_STEPS: ProgressStepDescriptor[] = [
  { name: "FilterSeq.quality", label: "FilterSeq quality", sub: "Read 1", color: "pink" },
  { name: "FilterSeq.quality", label: "FilterSeq quality", sub: "Read 2", color: "pink" },
  { name: "MaskPrimers.score", label: "MaskPrimers score", sub: "C-region primer", color: "pink" },
  { name: "MaskPrimers.score", label: "MaskPrimers score", sub: "Template-switching", color: "pink" },
  { name: "PairSeq.default", label: "PairSeq", color: "orange" },
  { name: "BuildConsensus.default", label: "BuildConsensus", sub: "Read 1", color: "orange" },
  { name: "BuildConsensus.default", label: "BuildConsensus", sub: "Read 2", color: "orange" },
  { name: "PairSeq.default", label: "PairSeq", sub: "consensus", color: "green" },
  { name: "AssembleSeq.sequential", label: "AssemblePairs sequential", color: "green" },
  { name: "MaskPrimers.align", label: "MaskPrimers align", sub: "Internal IG C-region", color: "blue" },
  { name: "ParseHeaders.collapse", label: "ParseHeaders collapse", color: "blue" },
  { name: "CollapseSeq.default", label: "CollapseSeq", color: "blue" },
  { name: "SplitSeq.group", label: "SplitSeq group", color: "blue" },
  { name: "ParseHeaders.table", label: "ParseHeaders table", color: "blue" },
];