
from app.pipeline.capabilities import Capability


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# STEP_CONTRACTS â€” single source of truth for what each pRESTO step needs and
# produces. Consumed by the planner/validator (input_types, output_type,
# requires, requires_any, produces, requires_files, stream_behavior,
# parameter_effects) and by the metadata API (`description`, surfaced to the UI).
#
# `description` mirrors the behaviour of the underlying tool in
# app/presto_tools/* so the frontend can explain each component.
#
# output_type: "same" keeps the lane's current type; an explicit type overrides.
#   "tab" ends the sequence stream (the step writes a TSV instead of reads).
# splits_output: "always" | "conditional" | absent. The step fans one lane out
#   into several files, which ends the pipeline (see app/pipeline/splitting.py
#   for why, and for the parameter check behind "conditional").
# stream_behavior: "per_lane" (default) | "paired_io" | "merge_paired".
# requires_executable: external binaries the step shells out to (muscle,
#   usearch/vsearch/cd-hit-est). Surfaced to the UI; the wrapper raises a
#   clear error when the binary is missing from the worker's PATH.
# parameter_effects: how a parameter changes annotation capabilities
#   - "filter_annotation_fields" (consumed by step_parameter_analyzer)
#   - "parse_headers" (documentation; ParseHeaders capability changes are
#     computed in parse_headers_effects.py)
#
# produces_fields / field_effects: the concrete field-name registry
# (app/pipeline/planner.py: LaneState.fields), parallel to produces /
# parameter_effects above but tracking actual field-name strings instead of
# the coarser Capability enum. Consumed by step_parameter_analyzer.py
# (mutation on apply_step + job-launch existence validation) and by
# metadata.py (the `field_kind` a StepMetaParam gets, which the frontend uses
# to render a dropdown of real field names instead of a free-text box).
#   - produces_fields: static list of field names this step always writes,
#     independent of any parameter (e.g. CollapseSeq -> DUPCOUNT).
#   - field_effects: per-parameter effect, one of:
#       "field_name_new": the param's value(s) become new field name(s).
#         "default": literal value used when the param is absent/falsy.
#         "when": only applies if this other (boolean) param is truthy.
#       "field_name_existing": the param's value(s) must already exist in the
#         lane; validation-only, no mutation.
#         "optional": skip the check when the param has no value.
#         "lane": which lane to check against, for steps whose params span
#         two lanes (PairSeq's fields_1/fields_2, AssembleSeq's
#         head_fields/tail_fields) -- one of "R1"/"R2"/"head"/"tail" (the
#         step's own lane when omitted).
#       "multi": the param is a list of field names rather than one.
#   ParseHeaders.* params are classified the same way, but the table lives in
#   parse_headers_effects.PARSE_HEADERS_FIELD_EFFECTS instead (mutation there
#   is bespoke per subcommand, not expressible as static add/reference).
# ─────────────────────────────────────────────────────────────────────────


