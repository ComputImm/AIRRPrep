/**
 * What to actually type into each step parameter.
 *
 * The backend's step metadata gives a name, a type and a default, which is
 * enough to draw a box but not enough to fill one in: "Comma,separated,values"
 * tells someone the syntax and nothing about the content, and a field like
 * `uniq_fields` is meaningless unless you already know pRESTO's annotation
 * names. So each parameter gets a realistic example -- the sort of value that
 * appears in a working AIRR-seq workflow -- shown as the input's placeholder,
 * plus a one-line hint under it.
 *
 * Parameters with a fixed set of accepted values are listed in PARAM_CHOICES
 * and render as a dropdown, so an invalid mode cannot be typed at all.
 *
 * Keys are "Step.subcommand:param" for a step-specific entry, falling back to
 * the bare "param" name shared across steps (barcode_field, max_error, ...).
 */

/** pRESTO annotation fields users most often reference, for the hints below. */
const COMMON_FIELDS = "BARCODE, UMI, PRIMER, CPRIMER, VPRIMER, CONSCOUNT, DUPCOUNT, CLUSTER, SAMPLE";

/** Parameters whose accepted values are a closed set -- rendered as a select. */
export const PARAM_CHOICES: Record<string, string[]> = {
  // MaskPrimers: what to do with the matched primer region.
  mode: ["mask", "cut", "trim", "tag"],
  "EstimateError.set:mode": ["freq", "qual"],

  // Which mate to reverse-complement before assembly.
  rc: ["tail", "head", "both", "none"],

  // How annotations from several reads are combined into one value.
  action: ["set", "first", "last", "min", "max", "sum", "cat"],
  actions: ["set", "first", "last", "min", "max", "sum", "cat"],
  copy_actions: ["set", "first", "last", "min", "max", "sum", "cat"],

  // Read-name format PairSeq/SplitSeq use to match mates.
  coord_type: ["presto", "illumina", "solexa", "sra", "454"],

  // External tools the server may shell out to. The open tools the
  // container image carries come first and are the defaults; USEARCH is
  // proprietary and is not distributed with AIRRPrep, so it only works on a
  // deployment whose operator installed a licensed copy (USEARCH_BIN).
  aligner: ["blastn", "usearch"],
  cluster_tool: ["vsearch", "cd-hit-est", "usearch"],

  offset_mode: ["pad", "cut"],
  pad_ends: ["none", "head", "tail"],
};

interface Guide {
  /** A realistic value, shown greyed out inside the empty input. */
  example: string;
  /** One line under the field saying what the value means. */
  hint: string;
}

/**
 * Step-specific entries first; they win over the shared ones below.
 */
