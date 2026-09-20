PIPELINE_REGISTRY = {

    "FilterSeq": {
        "length": {"depends_on": []},
        "quality": {"depends_on": []},
        "missing": {"depends_on": []},
        "repeats": {"depends_on": []},
        "trimqual": {"depends_on": []},
        "maskqual": {"depends_on": []},
    },

    "MaskPrimers": {
        "align": {"depends_on": []},
        "extract": {"depends_on": []},
        "score": {"depends_on": []},
    },

    "CollapseSeq": {
        "default": {"depends_on": ["FilterSeq"]}
    },

    "BuildConsensus": {
        "default": {"depends_on": []}
    },

    "PairSeq": {
        "default": {"depends_on": []}
    },
    "AssembleSeq": {
        "align": {"depends_on": []},
        "join": {"depends_on": []},
        "reference": {"depends_on": []},
        "sequential": {"depends_on": []},
    },

    "ParseHeaders": {
        "add": {"depends_on": []},
        "collapse": {"depends_on": []},
        "copy": {"depends_on": []},
        "delete": {"depends_on": []},
        "expand": {"depends_on": []},
        "merge": {"depends_on": []},
        "rename": {"depends_on": []},
        "table": {"depends_on": []},
    },

    "SplitSeq": {
        "count": {"depends_on": []},
        "group": {"depends_on": []},
        "sample": {"depends_on": []},
        "samplepair": {"depends_on": []},
        "sort": {"depends_on": []},
        "select": {"depends_on": []},
    },

    "AlignSets": {
        "muscle": {"depends_on": []},
        "offset": {"depends_on": []},
        "table": {"depends_on": []},
    },

    "ClusterSets": {
        "all": {"depends_on": []},
        "barcode": {"depends_on": []},
        "set": {"depends_on": []},
    },

    "ConvertHeaders": {
        "454": {"depends_on": []},
        "genbank": {"depends_on": []},
        "generic": {"depends_on": []},
        "illumina": {"depends_on": []},
        "imgt": {"depends_on": []},
        "migec": {"depends_on": []},
        "sra": {"depends_on": []},
    },

    "EstimateError": {
        "barcode": {"depends_on": []},
        "set": {"depends_on": []},
    },

    "UnifyHeaders": {
        "consensus": {"depends_on": []},
        "delete": {"depends_on": []},
    },
}
# app/pipeline/registry.py

from presto.Sequence import (
    filterLength,
    filterQuality,
    filterMissing,
    filterRepeats,
    trimQuality,
    maskQuality
)


from app.presto_wrappers.collapse_seq import (
    run_collapse_seq
)

from app.presto_wrappers.mask_primers import (
    run_mask_primers_align,
    run_mask_primers_extract,
    run_mask_primers_score
)

from app.presto_wrappers.pair_seq import (
    pair_seq
)
from app.presto_wrappers.build_consesus import build_consensus 
from app.presto_wrappers.assemble_pair import (
    run_assemble_align,
    run_assemble_join,
    run_assemble_reference,
    run_assemble_sequential,
)
from app.presto_wrappers.parse_headers import (
    run_parse_headers_add,
    run_parse_headers_collapse,
    run_parse_headers_copy,
    run_parse_headers_delete,
    run_parse_headers_expand,
    run_parse_headers_merge,
    run_parse_headers_rename,
    run_parse_headers_table,
)
from app.presto_wrappers.split_seq import (
    run_split_seq_count,
    run_split_seq_group,
    run_split_seq_sample,
    run_split_seq_samplepair,
    run_split_seq_sort,
    run_split_seq_select,
)
from app.presto_wrappers.align_sets import (
    run_align_sets_muscle,
    run_align_sets_offset,
    run_align_sets_table,
)
from app.presto_wrappers.cluster_sets import (
    run_cluster_sets_all,
    run_cluster_sets_barcode,
    run_cluster_sets_set,
)
from app.presto_wrappers.convert_headers import (
    run_convert_headers_454,
    run_convert_headers_genbank,
    run_convert_headers_generic,
    run_convert_headers_illumina,
    run_convert_headers_imgt,
    run_convert_headers_migec,
    run_convert_headers_sra,
)
from app.presto_wrappers.estimate_error import (
    run_estimate_error_barcode,
    run_estimate_error_set,
)
from app.presto_wrappers.unify_headers import (
    run_unify_headers_consensus,
    run_unify_headers_delete,
)

