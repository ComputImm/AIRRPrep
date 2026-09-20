/**
 * The seven single-cell workflows, one card + one page each.
 *
 * This is the single-cell counterpart of bulk's data-type cards: the user
 * picks the workflow up front, so the format is fixed and each input gets a
 * named slot instead of one shared "drop everything here" uploader.
 *
 * `role` on each input MUST match the role name in that format's FormatSpec
 * (presto-backend/app/singlecell/detector.py::FORMAT_SPECS) — it is sent back
 * as `role_file_ids` so the backend uses the user's own slot assignment
 * rather than re-guessing roles from filenames.
 *
 * The flow diagram for each workflow is reused from SINGLE_CELL_FORMAT_DOCS
 * so the card, the page, and /documentation/single-cell can never drift.
 */

import type { StepKind } from "@/lib/stepColors";
import type { SingleCellFormatId } from "@/api/singleCell";
import { SINGLE_CELL_FORMAT_DOCS } from "@/lib/singleCellDocs";
import type { FormatFlowSpec } from "@/components/SingleCellFormatFlow";

export interface WorkflowInput {
  /** Backend role name — see the note above. */
  role: string;
  label: string;
  helper: string;
  accept: string;
  required: boolean;
}

export interface SingleCellWorkflow {
  id: SingleCellFormatId;
  title: string;
  subtitle: string;
  kind: StepKind;
  inputs: WorkflowInput[];
  /** True for the formats whose adapter shells out to TRUST4 first. */
  needsTrust4: boolean;
  /**
   * True where the source can supply Cell Ranger's `productive` call. It is
   * annotation-derived, so it is only ever carried through on explicit
   * request — Cell Ranger is the only source that has it at all.
   */
  supportsProductive?: boolean;
  /**
   * True where the user must declare how the cell barcode is recovered
   * (mapping file or header regex) before the run can start.
   */
  needsBarcodeRule?: boolean;
  flow: FormatFlowSpec;
}

const FASTA_ACCEPT = ".fasta,.fa,.fas,.gz";
const FASTQ_ACCEPT = ".fastq,.fq,.gz";
const TABLE_ACCEPT = ".csv,.tsv,.gz";

function flowOf(id: SingleCellFormatId): FormatFlowSpec {
  const doc = SINGLE_CELL_FORMAT_DOCS.find((d) => d.id === id);
  if (!doc) throw new Error(`No documentation entry for format ${id}`);
  return doc.flow;
}

export const SINGLE_CELL_WORKFLOWS: SingleCellWorkflow[] = [
  {
    id: "cellranger_vdj_all",
    title: "Cell Ranger VDJ — all contigs",
    subtitle:
      "Every contig Cell Ranger assembled, including the ones it did not call as cells.",
    kind: "blue",
    needsTrust4: false,
    supportsProductive: true,
    inputs: [
      {
        role: "contig_fasta",
        label: "Contig FASTA",
        helper: "all_contig.fasta — the assembled contig sequences",
        accept: FASTA_ACCEPT,
        required: true,
      },
      {
        role: "contig_annotations",
        label: "Contig annotations",
        helper: "all_contig_annotations.csv — barcode, UMI/read counts, flags",
        accept: TABLE_ACCEPT,
        required: true,
      },
    ],
    flow: flowOf("cellranger_vdj_all"),
  },
  {
    id: "cellranger_vdj_filtered",
    title: "Cell Ranger VDJ — filtered contigs",
    subtitle:
      "Only the high-confidence contigs from cells Cell Ranger kept after filtering.",
    kind: "blue",
    needsTrust4: false,
    supportsProductive: true,
    inputs: [
      {
        role: "contig_fasta",
        label: "Contig FASTA",
        helper: "filtered_contig.fasta — the assembled contig sequences",
        accept: FASTA_ACCEPT,
        required: true,
      },
      {
        role: "contig_annotations",
        label: "Contig annotations",
        helper:
          "filtered_contig_annotations.csv — barcode, UMI/read counts, flags",
        accept: TABLE_ACCEPT,
        required: true,
      },
    ],
    flow: flowOf("cellranger_vdj_filtered"),
  },
  {
    id: "cellranger_airr_tsv",
    title: "Cell Ranger AIRR TSV",
    subtitle:
      "Cell Ranger's AIRR rearrangement table — sequence and metadata in one file.",
    kind: "blue",
    needsTrust4: false,
    supportsProductive: true,
    inputs: [
      {
        role: "airr_tsv",
        label: "AIRR rearrangement TSV",
        helper: "airr_rearrangement.tsv — one row per rearrangement",
        accept: TABLE_ACCEPT,
        required: true,
      },
    ],
    flow: flowOf("cellranger_airr_tsv"),
  },
  {
    id: "trust4",
    title: "TRUST4 output",
    subtitle:
      "An assembly you already ran elsewhere — uploaded directly, no assembly on this server.",
    kind: "orange",
    needsTrust4: false,
    inputs: [
      {
        role: "annot_fasta",
        label: "Annotated FASTA",
        helper: "*_annot.fa — the assembled, annotated contigs",
        accept: FASTA_ACCEPT,
        required: true,
      },
      {
        role: "barcode_report",
        label: "Barcode report",
        helper: "*_barcode_report.tsv — maps each contig to its cell barcode",
        accept: TABLE_ACCEPT,
        required: true,
      },
    ],
    flow: flowOf("trust4"),
  },
  {
    id: "fastq_10x",
    title: "Raw 10x FASTQ",
    subtitle:
      "Unassembled paired reads. TRUST4 assembles per-cell contigs on the server first.",
    kind: "orange",
    needsTrust4: true,
    inputs: [
      {
        role: "r1_fastq",
        label: "Read 1",
        helper: "R1 FASTQ — carries the cell barcode and UMI",
        accept: FASTQ_ACCEPT,
        required: true,
      },
      {
        role: "r2_fastq",
        label: "Read 2",
        helper: "R2 FASTQ — carries the cDNA read",
        accept: FASTQ_ACCEPT,
        required: true,
      },
    ],
    flow: flowOf("fastq_10x"),
  },
  {
    id: "bam_10x",
    title: "10x BAM",
    subtitle:
      "A genome-aligned 10x BAM with CB/UB tags. TRUST4 assembles per-cell contigs on the server first.",
    kind: "orange",
    needsTrust4: true,
    inputs: [
      {
        role: "bam",
        label: "BAM file",
        helper:
          "possorted_genome_bam.bam or equivalent — cell barcodes and UMIs are read from the CB/UB tags",
        accept: ".bam",
        required: true,
      },
    ],
    flow: flowOf("bam_10x"),
  },
  {
    id: "generic_fasta",
    title: "Generic FASTA",
    subtitle:
      "Any FASTA of receptor sequences. You must declare how the cell barcode is recovered.",
    kind: "green",
    needsTrust4: false,
    needsBarcodeRule: true,
    inputs: [
      {
        role: "fasta",
        label: "Sequence FASTA",
        helper: "Any FASTA of receptor sequences",
        accept: FASTA_ACCEPT,
        required: true,
      },
      {
        role: "barcode_map",
        label: "Barcode mapping",
        helper:
          "CSV/TSV: sequence_id, cell_id, umi_count, read_count — or use a header regex instead",
        accept: TABLE_ACCEPT,
        required: false,
      },
    ],
    flow: flowOf("generic_fasta"),
  },
];

export function getSingleCellWorkflow(
  id: string,
): SingleCellWorkflow | undefined {
  return SINGLE_CELL_WORKFLOWS.find((w) => w.id === id);
}