const STEP_PARAMS: Record<string, Guide> = {
  // ── FilterSeq ────────────────────────────────────────────────────────────
  "FilterSeq.length:min_length": {
    example: "250",
    hint: "Reads shorter than this many bases are removed. 250 suits 2x250 MiSeq reads.",
  },
  "FilterSeq.quality:min_qual": {
    example: "20",
    hint: "Minimum mean Phred score. 20 keeps reads with under 1% average base-call error.",
  },
  "FilterSeq.missing:max_missing": {
    example: "10",
    hint: "Maximum number of ambiguous bases (N) allowed in a read.",
  },
  "FilterSeq.repeats:max_repeat": {
    example: "15",
    hint: "Longest homopolymer run allowed, e.g. 15 rejects AAAAAAAAAAAAAAAA.",
  },
  "FilterSeq.trimqual:min_qual": {
    example: "20",
    hint: "Trim the read end once the sliding window's mean quality drops below this.",
  },
  "FilterSeq.trimqual:window": {
    example: "10",
    hint: "Width in bases of the sliding quality window.",
  },
  "FilterSeq.maskqual:min_qual": {
    example: "20",
    hint: "Bases below this quality become N instead of the read being discarded.",
  },

  // ── MaskPrimers ──────────────────────────────────────────────────────────
  "MaskPrimers.align:max_len": {
    example: "50",
    hint: "How far into the read to search for the primer, in bases.",
  },
  "MaskPrimers.score:start": {
    example: "0",
    hint: "Base position where the primer starts. 0 is the very first base of the read.",
  },
  "MaskPrimers.extract:start": {
    example: "0",
    hint: "First base of the region to extract, counting from 0.",
  },
  "MaskPrimers.extract:length": {
    example: "17",
    hint: "How many bases to extract, e.g. 17 for a 17-nt UMI.",
  },

  // ── CollapseSeq ──────────────────────────────────────────────────────────
  "CollapseSeq.default:max_missing": {
    example: "20",
    hint: "Reads with more than this many N are not collapsed against others.",
  },
  "CollapseSeq.default:uniq_fields": {
    example: "CPRIMER",
    hint: "Only collapse reads that also agree on these fields. Blank means sequence only.",
  },
  "CollapseSeq.default:copy_fields": {
    example: "VPRIMER, CONSCOUNT",
    hint: "Fields carried onto the surviving read, combined using Copy actions.",
  },
  "CollapseSeq.default:copy_actions": {
    example: "set, sum",
    hint: "One action per copied field, in the same order (e.g. sum for counts).",
  },
  "CollapseSeq.default:max_field": {
    example: "CONSCOUNT",
    hint: "Keep the duplicate with the highest value in this field as the representative.",
  },
  "CollapseSeq.default:min_field": {
    example: "ERROR",
    hint: "Keep the duplicate with the lowest value in this field as the representative.",
  },

  // ── BuildConsensus ───────────────────────────────────────────────────────
  "BuildConsensus.default:min_count": {
    example: "1",
    hint: "Barcode groups with fewer reads than this produce no consensus.",
  },
  "BuildConsensus.default:min_freq": {
    example: "0.6",
    hint: "A base needs this share of the group's reads to be called. 0.6 = 60%.",
  },
  "BuildConsensus.default:min_qual": {
    example: "0",
    hint: "Consensus bases below this quality are called as N.",
  },
  "BuildConsensus.default:primer_freq": {
    example: "0.6",
    hint: "Share of reads that must agree on the primer before the group is kept.",
  },
  "BuildConsensus.default:max_error": {
    example: "0.1",
    hint: "Discard a group whose reads differ from their consensus by more than this.",
  },
  "BuildConsensus.default:max_gap": {
    example: "0.5",
    hint: "Positions that are a gap in more than this share of reads are dropped.",
  },
  "BuildConsensus.default:max_diversity": {
    example: "0.1",
    hint: "Discard barcode groups more diverse than this -- likely more than one molecule.",
  },

  // ── PairSeq ──────────────────────────────────────────────────────────────
  "PairSeq.default:fields_1": {
    example: "BARCODE",
    hint: "Fields copied from Read 1 onto its Read 2 mate.",
  },
  "PairSeq.default:fields_2": {
    example: "BARCODE",
    hint: "Fields copied from Read 2 onto its Read 1 mate.",
  },

  // ── AssembleSeq ──────────────────────────────────────────────────────────
  "AssembleSeq.align:alpha": {
    example: "1e-5",
    hint: "Significance cutoff for accepting an overlap. Lower is stricter.",
  },
  "AssembleSeq.align:max_error": {
    example: "0.3",
    hint: "Highest mismatch rate tolerated inside the overlap.",
  },
  "AssembleSeq.align:min_len": {
    example: "8",
    hint: "Shortest overlap, in bases, that may be called an assembly.",
  },
  "AssembleSeq.align:max_len": {
    example: "1000",
    hint: "Longest overlap to test, in bases.",
  },
  "AssembleSeq.join:gap": {
    example: "0",
    hint: "Number of N bases inserted between the two reads when joining them.",
  },
  "AssembleSeq.reference:min_ident": {
    example: "0.5",
    hint: "Minimum identity to the reference for a hit to count. 0.5 = 50%.",
  },
  "AssembleSeq.reference:evalue": {
    example: "1e-5",
    hint: "Maximum alignment E-value against the reference.",
  },
  "AssembleSeq.reference:max_hits": {
    example: "100",
    hint: "How many reference hits per read to consider.",
  },
  "AssembleSeq.align:head_fields": {
    example: "BARCODE",
    hint: "Annotations copied from Read 1 onto the assembled sequence.",
  },
  "AssembleSeq.align:tail_fields": {
    example: "PRIMER",
    hint: "Annotations copied from Read 2 onto the assembled sequence.",
  },

  // ── ParseHeaders ─────────────────────────────────────────────────────────
  "ParseHeaders.add:fields": {
    example: "SAMPLE, DONOR",
    hint: "New annotation names to add to every header.",
  },
  "ParseHeaders.add:values": {
    example: "HD13M, donor_1",
    hint: "One value per field above, in the same order. Values are stored as typed.",
  },
  "ParseHeaders.collapse:fields": {
    example: "CONSCOUNT",
    hint: "Fields whose repeated values should be reduced to one.",
  },
  "ParseHeaders.collapse:actions": {
    example: "sum",
    hint: "How to combine each field's values -- one action per field, same order.",
  },
  "ParseHeaders.copy:fields": {
    example: "BARCODE",
    hint: "Existing fields to copy from.",
  },
  "ParseHeaders.copy:names": {
    example: "UMI",
    hint: "New name for each copied field, in the same order.",
  },
  "ParseHeaders.delete:fields": {
    example: "PRIMER, CLUSTER",
    hint: "Annotations to remove from every header.",
  },
  "ParseHeaders.expand:fields": {
    example: "PRIMER",
    hint: "Field holding several values that should become separate fields.",
  },
  "ParseHeaders.expand:separator": {
    example: ",",
    hint: "Character that separates the values inside that field.",
  },
  "ParseHeaders.merge:fields": {
    example: "CPRIMER, VPRIMER",
    hint: "Fields to combine into one.",
  },
  "ParseHeaders.merge:name": {
    example: "PRIMERS",
    hint: "Name of the combined field.",
  },
  "ParseHeaders.rename:fields": {
    example: "BARCODE",
    hint: "Existing field names to rename.",
  },
  "ParseHeaders.rename:names": {
    example: "UMI",
    hint: "New name for each, in the same order.",
  },
  "ParseHeaders.table:fields": {
    example: "DUPCOUNT, CPRIMER, VPRIMER",
    hint: "Columns to export. The sequence ID is always included as the first column.",
  },

  // ── SplitSeq ─────────────────────────────────────────────────────────────
  "SplitSeq.count:max_count": {
    example: "4000",
    hint: "Reads per output file. 20,000 reads at 4,000 gives 5 files.",
  },
  "SplitSeq.group:field": {
    example: "DUPCOUNT",
    hint: "Annotation to split on -- one file per distinct value, unless a threshold is set.",
  },
  "SplitSeq.group:threshold": {
    example: "2",
    hint: "Split numerically into under / at-least instead. The at-least part continues.",
  },
  "SplitSeq.sample:max_count": {
    example: "10000",
    hint: "How many reads to sample. Several numbers give one file per sample size.",
  },
  "SplitSeq.sample:field": {
    example: "BARCODE",
    hint: "Sample within each group of this field instead of across the whole file.",
  },
  "SplitSeq.sample:values": {
    example: "BC1, BC2",
    hint: "Restrict sampling to these values of the field above.",
  },
  "SplitSeq.samplepair:max_count": {
    example: "10000",
    hint: "Read pairs to sample. Several numbers give one R1/R2 pair per sample size.",
  },
  "SplitSeq.sort:field": {
    example: "CONSCOUNT",
    hint: "Annotation to sort the reads by.",
  },
  "SplitSeq.sort:max_count": {
    example: "10000",
    hint: "Optional. Also split the sorted reads into files of this size.",
  },
  "SplitSeq.select:field": {
    example: "SAMPLE",
    hint: "Annotation to filter on.",
  },
  "SplitSeq.select:value_list": {
    example: "HD13M, HD09N",
    hint: "Keep only reads whose field matches one of these values.",
  },

  // ── AlignSets / ClusterSets ──────────────────────────────────────────────
  "ClusterSets.all:ident": {
    example: "0.9",
    hint: "Sequence identity needed to join a cluster. 0.9 = 90%.",
  },
  "ClusterSets.all:seq_start": {
    example: "0",
    hint: "First base of the region used for clustering.",
  },
  "ClusterSets.all:seq_end": {
    example: "300",
    hint: "Last base of the region used for clustering. Blank means to the end.",
  },
  "ClusterSets.set:set_field": {
    example: "BARCODE",
    hint: "Cluster within the groups defined by this field.",
  },

  // ── EstimateError / UnifyHeaders ─────────────────────────────────────────
  "EstimateError.set:min_count": {
    example: "20",
    hint: "Barcode groups smaller than this are skipped when estimating error.",
  },
  "UnifyHeaders.consensus:unify_field": {
    example: "SAMPLE",
    hint: "Field forced to one agreed value across each barcode group.",
  },
  "UnifyHeaders.delete:unify_field": {
    example: "SAMPLE",
    hint: "Groups whose reads disagree on this field are deleted.",
  },
};

