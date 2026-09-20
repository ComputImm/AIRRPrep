/**
 * Documentation catalog for the single-cell preprocessing module.
 *
 * Unlike bulk (a user-composed chain of pRESTO steps), a single-cell input
 * is format-detected: one adapter handles the whole file set. Each entry
 * here describes exactly what that adapter does to its specific input
 * files, mirroring the backend (presto-backend/app/singlecell/adapters/*)
 * and the FormatId union in src/api/singleCell.ts.
 */

import type { StepKind } from "@/lib/stepColors";
import type { FormatFlowSpec } from "@/components/SingleCellFormatFlow";
import type { SingleCellFormatId } from "@/api/singleCell";

export type SingleCellCategory = "cellranger" | "raw_reads" | "generic";

export interface SingleCellFormatDoc {
  id: SingleCellFormatId;
  title: string;
  category: SingleCellCategory;
  kind: StepKind;
  short: string;
  detail: string[];
  flow: FormatFlowSpec;
}

export const CATEGORY_INFO: Record<
  SingleCellCategory,
  { title: string; tagline: string; blurb: string }
> = {
  cellranger: {
    title: "Cell Ranger VDJ outputs",
    tagline: "Already-assembled contigs + a CSV/TSV of per-contig annotations",
    blurb:
      "Cell Ranger has already assembled and annotated each contig. The " +
      "adapter only re-reads the sequence and the handful of fields the " +
      "unified schema needs (barcode, read/UMI counts, cell/confidence " +
      "flags) — every V(D)J call Cell Ranger produced is deliberately left " +
      "out, so IMGT infers it fresh rather than trusting a vendor's call.",
  },
  raw_reads: {
    title: "Raw reads (require TRUST4 assembly)",
    tagline: "No contigs yet — sequences must be assembled first",
    blurb:
      "These inputs are raw reads, not assembled receptor sequences. TRUST4 " +
      "performs the assembly step first (external tool, invoked as a " +
      "subprocess); its output is then parsed exactly like a directly " +
      "uploaded TRUST4 result. The assembly runs as its own job stage, so a " +
      "long run shows progress rather than looking stalled.",
  },
  generic: {
    title: "Generic FASTA",
    tagline: "Any FASTA of receptor sequences, with a rule that recovers each cell barcode",
    blurb:
      "For sequences that don't come from Cell Ranger or TRUST4 at all — " +
      "a plain FASTA, plus either a small mapping file (per-sequence cell " +
      "barcode / UMI / read counts) or a header regex that extracts the " +
      "barcode. Without one of them the input is refused.",
  },
};

const CELLRANGER_STEPS = (variant: "all" | "filtered") => [
  {
    label: "Match contig_id ↔ barcode",
    sub: "joins each FASTA record to its row in the annotations file",
  },
  {
    label: "Strip annotation fields",
    sub:
      "drops chain, v_gene, d_gene, j_gene, c_gene, cdr3, cdr3_nt from the " +
      "analysis schema; kept verbatim in source_annotations.tsv",
  },
  {
    label: "Build unified record",
    sub:
      variant === "filtered"
        ? "already cell-associated + high-confidence"
        : "sequence_id, cell_id, umi_count, read_count, is_cell, high_confidence, productive",
  },
];

const UNIFIED_OUTPUT = [
  { label: "final.fasta" },
  { label: "metadata.tsv" },
  { label: "source_annotations.tsv" },
];