STEP_CONTRACTS = {

    # â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ FilterSeq â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    "FilterSeq.length": {
        "description": (
            "Removes reads shorter than the minimum required sequence length."
        ),
        "input_types": ["fasta", "fastq"],
        "output_type": "same",
    },

    "FilterSeq.quality": {
        "description": (
            "Removes reads whose mean Phred quality score is below the "
            "threshold."
        ),
        "input_types": ["fastq"],
        "output_type": "fastq",
        "requires": [Capability.QUALITY],
    },

    "FilterSeq.missing": {
        "description": (
            "Removes reads containing more than the allowed number of "
            "ambiguous/missing bases (N)."
        ),
        "input_types": ["fasta", "fastq"],
        "output_type": "same",
    },

    "FilterSeq.repeats": {
        "description": (
            "Removes low-complexity reads with homopolymer/repeat runs longer "
            "than the maximum allowed."
        ),
        "input_types": ["fasta", "fastq"],
        "output_type": "same",
    },

    "FilterSeq.trimqual": {
        "description": (
            "Trims low-quality bases from the ends of each read using a "
            "sliding-window quality cutoff."
        ),
        "input_types": ["fastq"],
        "output_type": "fastq",
        "requires": [Capability.QUALITY],
    },

    "FilterSeq.maskqual": {
        "description": (
            "Masks (replaces with N) individual bases below the quality "
            "threshold instead of discarding the whole read."
        ),
        "input_types": ["fastq"],
        "output_type": "fastq",
        "requires": [Capability.QUALITY],
    },

    # â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ MaskPrimers â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    "MaskPrimers.align": {
        "description": (
            "Identifies primers by local alignment against a primer FASTA "
            "(variable position) and masks or cuts them, annotating PRIMER."
        ),
        "input_types": ["fastq", "fasta"],
        "output_type": "same",
        "requires_files": ["primer_file"],
        "produces": [Capability.PRIMER],
        "field_effects": {
            "primer_field": {"type": "field_name_new", "default": "PRIMER"},
            "barcode_field": {
                "type": "field_name_new",
                "default": "BARCODE",
                "when": "barcode",
            },
        },
    },

    "MaskPrimers.extract": {
        "description": (
            "Extracts a fixed-position region of each read as an annotation "
            "without needing a primer file."
        ),
        "input_types": ["fastq", "fasta"],
        "output_type": "same",
        "produces": [Capability.PRIMER],
        "field_effects": {
            "primer_field": {"type": "field_name_new", "default": "PRIMER"},
            "barcode_field": {
                "type": "field_name_new",
                "default": "BARCODE",
                "when": "barcode",
            },
        },
    },

    "MaskPrimers.score": {
        "description": (
            "Matches primers at a fixed start position by scoring against a "
            "primer FASTA; annotates PRIMER and optionally a barcode/UMI."
        ),
        "input_types": ["fastq", "fasta"],
        "output_type": "same",
        "requires_files": ["primer_file"],
        "produces": [Capability.PRIMER],
        "field_effects": {
            "primer_field": {"type": "field_name_new", "default": "PRIMER"},
            "barcode_field": {
                "type": "field_name_new",
                "default": "BARCODE",
                "when": "barcode",
            },
        },
    },

    # â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ CollapseSeq â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    "CollapseSeq.default": {
        "description": (
            "Removes duplicate sequences, collapsing identical reads into "
            "unique records and recording duplicate counts (DUPCOUNT)."
        ),
        "input_types": ["fastq", "fasta"],
        "output_type": "same",
        "produces": [Capability.GROUPED, Capability.COLLAPSED],
        "produces_fields": ["DUPCOUNT"],
        "parameter_effects": {
            "copy_fields": {
                "type": "filter_annotation_fields",
                "affects": ["BARCODE", "UMI", "PRIMER", "DUPCOUNT", "CONSCOUNT"],
            }
        },
        "field_effects": {
            "uniq_fields": {"type": "field_name_existing", "multi": True, "optional": True},
            "copy_fields": {"type": "field_name_existing", "multi": True, "optional": True},
            "max_field": {"type": "field_name_existing", "optional": True},
            "min_field": {"type": "field_name_existing", "optional": True},
        },
    },

    # â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ BuildConsensus â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    "BuildConsensus.default": {
        "description": (
            "Builds a consensus sequence for each UMI/barcode group to correct "
            "errors within molecular-barcoded reads."
        ),
        "input_types": ["fastq", "fasta"],
        "output_type": "same",
        "requires_any": [Capability.UMI, Capability.BARCODE],
        "produces": [Capability.GROUPED],
        # CONSCOUNT is unconditional; PRIMER/PRCOUNT vs PRCONS/PRFREQ (when
        # primer_field is set, gated on primer_freq) and copy_fields' derived
        # {field}_COUNT/{field}_FREQ (for the "set"/"majority" actions) are
        # fixed field names a *parameter's presence* controls rather than a
        # parameter's own value -- handled as a bespoke case in
        # step_parameter_analyzer.fields_after_step, the same way
        # ConvertHeaders.imgt's `simple` toggle is.
        "produces_fields": ["CONSCOUNT"],
        "parameter_effects": {
            "copy_fields": {
                "type": "filter_annotation_fields",
                "affects": ["BARCODE", "UMI", "PRIMER", "DUPCOUNT", "CONSCOUNT"],
            }
        },
        "field_effects": {
            "barcode_field": {"type": "field_name_existing", "default": "BARCODE"},
            "primer_field": {"type": "field_name_existing", "optional": True},
            "copy_fields": {"type": "field_name_existing", "multi": True, "optional": True},
        },
    },

    # â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ PairSeq â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    "PairSeq.default": {
        "description": (
            "Synchronizes paired R1/R2 files so mates line up, and copies "
            "annotation fields between the two reads."
        ),
        "input_types": ["fasta", "fastq"],
        "output_type": "same",
        "stream_behavior": "paired_io",
        "requires": [Capability.PAIRED_END],
        "field_effects": {
            "fields_1": {"type": "field_name_existing", "multi": True, "lane": "R1"},
            "fields_2": {"type": "field_name_existing", "multi": True, "lane": "R2"},
        },
    },

    # â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ AssembleSeq â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    "AssembleSeq.align": {
        "description": (
            "Assembles paired-end reads into one sequence by finding a "
            "significance-tested de novo overlap."
        ),
        "input_types": ["fasta", "fastq"],
        "output_type": "same",
        "stream_behavior": "merge_paired",
        "produces": [Capability.ASSEMBLED],
        "field_effects": {
            "head_fields": {"type": "field_name_existing", "multi": True, "lane": "head", "optional": True},
            "tail_fields": {"type": "field_name_existing", "multi": True, "lane": "tail", "optional": True},
        },
    },

    "AssembleSeq.join": {
        "description": (
            "Concatenates paired-end reads end-to-end (optionally with a gap) "
            "without searching for an overlap."
        ),
        "input_types": ["fasta", "fastq"],
        "output_type": "same",
        "stream_behavior": "merge_paired",
        "produces": [Capability.ASSEMBLED],
        "field_effects": {
            "head_fields": {"type": "field_name_existing", "multi": True, "lane": "head", "optional": True},
            "tail_fields": {"type": "field_name_existing", "multi": True, "lane": "tail", "optional": True},
        },
    },

    "AssembleSeq.reference": {
        "description": (
            "Assembles paired-end reads guided by alignment to a reference "
            "sequence (FASTA)."
        ),
        "input_types": ["fasta", "fastq"],
        "output_type": "same",
        "stream_behavior": "merge_paired",
        "requires_files": ["ref_file"],
        "produces": [Capability.ASSEMBLED],
        "field_effects": {
            "head_fields": {"type": "field_name_existing", "multi": True, "lane": "head", "optional": True},
            "tail_fields": {"type": "field_name_existing", "multi": True, "lane": "tail", "optional": True},
        },
    },

    "AssembleSeq.sequential": {
        "description": (
            "Attempts de novo overlap assembly first, then falls back to "
            "reference-guided assembly for unjoined pairs."
        ),
        "input_types": ["fasta", "fastq"],
        "output_type": "same",
        "stream_behavior": "merge_paired",
        "requires_files": ["ref_file"],
        "produces": [Capability.ASSEMBLED],
        "field_effects": {
            "head_fields": {"type": "field_name_existing", "multi": True, "lane": "head", "optional": True},
            "tail_fields": {"type": "field_name_existing", "multi": True, "lane": "tail", "optional": True},
        },
    },

    # â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ ParseHeaders â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    # ParseHeaders capability changes are computed in parse_headers_effects.py
    # from the field/name params; the `produces`/`parameter_effects` below are
    # for the planner metadata + UI. `table` ends the sequence stream (TSV).
    "ParseHeaders.add": {
        "description": (
            "Adds new annotation fields with fixed values to every sequence "
            "header."
        ),
        "input_types": ["fasta", "fastq"],
        "output_type": "same",
        "produces": [Capability.PARSED_HEADER],
        "parameter_effects": {
            "fields": {"type": "parse_headers", "operation": "add"},
            "values": {"type": "parse_headers", "operation": "add"},
        },
    },

    "ParseHeaders.collapse": {
        "description": (
            "Collapses duplicate values within an annotation field into a "
            "single value."
        ),
        "input_types": ["fasta", "fastq"],
        "output_type": "same",
        "produces": [Capability.PARSED_HEADER],
        "parameter_effects": {
            "fields": {"type": "parse_headers", "operation": "collapse"},
        },
    },

    "ParseHeaders.copy": {
        "description": "Copies the contents of one annotation field into another.",
        "input_types": ["fasta", "fastq"],
        "output_type": "same",
        "produces": [Capability.PARSED_HEADER],
        "parameter_effects": {
            "fields": {"type": "parse_headers", "operation": "copy"},
            "names": {"type": "parse_headers", "operation": "copy"},
        },
    },

    "ParseHeaders.delete": {
        "description": "Deletes annotation fields from sequence headers.",
        "input_types": ["fasta", "fastq"],
        "output_type": "same",
        "produces": [Capability.PARSED_HEADER],
        "parameter_effects": {
            "fields": {"type": "parse_headers", "operation": "delete"},
        },
    },

    "ParseHeaders.expand": {
        "description": (
            "Expands a delimited annotation field into several separate fields."
        ),
        "input_types": ["fasta", "fastq"],
        "output_type": "same",
        "produces": [Capability.PARSED_HEADER],
        "parameter_effects": {
            "fields": {"type": "parse_headers", "operation": "expand"},
        },
    },

    "ParseHeaders.merge": {
        "description": (
            "Merges several annotation fields into a single combined field."
        ),
        "input_types": ["fasta", "fastq"],
        "output_type": "same",
        "produces": [Capability.PARSED_HEADER],
        "parameter_effects": {
            "fields": {"type": "parse_headers", "operation": "merge"},
            "name": {"type": "parse_headers", "operation": "merge"},
            "delete": {"type": "parse_headers", "operation": "merge"},
        },
    },

    "ParseHeaders.rename": {
        "description": "Renames annotation fields in sequence headers.",
        "input_types": ["fasta", "fastq"],
        "output_type": "same",
        "produces": [Capability.PARSED_HEADER],
        "parameter_effects": {
            "fields": {"type": "parse_headers", "operation": "rename"},
            "names": {"type": "parse_headers", "operation": "rename"},
        },
    },

    "ParseHeaders.table": {
        "description": (
            "Exports selected annotation fields to a tab-delimited table (TSV) "
            "instead of sequences; ends the sequence stream."
        ),
        "input_types": ["fasta", "fastq"],
        "output_type": "tab",
        "parameter_effects": {
            "fields": {"type": "parse_headers", "operation": "table"},
        },
    },

    # â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ SplitSeq â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    "SplitSeq.count": {
        "description": (
            "Splits a sequence file into multiple parts, each containing at "
            "most max_count reads (20,000 reads at max_count=4,000 gives 5 "
            "files). Every part is downloadable; the pipeline ends here."
        ),
        "input_types": ["fasta", "fastq"],
        "output_type": "same",
        "produces": [Capability.SPLIT],
        "splits_output": "always",
    },

    "SplitSeq.group": {
        "description": (
            "Splits sequences into separate files by the value of an annotation "
            "field: one file per distinct value, which ends the pipeline. A "
            "numeric threshold instead makes the bounded under/at-least split, "
            "and the at-least part carries on to the next step."
        ),
        "input_types": ["fasta", "fastq"],
        "output_type": "same",
        "produces": [Capability.SPLIT],
        "splits_output": "conditional",
        "parameter_effects": {
            "field": {"type": "split_by_field", "operation": "group"},
        },
        "field_effects": {
            "field": {"type": "field_name_existing"},
        },
    },

    "SplitSeq.sample": {
        "description": (
            "Randomly subsamples reads (optionally within annotation-field "
            "groups) down to the requested counts: one output file per size in "
            "max_count. Asking for more than one size ends the pipeline."
        ),
        "input_types": ["fasta", "fastq"],
        "output_type": "same",
        "produces": [Capability.SPLIT],
        "splits_output": "conditional",
        "field_effects": {
            "field": {"type": "field_name_existing", "optional": True},
        },
    },

    "SplitSeq.samplepair": {
        "description": (
            "Randomly subsamples paired-end reads, keeping R1/R2 mates "
            "together: one R1/R2 pair per size in max_count. Asking for more "
            "than one size ends the pipeline."
        ),
        "input_types": ["fasta", "fastq"],
        "output_type": "same",
        "stream_behavior": "paired_io",
        "requires": [Capability.PAIRED_END],
        "produces": [Capability.SPLIT],
        "splits_output": "conditional",
    },

    "SplitSeq.sort": {
        "description": (
            "Sorts sequences by an annotation field (lexicographic, or numeric "
            "when requested). Writes one file unless max_count is given, which "
            "also partitions the sorted reads and ends the pipeline."
        ),
        "input_types": ["fasta", "fastq"],
        "output_type": "same",
        "produces": [Capability.SPLIT],
        "splits_output": "conditional",
        "parameter_effects": {
            "field": {"type": "split_by_field", "operation": "sort"},
        },
        "field_effects": {
            "field": {"type": "field_name_existing"},
        },
    },

    "SplitSeq.select": {
        "description": (
            "Keeps (or, with negate, removes) reads whose annotation field "
            "matches the given values or value file. Writes a single file, so "
            "the pipeline can continue after it."
        ),
        "input_types": ["fasta", "fastq"],
        "output_type": "same",
        "produces": [Capability.SPLIT],
        "parameter_effects": {
            "field": {"type": "split_by_field", "operation": "select"},
        },
        "field_effects": {
            "field": {"type": "field_name_existing"},
        },
    },

    # ───────────────────────────── AlignSets ─────────────────────────────
    "AlignSets.muscle": {
        "description": (
            "Multiple aligns the reads of each barcode/UMI set with MUSCLE so "
            "the set can be collapsed into a consensus."
        ),
        "input_types": ["fasta", "fastq"],
        "output_type": "same",
        "requires_any": [Capability.UMI, Capability.BARCODE],
        "produces": [Capability.ALIGNED, Capability.GROUPED],
        "requires_executable": ["muscle"],
        "field_effects": {
            "barcode_field": {"type": "field_name_existing", "default": "BARCODE"},
        },
    },

    "AlignSets.offset": {
        "description": (
            "Aligns the reads of each barcode/UMI set using a table of primer "
            "offsets, padding with gaps or cutting to a common start position."
        ),
        "input_types": ["fasta", "fastq"],
        "output_type": "same",
        "requires": [Capability.PRIMER],
        "requires_any": [Capability.UMI, Capability.BARCODE],
        "requires_files": ["offset_file"],
        "produces": [Capability.ALIGNED, Capability.GROUPED],
        "field_effects": {
            "barcode_field": {"type": "field_name_existing", "default": "BARCODE"},
            "primer_field": {"type": "field_name_existing", "default": "PRIMER"},
        },
    },

    "AlignSets.table": {
        "description": (
            "Builds a 5-prime (or 3-prime) primer offset table by multiple "
            "aligning a primer FASTA; the table feeds the offset subcommand."
        ),
        "input_types": ["fasta", "fastq"],
        "output_type": "tab",
        "requires_files": ["primer_file"],
        "requires_executable": ["muscle"],
    },

    # ──────────────────────────── ClusterSets ────────────────────────────
    "ClusterSets.all": {
        "description": (
            "Clusters every read by sequence identity, regardless of "
            "annotation, and records the cluster in a CLUSTER field."
        ),
        "input_types": ["fasta", "fastq"],
        "output_type": "same",
        "produces": [Capability.CLUSTERED],
        "requires_executable": ["usearch", "vsearch", "cd-hit-est"],
        "field_effects": {
            "cluster_field": {"type": "field_name_new", "default": "CLUSTER"},
        },
    },

    "ClusterSets.barcode": {
        "description": (
            "Clusters reads by clustering their barcode/UMI sequences, so "
            "barcodes that differ by sequencing error end up in one CLUSTER."
        ),
        "input_types": ["fasta", "fastq"],
        "output_type": "same",
        "requires_any": [Capability.UMI, Capability.BARCODE],
        "produces": [Capability.CLUSTERED],
        "requires_executable": ["usearch", "vsearch", "cd-hit-est"],
        "field_effects": {
            "barcode_field": {"type": "field_name_existing", "default": "BARCODE"},
            "cluster_field": {"type": "field_name_new", "default": "CLUSTER"},
        },
    },

    "ClusterSets.set": {
        "description": (
            "Clusters reads by sequence data within each barcode/UMI group, "
            "splitting a barcode that captured more than one molecule."
        ),
        "input_types": ["fasta", "fastq"],
        "output_type": "same",
        "requires_any": [Capability.UMI, Capability.BARCODE],
        "produces": [Capability.CLUSTERED, Capability.GROUPED],
        "requires_executable": ["usearch", "vsearch", "cd-hit-est"],
        "field_effects": {
            "set_field": {"type": "field_name_existing", "default": "BARCODE"},
            "cluster_field": {"type": "field_name_new", "default": "CLUSTER"},
        },
    },

    # ─────────────────────────── ConvertHeaders ──────────────────────────
    # ConvertHeaders rewrites a vendor header into pRESTO's FIELD=VALUE format,
    # so it normally runs first. Which annotations appear is decided by the
    # input format, not by parameters — hence only PARSED_HEADER is produced.
    "ConvertHeaders.454": {
        "description": "Converts Roche 454 sequence headers to the pRESTO format.",
        "input_types": ["fasta", "fastq"],
        "output_type": "same",
        "produces": [Capability.PARSED_HEADER],
        "produces_fields": ["LENGTH"],
    },

    "ConvertHeaders.genbank": {
        "description": (
            "Converts NCBI GenBank and RefSeq sequence headers to the pRESTO "
            "format."
        ),
        "input_types": ["fasta", "fastq"],
        "output_type": "same",
        "produces": [Capability.PARSED_HEADER],
        # presto.Annotation.convertGenbankHeader only emits GI/SOURCE for the
        # legacy pipe-delimited header (gi|...|...|accession|desc); the
        # modern "<accession> <description>" format -- the common case today
        # -- produces just ID/DESC. Only list the two fields both branches
        # guarantee, so the registry never claims GI/SOURCE exist when they
        # don't (a wrong field-registry entry only surfaces as a runtime
        # failure once something downstream references it).
        "produces_fields": ["ID", "DESC"],
    },

    "ConvertHeaders.generic": {
        "description": (
            "Converts sequence headers with an unknown annotation system, "
            "keeping the original description as a single annotation."
        ),
        "input_types": ["fasta", "fastq"],
        "output_type": "same",
        "produces": [Capability.PARSED_HEADER],
        # Deliberately no produces_fields: the output field set depends
        # entirely on what the input already contained, so this step cannot
        # improve field-registry confidence (see step_parameter_analyzer.py).
    },

    "ConvertHeaders.illumina": {
        "description": "Converts Illumina sequence headers to the pRESTO format.",
        "input_types": ["fasta", "fastq"],
        "output_type": "same",
        "produces": [Capability.PARSED_HEADER],
        "produces_fields": ["READ"],
    },

    "ConvertHeaders.imgt": {
        "description": (
            "Converts sequence headers output by IMGT/GENE-DB; simple keeps "
            "only the allele name."
        ),
        "input_types": ["fasta", "fastq"],
        "output_type": "same",
        "produces": [Capability.PARSED_HEADER],
        # `simple` toggles the produced field set -- handled as a bespoke
        # case in step_parameter_analyzer.fields_after_step, the same way
        # MaskPrimers' conditional barcode_field is.
    },

    "ConvertHeaders.migec": {
        "description": (
            "Converts headers of consensus sequences generated by MIGEC to the "
            "pRESTO format."
        ),
        "input_types": ["fasta", "fastq"],
        "output_type": "same",
        "produces": [Capability.PARSED_HEADER],
        "produces_fields": ["COUNT"],
    },

    "ConvertHeaders.sra": {
        "description": (
            "Converts NCBI SRA or EMBL-EBI ENA sequence headers to the pRESTO "
            "format."
        ),
        "input_types": ["fasta", "fastq"],
        "output_type": "same",
        "produces": [Capability.PARSED_HEADER],
        "produces_fields": ["DESC"],
    },

    # ─────────────────────────── EstimateError ───────────────────────────
    # Both subcommands emit tab-delimited error tables and end the sequence
    # stream (like ParseHeaders.table).
    "EstimateError.barcode": {
        "description": (
            "Calculates pairwise distance metrics of barcode sequences and the "
            "clustering threshold they suggest; outputs tables (TSV)."
        ),
        "input_types": ["fasta", "fastq"],
        "output_type": "tab",
        "requires_any": [Capability.UMI, Capability.BARCODE],
        "field_effects": {
            "barcode_field": {"type": "field_name_existing", "default": "BARCODE"},
        },
    },

    "EstimateError.set": {
        "description": (
            "Estimates sequencing error rates within annotation sets by "
            "comparing each read to its set consensus; outputs tables (TSV)."
        ),
        "input_types": ["fastq"],
        "output_type": "tab",
        "requires": [Capability.QUALITY],
        "requires_any": [Capability.UMI, Capability.BARCODE],
        "field_effects": {
            "set_field": {"type": "field_name_existing", "default": "BARCODE"},
        },
    },

    # ─────────────────────────── UnifyHeaders ────────────────────────────
    "UnifyHeaders.consensus": {
        "description": (
            "Reassigns an annotation field to the consensus value of its "
            "barcode/UMI group, so every read in the group agrees."
        ),
        "input_types": ["fasta", "fastq"],
        "output_type": "same",
        "requires_any": [Capability.UMI, Capability.BARCODE],
        "produces": [Capability.PARSED_HEADER, Capability.GROUPED],
        "field_effects": {
            "set_field": {"type": "field_name_existing", "default": "BARCODE"},
            "unify_field": {"type": "field_name_existing", "default": "SAMPLE"},
        },
    },

    "UnifyHeaders.delete": {
        "description": (
            "Deletes whole barcode/UMI groups whose reads disagree on the "
            "annotation field instead of forcing a consensus."
        ),
        "input_types": ["fasta", "fastq"],
        "output_type": "same",
        "requires_any": [Capability.UMI, Capability.BARCODE],
        "produces": [Capability.PARSED_HEADER, Capability.GROUPED],
        "field_effects": {
            "set_field": {"type": "field_name_existing", "default": "BARCODE"},
            "unify_field": {"type": "field_name_existing", "default": "SAMPLE"},
        },
    },
}