/** Shared across steps -- used when no step-specific entry matches. */
const SHARED_PARAMS: Record<string, Guide> = {
  cluster_tool: {
    example: "vsearch",
    hint:
      "Clustering program. vsearch and cd-hit-est ship with AIRRPrep; " +
      "USEARCH is proprietary and is not distributed, so it runs only where " +
      "the operator installed a licensed copy.",
  },
  aligner: {
    example: "blastn",
    hint:
      "Aligner used to place reads against the reference. blastn ships " +
      "with AIRRPrep; usearch (ublast) is proprietary and is not " +
      "distributed.",
  },
  barcode_field: {
    example: "BARCODE",
    hint: "Header annotation holding the barcode / UMI sequence.",
  },
  primer_field: {
    example: "PRIMER",
    hint: "Header annotation holding the matched primer name.",
  },
  set_field: {
    example: "BARCODE",
    hint: "Header annotation that groups reads from the same molecule.",
  },
  cluster_field: {
    example: "CLUSTER",
    hint: "Header annotation the cluster id is written to.",
  },
  cluster_prefix: {
    example: "C",
    hint: "Optional text placed before each cluster id, e.g. C1, C2.",
  },
  field: { example: "BARCODE", hint: `Header annotation to use, e.g. ${COMMON_FIELDS}.` },
  fields: { example: "BARCODE, PRIMER", hint: `Header annotations, e.g. ${COMMON_FIELDS}.` },
  names: { example: "UMI", hint: "New name for each field above, in the same order." },
  values: { example: "HD13M", hint: "One value per field above, in the same order." },
  max_error: {
    example: "0.2",
    hint: "Highest error rate accepted. 0.2 means up to 20% mismatching bases.",
  },
  max_missing: { example: "10", hint: "Maximum number of ambiguous bases (N) allowed." },
  missing_chars: {
    example: "Nn.-",
    hint: "Characters counted as unknown bases or gaps.",
  },
  min_qual: { example: "20", hint: "Minimum Phred quality score." },
  min_freq: { example: "0.6", hint: "Minimum share of reads that must agree. 0.6 = 60%." },
  min_len: { example: "8", hint: "Minimum length in bases." },
  max_len: { example: "1000", hint: "Maximum length in bases." },
  max_count: { example: "10000", hint: "Maximum number of reads." },
  ident: { example: "0.9", hint: "Sequence identity threshold. 0.9 = 90%." },
  length_ratio: {
    example: "0.0",
    hint: "Minimum length ratio between clustered sequences. 0 disables the check.",
  },
  cluster_memory: { example: "3000", hint: "Memory the clustering tool may use, in MB." },
  barcode_length: {
    example: "17",
    hint: "Length of the barcode in bases. Blank uses the primer file's own length.",
  },
  threshold: { example: "2", hint: "Numeric cut-off applied to the field's value." },
  separator: { example: ",", hint: "Character separating values inside a field." },
  name: { example: "PRIMERS", hint: "Name of the resulting annotation field." },
  value_list: { example: "HD13M, HD09N", hint: "Values to match against the field." },
  window: { example: "10", hint: "Width of the sliding window, in bases." },
  alpha: { example: "1e-5", hint: "Significance cut-off. Lower is stricter." },
  evalue: { example: "1e-5", hint: "Maximum alignment E-value." },
  gap: { example: "0", hint: "Number of N bases inserted between the joined reads." },
  start: { example: "0", hint: "Base position to start at, counting from 0." },
  length: { example: "17", hint: "Number of bases." },
  min_count: { example: "1", hint: "Minimum number of reads required." },
  min_ident: { example: "0.5", hint: "Minimum identity. 0.5 = 50%." },
  max_hits: { example: "100", hint: "Maximum number of alignment hits to consider." },
  max_repeat: { example: "15", hint: "Longest run of one repeated base allowed." },
  max_diversity: { example: "0.1", hint: "Maximum diversity allowed within a group." },
  max_gap: { example: "0.5", hint: "Maximum share of reads that may have a gap at a position." },
  seq_start: { example: "0", hint: "First base of the region to use." },
  seq_end: { example: "300", hint: "Last base of the region to use. Blank means to the end." },
  unify_field: { example: "SAMPLE", hint: "Field to unify across each group." },
};