export const SINGLE_CELL_FORMAT_DOCS: SingleCellFormatDoc[] = [
  {
    id: "cellranger_vdj_all",
    title: "Cell Ranger VDJ — all contigs",
    category: "cellranger",
    kind: "blue",
    short: "Every assembled contig, including background/noise Cell Ranger found.",
    detail: [
      "Input: all_contig.fasta (one record per assembled contig) + " +
        "all_contig_annotations.csv (barcode, chain, V/D/J/C calls, CDR3, " +
        "read/UMI counts, is_cell / high_confidence flags, productive).",
      "The adapter reads the FASTA purely for its sequences, then walks the " +
        "CSV row by row and looks up each row's contig_id in that sequence " +
        "map. Only contig_id, barcode, umis, reads, is_cell, " +
        "high_confidence, and productive are ever read from the CSV.",
      "chain, v_gene, d_gene, j_gene, c_gene, cdr3, and cdr3_nt are never " +
        "copied into the unified record — these are Cell Ranger's own names " +
        "for exactly the V(D)J call the platform bans from preprocessing " +
        "output, so IMGT re-infers them from the raw sequence instead of " +
        "trusting Cell Ranger's call.",
      "\"All contigs\" includes background noise Cell Ranger did not " +
        "associate with a real cell — use the filtered variant if you only " +
        "want cell-associated, high-confidence contigs.",
    ],
    flow: {
      kind: "blue",
      inputs: [
        { label: "all_contig.fasta", sub: "one record per contig" },
        { label: "all_contig_annotations.csv", sub: "barcode, calls, counts" },
      ],
      steps: CELLRANGER_STEPS("all"),
      outputs: UNIFIED_OUTPUT,
    },
  },
  {
    id: "cellranger_vdj_filtered",
    title: "Cell Ranger VDJ — filtered contigs",
    category: "cellranger",
    kind: "blue",
    short: "Only cell-associated, high-confidence contigs — background already removed.",
    detail: [
      "Identical adapter logic to \"all contigs\" — same columns read, same " +
        "fields stripped — the only difference is which file Cell Ranger " +
        "itself produced: filtered_contig.fasta / " +
        "filtered_contig_annotations.csv already exclude background/noise " +
        "contigs, so every record that survives is cell-associated and " +
        "high-confidence.",
      "Prefer this variant unless you specifically need to inspect contigs " +
        "Cell Ranger did not assign to a real cell.",
    ],
    flow: {
      kind: "blue",
      inputs: [
        { label: "filtered_contig.fasta", sub: "cell-associated contigs only" },
        { label: "filtered_contig_annotations.csv", sub: "barcode, calls, counts" },
      ],
      steps: CELLRANGER_STEPS("filtered"),
      outputs: UNIFIED_OUTPUT,
    },
  },
  {
    id: "cellranger_airr_tsv",
    title: "Cell Ranger AIRR TSV",
    category: "cellranger",
    kind: "blue",
    short: "Cell Ranger's AIRR-schema rearrangement table — one row per contig.",
    detail: [
      "Input: a single AIRR Rearrangement TSV, one row per contig, already " +
        "in the community AIRR schema (sequence_id, sequence, cell_id, " +
        "productive, v_call, d_call, j_call, c_call, junction, junction_aa, " +
        "duplicate_count / consensus_count, ...).",
      "The adapter reads sequence_id, sequence, and cell_id directly, and " +
        "tries both common column-name variants for counts " +
        "(umi_count/duplicate_count, read_count/reads/consensus_count) " +
        "since these differ slightly across Cell Ranger versions.",
      "Every *_call, junction / junction_aa, *_alignment, and *_cigar " +
        "column is left out of the normalized record, so the sequences are " +
        "re-annotated downstream with one reference and procedure. The " +
        "sequence_id is kept unchanged, so those upstream annotations can " +
        "always be looked up again in the original file.",
      "The file has no high_confidence column, so that value is left empty " +
        "rather than assumed.",
    ],
    flow: {
      kind: "blue",
      inputs: [{ label: "AIRR rearrangement TSV", sub: "one row per contig" }],
      steps: [
        {
          label: "Read AIRR columns",
          sub: "sequence_id, sequence, cell_id, productive, counts",
        },
        {
          label: "Strip annotation fields",
          sub: "drops *_call, junction(_aa), *_alignment, *_cigar",
        },
        { label: "Build unified record" },
      ],
      outputs: UNIFIED_OUTPUT,
    },
  },
  {
    id: "trust4",
    title: "TRUST4 output",
    category: "raw_reads",
    kind: "orange",
    short:
      "Pre-computed TRUST4 assembly — uploaded directly, no assembly needed.",
    detail: [
      "Input: *_annot.fa (assembled contig sequences) + " +
        "*_barcode_report.tsv (TRUST4's per-cell report), both from one " +
        "TRUST4 run in barcode mode.",
      "The barcode report is what places each contig in a cell: every chain " +
        "field names a contig id, which is matched against the ids in " +
        "annot.fa rather than read from a fixed position, so a change in " +
        "TRUST4's column layout cannot silently misassign contigs.",
      "A contig whose barcode cannot be recovered is left out and counted — " +
        "it is never given its own id as a cell id, which would turn every " +
        "contig into a fake cell. A file pair in which no contig maps to a " +
        "barcode is refused.",
      "TRUST4 reports read support, not UMI counts, and makes no cell / " +
        "confidence calls, so umi_count, is_cell and high_confidence are left " +
        "empty.",
    ],
    flow: {
      kind: "orange",
      inputs: [
        {
          label: "*_annot.fa",
          sub: "assembled contig sequences",
        },
        {
          label: "*_barcode_report.tsv",
          sub: "cell barcode → contigs",
        },
      ],
      steps: [
        {
          label: "Match contig ids",
          sub: "barcode report chain fields ↔ annot.fa records",
        },
        {
          label: "Drop unplaced contigs",
          sub: "counted in the run report, never made into cells",
        },
        {
          label: "Build unified record",
        },
      ],
      outputs: UNIFIED_OUTPUT,
    },
  },
  {
    id: "fastq_10x",
    title: "Raw 10x FASTQ",
    category: "raw_reads",
    kind: "orange",
    short: "R1 + R2 FASTQ — TRUST4 assembles contigs first, then the TRUST4 adapter parses them.",
    detail: [
      "Input: R1.fastq.gz (cell barcode + UMI) + R2.fastq.gz (cDNA read), " +
        "the rawest single-cell input the platform accepts.",
      "TRUST4 is run as a subprocess to assemble V(D)J contigs per cell " +
        "from the raw reads; its two output files are then handed to the " +
        "exact same TRUST4 adapter used for a directly-uploaded TRUST4 " +
        "result, so there is only one place that ever parses TRUST4 output.",
      "R2 is passed to TRUST4 as the cDNA read, and R1 as the source of both " +
        "the cell barcode and the UMI — which slice of R1 is which comes " +
        "from the read-1 layout picked in the assembly settings (10x v2 = " +
        "16 bp barcode + 10 bp UMI, v3 = 16 + 12, or custom offsets).",
    ],
    flow: {
      kind: "orange",
      inputs: [
        { label: "R1.fastq.gz", sub: "cell barcode + UMI" },
        { label: "R2.fastq.gz", sub: "cDNA read" },
      ],
      steps: [
        { label: "Run TRUST4 assembly", sub: "external tool, invoked as a subprocess" },
        { label: "Parse TRUST4 output", sub: "same adapter as direct TRUST4 uploads" },
        { label: "Build unified record" },
      ],
      outputs: UNIFIED_OUTPUT,
      warning:
        "Needs TRUST4 and the reference set for the chosen species on the " +
        "server. The upload page reports exactly what's missing if it isn't " +
        "there, and refuses to start rather than queueing a job that would " +
        "fail.",
    },
  },
  {
    id: "bam_10x",
    title: "10x BAM",
    category: "raw_reads",
    kind: "orange",
    short:
      "Genome-aligned 10x BAM — TRUST4 assembles per-cell contigs from the CB/UB-tagged reads.",
    detail: [
      "Input: a genome-aligned 10x/Cell Ranger BAM (possorted_genome_bam.bam " +
        "or equivalent). TRUST4 reads the cell barcode from each read's CB tag " +
        "and the UMI from its UB tag.",
      "If TRUST4 cannot assemble the BAM using those tags, the run stops with " +
        "the reason. It is deliberately not retried without barcodes: a " +
        "barcode-free assembly completes and writes contigs, but they belong " +
        "to no cell, so it cannot be single-cell output.",
      "A BAM that is not aligned to the genome (such as Cell Ranger's " +
        "all_contig.bam) is refused up front; the \"Extract reads with samtools " +
        "first\" option handles it instead, copying CB/UB into TRUST4's FASTQ " +
        "path and counting how many reads carried them.",
      "The TRUST4 output is then parsed by the same adapter used for an " +
        "uploaded TRUST4 result.",
    ],
    flow: {
      kind: "orange",
      inputs: [
        {
          label: "possorted_genome_bam.bam",
          sub: "genome-aligned, with CB/UB tags",
        },
      ],
      steps: [
        {
          label: "Run TRUST4 in barcode mode",
          sub: "cell barcode from CB, UMI from UB",
        },
        {
          label: "Parse TRUST4 output",
          sub: "annot.fa + barcode report",
        },
        {
          label: "Build unified record",
        },
      ],
      outputs: UNIFIED_OUTPUT,
      warning:
        "Needs TRUST4 and the reference set for the chosen species on the " +
        "server. CB/UB tags are required: without them no read can be " +
        "assigned to a cell, and the run is refused rather than completed " +
        "without cell identity.",
    },
  },
  {
    id: "generic_fasta",
    title: "Generic FASTA",
    category: "generic",
    kind: "green",
    short: "Any FASTA of receptor sequences, with a required rule for recovering each cell barcode.",
    detail: [
      "Input: a plain FASTA of sequences, plus one way to recover each " +
        "sequence's cell barcode: a CSV/TSV mapping file (columns: " +
        "sequence_id, cell_id, umi_count, read_count), or a header regular " +
        "expression with one capture group.",
      "The mapping file is joined by exact sequence_id; the regex fills in " +
        "any sequence the file does not cover. If neither is given, or any " +
        "sequence is left without a barcode, the run is refused — each " +
        "sequence is never made its own \"cell\", because that would turn N " +
        "sequences into N fake cells.",
      "A bare FASTA carries no cell calling, so is_cell and high_confidence " +
        "are left empty; umi_count and read_count come only from the mapping file.",
    ],
    flow: {
      kind: "green",
      inputs: [
        { label: "sequences.fasta", sub: "any receptor sequences" },
        { label: "barcode_map.csv or header regex", sub: "sequence_id → cell_id (required)" },
      ],
      steps: [
        { label: "Recover cell barcode", sub: "mapping file, then header regex" },
        { label: "Refuse unresolved sequences", sub: "no barcode, no record — never a fake cell" },
      ],
      outputs: UNIFIED_OUTPUT,
    },
  },
];
