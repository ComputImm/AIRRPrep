/**
 * Documentation catalog for the pRESTO pipeline steps.
 *
 * Steps are split into two groups by *what they do to a record*:
 *
 *  - "transform" — the step CHANGES the content of records: it edits the
 *    sequence bases (trim/mask/assemble/consensus) or edits the header
 *    annotations (add/remove/rename fields, copy between mates, …).
 *
 *  - "filter" — the step does NOT change any record. It only decides which
 *    whole records survive, or how they are split / ordered. The output file
 *    is different, but every surviving read is byte-for-byte identical to its
 *    input.
 *
 * Each entry carries a `visual` key that selects the before→after illustration
 * drawn by <StepVisual/>. The text mirrors the backend STEP_CONTRACTS
 * descriptions (contracts.py) so the docs stay accurate.
 */

import type { VisualKind } from "@/components/StepVisual";

export type StepCategory = "transform" | "filter";

export interface StepDoc {
  /** Backend step name, e.g. "FilterSeq.length". */
  name: string;
  /** Human-friendly title. */
  title: string;
  /** Backend family, e.g. "FilterSeq" (drives the color). */
  family: string;
  /** One-line summary shown on the card. */
  short: string;
  category: StepCategory;
  visual: VisualKind;
  /** Detailed explanation paragraphs (shown in the dialog). */
  detail: string[];
  /** Short "what actually changes" line. */
  changes: string;
  /** For header-edit visuals: example header before/after. */
  headerBefore?: string;
  headerAfter?: string;
}

export const CATEGORY_INFO: Record<
  StepCategory,
  { title: string; tagline: string; blurb: string }
> = {
  transform: {
    title: "Steps that change the reads",
    tagline: "Sequence or annotation is modified",
    blurb:
      "These components rewrite the records themselves — they shorten or mask " +
      "the sequence, merge reads together, or add / remove / edit the " +
      "annotation fields in the header. The read that comes out is different " +
      "from the read that went in.",
  },
  filter: {
    title: "Steps that only filter or reorganize",
    tagline: "Records are kept, dropped, split or sorted — never edited",
    blurb:
      "These components never touch the content of a read. They only decide " +
      "which whole records pass, or how the file is split / sampled / sorted. " +
      "The file changes, but every surviving read is identical to its input.",
  },
};