/** Hints for the few boolean switches whose meaning is not obvious. */
const BOOLEAN_HINTS: Record<string, string> = {
  inner: "Ignore leading and trailing gaps, measuring only the sequence between them.",
  rev_primer: "The primer sits at the end of the read rather than the start.",
  skip_rc: "Do not also search the reverse complement of the read.",
  barcode: "Capture the bases before the primer as a barcode / UMI annotation.",
  negate: "Invert the selection: remove the matching reads instead of keeping them.",
  numeric: "Sort the field as numbers rather than as text (2 before 10).",
  reverse: "Build the table from the 3-prime end instead of the 5-prime end.",
  delete: "Remove the original fields once they have been merged.",
  fill: "Fill any gap between the reads with the reference sequence.",
  scan_reverse: "Keep scanning past the best overlap for a longer one.",
  simple: "Keep only the allele name from the IMGT header.",
  calc_div: "Also calculate the diversity of each aligned set (slower).",
  include_missing: "Count ambiguous bases as part of a repeat run.",
  keep_missing: "Keep reads with too many ambiguous bases instead of discarding them.",
};

const key = (step: string, param: string) => `${step}:${param}`;

/** Fixed set of accepted values for a parameter, or undefined if free-form. */
export function paramChoices(step: string, param: string): string[] | undefined {
  return PARAM_CHOICES[key(step, param)] ?? PARAM_CHOICES[param];
}

/**
 * Example value and one-line hint for a parameter.
 *
 * `kind` is the widget the field renders as; it only decides the fallback used
 * when the parameter is not in either table, so a new pRESTO parameter still
 * gets something more useful than an empty box.
 */
export function paramGuide(
  step: string,
  param: string,
  kind: "number" | "boolean" | "array" | "text" | "file",
  fallbackDefault?: unknown,
): { example: string; hint: string } {
  const found = STEP_PARAMS[key(step, param)] ?? SHARED_PARAMS[param];
  if (found) return found;

  if (kind === "boolean") {
    return { example: "", hint: BOOLEAN_HINTS[param] ?? "" };
  }

  // Nothing curated: the backend's default is still a real, valid value.
  const asExample =
    fallbackDefault == null || fallbackDefault === ""
      ? ""
      : Array.isArray(fallbackDefault)
        ? fallbackDefault.join(", ")
        : String(fallbackDefault);

  if (kind === "array") {
    return {
      example: asExample || "BARCODE, PRIMER",
      hint: `Several values, separated by commas. Common fields: ${COMMON_FIELDS}.`,
    };
  }
  if (kind === "number") {
    return { example: asExample || "0", hint: "" };
  }
  return { example: asExample, hint: "" };
}