# =========================================================
# PIPELINE FUNCTION REGISTRY
# =========================================================



PIPELINE_FUNCTIONS = {

    # =====================================================
    # FilterSeq
    # =====================================================

    "FilterSeq.length": filterLength,

    "FilterSeq.quality": filterQuality,

    "FilterSeq.missing": filterMissing,

    "FilterSeq.repeats": filterRepeats,

    "FilterSeq.trimqual": trimQuality,

    "FilterSeq.maskqual": maskQuality,


    # =====================================================
    # MaskPrimers
    # =====================================================

    
    "MaskPrimers.align": run_mask_primers_align,
    "MaskPrimers.score": run_mask_primers_score,
    "MaskPrimers.extract": run_mask_primers_extract,


    # =====================================================
    # CollapseSeq
    # =====================================================

    "CollapseSeq.default": run_collapse_seq,


    # =====================================================
    # BuildConsensus
    # =====================================================
    "BuildConsensus.default": build_consensus ,


    # =====================================================
    # PairSeq
    # =====================================================

    "PairSeq.default": pair_seq,
    # =====================================================
    # AssembleSeq (one step per pRESTO subcommand)
    # =====================================================
    "AssembleSeq.align": run_assemble_align,
    "AssembleSeq.join": run_assemble_join,
    "AssembleSeq.reference": run_assemble_reference,
    "AssembleSeq.sequential": run_assemble_sequential,

    # =====================================================
    # ParseHeaders
    # =====================================================
    "ParseHeaders.add": run_parse_headers_add,
    "ParseHeaders.collapse": run_parse_headers_collapse,
    "ParseHeaders.copy": run_parse_headers_copy,
    "ParseHeaders.delete": run_parse_headers_delete,
    "ParseHeaders.expand": run_parse_headers_expand,
    "ParseHeaders.merge": run_parse_headers_merge,
    "ParseHeaders.rename": run_parse_headers_rename,
    "ParseHeaders.table": run_parse_headers_table,

    # =====================================================
    # SplitSeq
    # =====================================================
    "SplitSeq.count": run_split_seq_count,
    "SplitSeq.group": run_split_seq_group,
    "SplitSeq.sample": run_split_seq_sample,
    "SplitSeq.samplepair": run_split_seq_samplepair,
    "SplitSeq.sort": run_split_seq_sort,
    "SplitSeq.select": run_split_seq_select,

    # =====================================================
    # AlignSets
    # =====================================================
    "AlignSets.muscle": run_align_sets_muscle,
    "AlignSets.offset": run_align_sets_offset,
    "AlignSets.table": run_align_sets_table,

    # =====================================================
    # ClusterSets
    # =====================================================
    "ClusterSets.all": run_cluster_sets_all,
    "ClusterSets.barcode": run_cluster_sets_barcode,
    "ClusterSets.set": run_cluster_sets_set,

    # =====================================================
    # ConvertHeaders
    # =====================================================
    "ConvertHeaders.454": run_convert_headers_454,
    "ConvertHeaders.genbank": run_convert_headers_genbank,
    "ConvertHeaders.generic": run_convert_headers_generic,
    "ConvertHeaders.illumina": run_convert_headers_illumina,
    "ConvertHeaders.imgt": run_convert_headers_imgt,
    "ConvertHeaders.migec": run_convert_headers_migec,
    "ConvertHeaders.sra": run_convert_headers_sra,

    # =====================================================
    # EstimateError
    # =====================================================
    "EstimateError.barcode": run_estimate_error_barcode,
    "EstimateError.set": run_estimate_error_set,

    # =====================================================
    # UnifyHeaders
    # =====================================================
    "UnifyHeaders.consensus": run_unify_headers_consensus,
    "UnifyHeaders.delete": run_unify_headers_delete,
}

    