export const STEP_DOCS: StepDoc[] = [
  // ───────────────────────── transform group ─────────────────────────
  {
    name: "FilterSeq.trimqual",
    title: "Trim by quality",
    family: "FilterSeq",
    short: "Cuts low-quality bases off the ends of each read.",
    category: "transform",
    visual: "trim",
    changes: "The read gets shorter — low-quality ends are removed.",
    detail: [
      "Slides a window along each read and trims bases from the ends once the " +
        "windowed quality score drops below the cutoff.",
      "The read survives, but its sequence is now shorter. This is why it is a " +
        "transforming step and not a pure filter: the bases themselves change.",
    ],
  },
  {
    name: "FilterSeq.maskqual",
    title: "Mask by quality",
    family: "FilterSeq",
    short: "Replaces individual low-quality bases with N (keeps the read).",
    category: "transform",
    visual: "mask",
    changes: "Length stays the same, but weak bases become N.",
    detail: [
      "Instead of discarding a read, each base below the quality threshold is " +
        "replaced with an ambiguous N.",
      "The read keeps its length and position, but its content is edited, so " +
        "it belongs to the transforming group.",
    ],
  },
  {
    name: "MaskPrimers.align",
    title: "Mask primers (alignment)",
    family: "MaskPrimers",
    short: "Finds primers by local alignment, then masks/cuts and annotates them.",
    category: "transform",
    visual: "primer",
    changes: "Primer region is masked or cut, and a PRIMER annotation is added.",
    detail: [
      "Aligns each read against a primer FASTA to locate the primer even when " +
        "its position varies, then masks (turns to N) or cuts that region.",
      "It also writes the matched primer name into the header as a PRIMER " +
        "annotation — so both the sequence and the header change.",
    ],
  },
  {
    name: "MaskPrimers.score",
    title: "Mask primers (scoring)",
    family: "MaskPrimers",
    short: "Matches primers at a fixed start position, annotates PRIMER / barcode.",
    category: "transform",
    visual: "primer",
    changes: "Fixed-position primer is masked and a PRIMER annotation is added.",
    detail: [
      "Scores each read against a primer FASTA assuming the primer starts at a " +
        "fixed offset, then masks the primer region.",
      "Adds the matched primer name (and optionally a barcode/UMI) to the " +
        "header, editing both sequence and annotation.",
    ],
  },
  {
    name: "MaskPrimers.extract",
    title: "Extract region",
    family: "MaskPrimers",
    short: "Pulls a fixed-position region out as an annotation (no primer file).",
    category: "transform",
    visual: "primer",
    changes: "A fixed region is captured into an annotation and masked.",
    detail: [
      "Takes a fixed-position slice of every read and stores it as an " +
        "annotation, without needing a primer file.",
      "The captured region is masked in the sequence and recorded in the " +
        "header, so the record content changes.",
    ],
  },
  {
    name: "CollapseSeq.default",
    title: "Collapse duplicates",
    family: "CollapseSeq",
    short: "Merges identical reads into one unique record with a DUPCOUNT.",
    category: "transform",
    visual: "collapse",
    changes: "Identical reads merge into one record carrying a duplicate count.",
    detail: [
      "Finds reads with identical sequences and collapses them into a single " + "unique record.",
      "The kept record gains a DUPCOUNT annotation recording how many copies " +
        "were merged — the set of records and the header both change.",
    ],
  },
  {
    name: "BuildConsensus.default",
    title: "Build consensus",
    family: "BuildConsensus",
    short: "Computes one consensus read per UMI/barcode group to fix errors.",
    category: "transform",
    visual: "consensus",
    changes: "Each barcode group becomes one new, error-corrected sequence.",
    detail: [
      "Groups reads by their UMI / barcode and builds a single consensus " +
        "sequence per group, correcting random sequencing errors.",
      "The consensus is a newly computed sequence that did not exist in the " +
        "input, which makes this a transforming step.",
    ],
  },
  {
    name: "PairSeq.default",
    title: "Pair mates",
    family: "PairSeq",
    short: "Synchronizes R1/R2 files and copies annotations between mates.",
    category: "transform",
    visual: "pair",
    changes: "Unpaired reads are dropped and annotations are copied across mates.",
    detail: [
      "Lines up the two paired-end files so that R1 and R2 mates correspond, " +
        "dropping reads that have no mate.",
      "It also copies annotation fields from one read onto its mate — because " +
        "it edits the headers, it lives in the transforming group even though " +
        "the bases are untouched.",
    ],
  },
  {
    name: "AssembleSeq.align",
    title: "Assemble (de novo overlap)",
    family: "AssembleSeq",
    short: "Joins R1+R2 into one read using a significance-tested overlap.",
    category: "transform",
    visual: "assemble",
    changes: "Two mates become one longer assembled sequence.",
    detail: [
      "Searches for a statistically significant overlap between the R1 and R2 " +
        "mates and stitches them into a single read.",
      "Two records collapse into one new, longer sequence — a clear content " + "change.",
    ],
  },
  {
    name: "AssembleSeq.join",
    title: "Assemble (concatenate)",
    family: "AssembleSeq",
    short: "Concatenates R1 and R2 end-to-end without searching for overlap.",
    category: "transform",
    visual: "assemble",
    changes: "Mates are glued end-to-end (optionally with a gap) into one read.",
    detail: [
      "Joins the two mates directly, optionally inserting a gap, without " +
        "looking for an overlap.",
      "The output is a single concatenated sequence built from the two inputs.",
    ],
  },
  {
    name: "AssembleSeq.reference",
    title: "Assemble (reference-guided)",
    family: "AssembleSeq",
    short: "Assembles mates guided by alignment to a reference sequence.",
    category: "transform",
    visual: "assemble",
    changes: "Mates are merged into one read using a reference for guidance.",
    detail: [
      "Uses alignment to a reference FASTA to place the two mates and merge " +
        "them into one sequence.",
      "Helpful when the de novo overlap is too short to call confidently.",
    ],
  },
  {
    name: "AssembleSeq.sequential",
    title: "Assemble (sequential)",
    family: "AssembleSeq",
    short: "Tries de novo overlap first, then falls back to reference-guided.",
    category: "transform",
    visual: "assemble",
    changes: "Mates become one read via overlap, or reference fallback.",
    detail: [
      "First attempts a de novo overlap assembly; for pairs that fail it falls " +
        "back to reference-guided assembly.",
      "Either way two mates are merged into a single sequence.",
    ],
  },
  {
    name: "ParseHeaders.add",
    title: "Add annotation field",
    family: "ParseHeaders",
    short: "Adds a new annotation field with a fixed value to every header.",
    category: "transform",
    visual: "header",
    changes: "A new field/value is appended to the header; sequence untouched.",
    headerBefore: "@SEQ1",
    headerAfter: "@SEQ1|SAMPLE=blood",
    detail: [
      "Writes a brand-new annotation field (with a constant value) into every " +
        "sequence header.",
      "The DNA is untouched, but the header is edited — so this is a " +
        "transforming step on the annotation.",
    ],
  },
  {
    name: "ParseHeaders.delete",
    title: "Delete annotation field",
    family: "ParseHeaders",
    short: "Removes one or more annotation fields from the header.",
    category: "transform",
    visual: "header",
    changes: "The chosen field disappears from the header; sequence untouched.",
    headerBefore: "@SEQ1|UMI=ACGT|PRIMER=VH",
    headerAfter: "@SEQ1|PRIMER=VH",
    detail: [
      "Strips the named annotation field(s) out of every sequence header.",
      "Only the header changes; the sequence bases are left exactly as they " + "were.",
    ],
  },
  {
    name: "ParseHeaders.copy",
    title: "Copy annotation field",
    family: "ParseHeaders",
    short: "Copies the value of one annotation field into another.",
    category: "transform",
    visual: "header",
    changes: "A field's value is duplicated into a new field name.",
    headerBefore: "@SEQ1|BARCODE=ACGT",
    headerAfter: "@SEQ1|BARCODE=ACGT|UMI=ACGT",
    detail: [
      "Duplicates the contents of one annotation field into another field.",
      "Edits the header only — the sequence is unaffected.",
    ],
  },
  {
    name: "ParseHeaders.rename",
    title: "Rename annotation field",
    family: "ParseHeaders",
    short: "Changes the name of an annotation field, keeping its value.",
    category: "transform",
    visual: "header",
    changes: "A field is renamed; its value and the sequence stay the same.",
    headerBefore: "@SEQ1|BARCODE=ACGT",
    headerAfter: "@SEQ1|UMI=ACGT",
    detail: ["Renames an annotation field while keeping its value.", "A header-only edit."],
  },
  {
    name: "ParseHeaders.merge",
    title: "Merge annotation fields",
    family: "ParseHeaders",
    short: "Combines several annotation fields into one combined field.",
    category: "transform",
    visual: "header",
    changes: "Multiple fields are folded into a single combined field.",
    headerBefore: "@SEQ1|V=IGHV1|J=IGHJ4",
    headerAfter: "@SEQ1|VJ=IGHV1,IGHJ4",
    detail: [
      "Joins the values of several annotation fields into one new field.",
      "A header-only edit.",
    ],
  },
  {
    name: "ParseHeaders.expand",
    title: "Expand annotation field",
    family: "ParseHeaders",
    short: "Splits a delimited field into several separate fields.",
    category: "transform",
    visual: "header",
    changes: "One delimited field is expanded into several fields.",
    headerBefore: "@SEQ1|VJ=IGHV1,IGHJ4",
    headerAfter: "@SEQ1|VJ1=IGHV1|VJ2=IGHJ4",
    detail: [
      "Takes a single field whose value is delimited and breaks it into " +
        "multiple separate fields.",
      "A header-only edit.",
    ],
  },
  {
    name: "ParseHeaders.collapse",
    title: "Collapse field values",
    family: "ParseHeaders",
    short: "Deduplicates repeated values inside one annotation field.",
    category: "transform",
    visual: "header",
    changes: "Repeated values within a field are reduced to one.",
    headerBefore: "@SEQ1|DUP=A,A,B",
    headerAfter: "@SEQ1|DUP=A,B",
    detail: [
      "Collapses duplicate values within a single annotation field down to one " + "value each.",
      "A header-only edit.",
    ],
  },

  // ─────────────────────────── filter group ───────────────────────────
  {
    name: "FilterSeq.length",
    title: "Filter by length",
    family: "FilterSeq",
    short: "Drops reads shorter than the minimum length.",
    category: "filter",
    visual: "filter-length",
    changes: "Short reads are removed; surviving reads are unchanged.",
    detail: [
      "Removes any read shorter than the minimum required length and keeps the " +
        "rest exactly as they are.",
      "Nothing inside a surviving read is touched — only the count of reads in " +
        "the file goes down.",
    ],
  },
  {
    name: "FilterSeq.quality",
    title: "Filter by quality",
    family: "FilterSeq",
    short: "Drops reads whose mean quality is below the threshold.",
    category: "filter",
    visual: "filter-quality",
    changes: "Low-quality reads are removed; survivors are unchanged.",
    detail: [
      "Computes each read's mean Phred quality and discards the reads that " +
        "fall below the cutoff.",
      "Reads that pass are written out untouched — a pure filter.",
    ],
  },
  {
    name: "FilterSeq.missing",
    title: "Filter by missing bases",
    family: "FilterSeq",
    short: "Drops reads with too many ambiguous (N) bases.",
    category: "filter",
    visual: "filter-missing",
    changes: "Reads with too many N are removed; survivors are unchanged.",
    detail: [
      "Counts the ambiguous/missing bases (N) in each read and removes the " +
        "ones above the allowed maximum.",
      "It never edits a read — it only drops the ones that are too ambiguous.",
    ],
  },
  {
    name: "FilterSeq.repeats",
    title: "Filter by repeats",
    family: "FilterSeq",
    short: "Drops low-complexity reads with long homopolymer runs.",
    category: "filter",
    visual: "filter-repeats",
    changes: "Low-complexity reads are removed; survivors are unchanged.",
    detail: [
      "Detects long homopolymer / repeat runs and removes low-complexity reads " +
        "that exceed the maximum allowed run length.",
      "A surviving read is written out exactly as it came in.",
    ],
  },
  {
    name: "SplitSeq.select",
    title: "Select by annotation",
    family: "SplitSeq",
    short: "Keeps (or removes) reads whose annotation matches given values.",
    category: "filter",
    visual: "select",
    changes: "Reads are kept/dropped by annotation value; content unchanged.",
    detail: [
      "Keeps the reads whose chosen annotation field matches the given values " +
        "(or removes them, with negate).",
      "It selects whole records by their label — no read is edited.",
    ],
  },
  {
    name: "SplitSeq.sort",
    title: "Sort by annotation",
    family: "SplitSeq",
    short: "Reorders reads by an annotation field.",
    category: "filter",
    visual: "sort",
    changes: "The order of records changes; the records themselves do not.",
    detail: [
      "Sorts the reads by the value of an annotation field (lexicographic, or " +
        "numeric when requested).",
      "Only the ordering changes — every read keeps its exact content.",
    ],
  },
  {
    name: "SplitSeq.sample",
    title: "Subsample",
    family: "SplitSeq",
    short: "Randomly keeps a subset of reads down to a target count.",
    category: "filter",
    visual: "sample",
    changes: "A random subset is kept; the kept reads are unchanged.",
    detail: [
      "Randomly draws reads (optionally within annotation groups) down to the " +
        "requested count.",
      "The reads that are kept are untouched — only how many you keep changes.",
    ],
  },
  {
    name: "SplitSeq.samplepair",
    title: "Subsample (paired)",
    family: "SplitSeq",
    short: "Randomly subsamples paired reads, keeping mates together.",
    category: "filter",
    visual: "sample",
    changes: "A random subset of pairs is kept; the reads are unchanged.",
    detail: [
      "Randomly subsamples paired-end reads while keeping each R1/R2 mate pair " + "together.",
      "No read is edited — it only thins the dataset.",
    ],
  },
  {
    name: "SplitSeq.count",
    title: "Split by count",
    family: "SplitSeq",
    short: "Splits the file into parts of at most max_count reads.",
    category: "filter",
    visual: "split-count",
    changes: "One file is split into several; reads are unchanged.",
    detail: [
      "Distributes the reads into multiple output files, each holding at most " +
        "max_count reads.",
      "Every read ends up in some file exactly as it was — nothing is edited.",
    ],
  },
  {
    name: "SplitSeq.group",
    title: "Split by field",
    family: "SplitSeq",
    short: "Splits reads into separate files by an annotation value.",
    category: "filter",
    visual: "split-group",
    changes: "Reads are routed to files by annotation; content unchanged.",
    detail: [
      "Sends reads to separate files according to the value of an annotation " +
        "field (optionally bucketed by a numeric threshold).",
      "It is a routing / grouping step — reads keep their content.",
    ],
  },
  {
    name: "ParseHeaders.table",
    title: "Export to table",
    family: "ParseHeaders",
    short: "Writes selected annotation fields to a TSV table (ends sequences).",
    category: "filter",
    visual: "table",
    changes: "Annotations are read out to a TSV; the reads are not edited.",
    detail: [
      "Exports the chosen annotation fields to a tab-delimited table instead " +
        "of sequences, ending the sequence stream.",
      "It reads the existing annotations out into a table without modifying any " +
        "record, so it sits with the non-editing steps.",
    ],
  },

  // ─────────────── ConvertHeaders (transform: header rewrite) ───────────────
  {
    name: "ConvertHeaders.illumina",
    title: "Convert Illumina headers",
    family: "ConvertHeaders",
    short: "Rewrites Illumina read headers into pRESTO FIELD=VALUE annotations.",
    category: "transform",
    visual: "header",
    changes: "The header is rewritten; the bases and qualities are untouched.",
    headerBefore: "M01234:12:000000000-A1B2C:1:1101:1000:2000 1:N:0:ATCACG",
    headerAfter: "M01234:12:000000000-A1B2C:1:1101:1000:2000|INDEX=ATCACG|READ=1",
    detail: [
      "Reads the colon-separated Illumina header and turns each piece it " +
        "recognises (run, tile, coordinates, read number, sample index) into a " +
        "named pRESTO annotation.",
      "Every later step reads annotations in the pRESTO format, so a conversion " +
        "step usually comes first when the data did not come out of pRESTO.",
    ],
  },
  {
    name: "ConvertHeaders.454",
    title: "Convert 454 headers",
    family: "ConvertHeaders",
    short: "Rewrites Roche 454 read headers into pRESTO annotations.",
    category: "transform",
    visual: "header",
    changes: "The header is rewritten; the read itself is unchanged.",
    detail: [
      "Parses the Roche 454 header layout and writes its fields back as pRESTO " +
        "FIELD=VALUE annotations.",
      "Reads whose header does not match the 454 layout fail out to the step's " +
        "fail file instead of being silently mangled.",
    ],
  },
  {
    name: "ConvertHeaders.genbank",
    title: "Convert GenBank headers",
    family: "ConvertHeaders",
    short: "Rewrites NCBI GenBank / RefSeq headers into pRESTO annotations.",
    category: "transform",
    visual: "header",
    changes: "The header is rewritten; the sequence is unchanged.",
    detail: [
      "Splits an NCBI GenBank or RefSeq definition line into the accession and " +
        "the description, and stores them as pRESTO annotations.",
      "Useful when a reference or germline FASTA downloaded from NCBI has to " +
        "flow through the same pipeline as the sample reads.",
    ],
  },
  {
    name: "ConvertHeaders.imgt",
    title: "Convert IMGT headers",
    family: "ConvertHeaders",
    short: "Rewrites IMGT/GENE-DB headers; `simple` keeps only the allele.",
    category: "transform",
    visual: "header",
    changes: "The header is rewritten; the sequence is unchanged.",
    detail: [
      "Parses the pipe-delimited IMGT/GENE-DB header and stores its fields " +
        "(allele, species, functionality, region…) as pRESTO annotations.",
      "With the `simple` switch on, only the allele name survives — handy when " +
        "the full IMGT header would clutter every downstream annotation.",
    ],
  },
  {
    name: "ConvertHeaders.migec",
    title: "Convert MIGEC headers",
    family: "ConvertHeaders",
    short: "Rewrites MIGEC consensus headers into pRESTO annotations.",
    category: "transform",
    visual: "header",
    changes: "The header is rewritten; the sequence is unchanged.",
    detail: [
      "Converts the headers MIGEC writes on its consensus sequences, so UMI " +
        "group sizes and barcodes become ordinary pRESTO annotations.",
      "Lets a repertoire that was already collapsed by MIGEC continue through " +
        "pRESTO steps that read UMI or count annotations.",
    ],
  },
  {
    name: "ConvertHeaders.sra",
    title: "Convert SRA / ENA headers",
    family: "ConvertHeaders",
    short: "Rewrites NCBI SRA or EMBL-EBI ENA headers into pRESTO annotations.",
    category: "transform",
    visual: "header",
    changes: "The header is rewritten; the read itself is unchanged.",
    detail: [
      "Parses the header layout that fastq-dump and the ENA browser produce " +
        "and stores the run accession and spot information as annotations.",
      "This is the usual first step for data pulled straight from a public " +
        "sequence archive.",
    ],
  },
  {
    name: "ConvertHeaders.generic",
    title: "Convert unknown headers",
    family: "ConvertHeaders",
    short: "Wraps an unrecognised header into a single pRESTO annotation.",
    category: "transform",
    visual: "header",
    changes: "The header is rewritten; the read itself is unchanged.",
    detail: [
      "For headers with no known annotation system: the identifier is kept and " +
        "the rest of the description is preserved as one annotation field.",
      "Use it when the reads come from a tool pRESTO has no dedicated converter " +
        "for, so later steps still see a well-formed pRESTO header.",
    ],
  },

  // ──────────────── AlignSets (transform: sequence padding) ─────────────────
  {
    name: "AlignSets.muscle",
    title: "Align sets (MUSCLE)",
    family: "AlignSets",
    short: "Multiple aligns the reads of each barcode set with MUSCLE.",
    category: "transform",
    visual: "consensus",
    changes: "Gaps are inserted so every read in a set lines up column by column.",
    detail: [
      "Runs MUSCLE on each UMI/barcode group so all of its reads share one " +
        "coordinate system — indels inside a group stop shifting the columns.",
      "The bases themselves are not replaced, but gap characters are inserted, " +
        "so the reads that come out are longer than the reads that went in.",
      "Needs the muscle executable installed on the server. It is normally run " +
        "just before building a consensus for each set.",
    ],
  },
  {
    name: "AlignSets.offset",
    title: "Align sets (primer offsets)",
    family: "AlignSets",
    short: "Lines up each set using a table of primer offsets — no aligner needed.",
    category: "transform",
    visual: "trim",
    changes: "Reads are padded with gaps, or cut, to a common start position.",
    detail: [
      "Instead of aligning, it looks up each read's primer in an offset table " +
        "and shifts the read by that many positions.",
      "In `pad` mode the offset is added as leading gaps; in `cut` mode the " +
        "5' end is trimmed to a common start, which shortens the read.",
      "The offset table is the file produced by the table subcommand; upload it " +
        "as the step's offset file.",
    ],
  },
  {
    name: "AlignSets.table",
    title: "Build primer offset table",
    family: "AlignSets",
    short: "Aligns a primer FASTA and writes the offset table (ends sequences).",
    category: "filter",
    visual: "table",
    changes: "Produces a TSV of primer offsets; no read is touched.",
    detail: [
      "Multiple aligns the primers in a FASTA file and records how far each one " +
        "starts from the common 5' (or, in reverse mode, 3') position.",
      "It consumes no reads and emits a table, so it ends the pipeline. Download " +
        "the table and upload it again as the offset file for the offset step.",
      "Needs the muscle executable installed on the server.",
    ],
  },

  // ───────────── ClusterSets (transform: adds a CLUSTER annotation) ─────────
  {
    name: "ClusterSets.set",
    title: "Cluster within sets",
    family: "ClusterSets",
    short: "Splits each barcode group into clusters of similar sequences.",
    category: "transform",
    visual: "header",
    changes: "A CLUSTER annotation is added to every read's header.",
    headerBefore: "READ1|BARCODE=ACGTACGT",
    headerAfter: "READ1|BARCODE=ACGTACGT|CLUSTER=2",
    detail: [
      "Clusters the reads inside each UMI/barcode group by sequence identity " +
        "and writes the cluster number into a CLUSTER annotation.",
      "This is how you catch a barcode that was shared by more than one " +
        "molecule: the group splits into clusters instead of being forced into " +
        "one wrong consensus.",
      "Needs usearch, vsearch or cd-hit-est installed on the server.",
    ],
  },
  {
    name: "ClusterSets.barcode",
    title: "Cluster barcodes",
    family: "ClusterSets",
    short: "Clusters the barcode sequences themselves, merging near-identical UMIs.",
    category: "transform",
    visual: "header",
    changes: "A CLUSTER annotation groups reads whose barcodes cluster together.",
    headerBefore: "READ1|BARCODE=ACGTACGT",
    headerAfter: "READ1|BARCODE=ACGTACGT|CLUSTER=7",
    detail: [
      "Clusters reads by their barcode/UMI sequence rather than by their read " +
        "sequence, so barcodes that differ only by a sequencing error land in " +
        "one cluster.",
      "Use the threshold suggested by the barcode error estimate to pick the " +
        "identity cut-off.",
      "Needs usearch, vsearch or cd-hit-est installed on the server.",
    ],
  },
  {
    name: "ClusterSets.all",
    title: "Cluster all reads",
    family: "ClusterSets",
    short: "Clusters every read by sequence identity, ignoring annotations.",
    category: "transform",
    visual: "header",
    changes: "A CLUSTER annotation is added to every read's header.",
    headerBefore: "READ1|PRIMER=VP1",
    headerAfter: "READ1|PRIMER=VP1|CLUSTER=13",
    detail: [
      "Runs one clustering pass over the whole file and labels each read with " +
        "the cluster it fell into — no barcode or grouping annotation needed.",
      "Handy for a quick look at repertoire structure, or to group reads before " +
        "a step that needs a grouping field.",
      "Needs usearch, vsearch or cd-hit-est installed on the server.",
    ],
  },

  // ──────────── UnifyHeaders (transform / filter, per subcommand) ───────────
  {
    name: "UnifyHeaders.consensus",
    title: "Unify field to consensus",
    family: "UnifyHeaders",
    short: "Sets an annotation to its group's majority value on every read.",
    category: "transform",
    visual: "header",
    changes: "The chosen annotation is overwritten with the group consensus.",
    headerBefore: "READ3|BARCODE=ACGT|SAMPLE=S2",
    headerAfter: "READ3|BARCODE=ACGT|SAMPLE=S1",
    detail: [
      "Within each barcode/UMI group it takes the most common value of the " +
        "chosen field and writes that value onto every read in the group.",
      "Nothing is dropped — the disagreeing reads are kept and corrected, which " +
        "is what you want when the odd value is a mis-assignment rather than " +
        "real contamination.",
    ],
  },
  {
    name: "UnifyHeaders.delete",
    title: "Delete disagreeing groups",
    family: "UnifyHeaders",
    short: "Drops whole groups whose reads disagree on an annotation.",
    category: "filter",
    visual: "select",
    changes: "Whole groups are removed; surviving reads are byte-for-byte identical.",
    detail: [
      "Checks the chosen annotation across each barcode/UMI group and removes " +
        "the entire group if its reads do not agree.",
      "The stricter alternative to the consensus subcommand: a group that mixes " +
        "two samples is thrown away rather than forced to one value.",
    ],
  },

  // ───────────── EstimateError (filter: reports, ends the stream) ───────────
  {
    name: "EstimateError.set",
    title: "Estimate error within sets",
    family: "EstimateError",
    short: "Measures sequencing error per position, quality and base (TSV).",
    category: "filter",
    visual: "table",
    changes: "Writes error tables; no read is edited or dropped.",
    detail: [
      "Builds a consensus for every UMI/barcode group with enough reads and " +
        "counts how often the individual reads disagree with it.",
      "Produces tables of the error rate by read position, by reported quality " +
        "score, by nucleotide and by group size, plus the empirical quality each " +
        "of those implies — the standard way to check whether the reported " +
        "Phred scores can be trusted.",
      "Needs FASTQ input, and ends the pipeline because it writes tables rather " +
        "than sequences.",
    ],
  },
  {
    name: "EstimateError.barcode",
    title: "Estimate barcode distances",
    family: "EstimateError",
    short: "Pairwise barcode distance histogram and clustering threshold (TSV).",
    category: "filter",
    visual: "table",
    changes: "Writes distance and threshold tables; no read is edited or dropped.",
    detail: [
      "Computes the pairwise Hamming distance distribution of the barcode " +
        "sequences and picks the dip between the two modes as a clustering " +
        "threshold.",
      "Run it before barcode clustering to choose the identity cut-off from the " +
        "data instead of guessing.",
      "Ends the pipeline, because it writes tables rather than sequences.",
    ],
  },
];

export const TRANSFORM_DOCS = STEP_DOCS.filter((s) => s.category === "transform");
export const FILTER_DOCS = STEP_DOCS.filter((s) => s.category === "filter");
