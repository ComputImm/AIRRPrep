from collections import OrderedDict
from Bio import SeqIO

from presto.Annotation import (
    parseAnnotation,
    flattenAnnotation,
    mergeAnnotation,
    collapseAnnotation
)
from app.presto_tools.CollapseSeq import (
    DuplicateSet,
    findUID,
    findUniqueSeq,
    merge_dicts
)


from presto.IO import readSeqFile, getFileType

from presto.Defaults import default_delimiter


def run_collapse_seq(
    seq_file,
    out_file,
    
    
    output_duplicate=None,
    output_undetermined=None,
    max_missing=0,

    uniq_fields=None,

    copy_fields=None,
    copy_actions=None,

    max_field=None,
    min_field=None,

    inner=False,
    keep_missing=False,

    out_type=None,

    delimiter=default_delimiter
):
    # Real pRESTO's collapseSeq auto-detects the output format from the input
    # (out_args['out_type'] = out_args['out_type'] or in_type) instead of
    # defaulting to fastq; a hardcoded "fastq" here made every FASTA-lane
    # CollapseSeq step crash in Bio.SeqIO writing records with no quality
    # scores.
    out_type = out_type or getFileType(seq_file)

    output_unique=out_file
    seq_dict = SeqIO.to_dict(
        readSeqFile(seq_file, index=False)
    )

    uniq_dicts = {}

    search_keys = list(seq_dict.keys())

    dup_keys = []

    for n in range(0, max_missing + 1):

        uniq_dicts, search_keys, dup_list = findUniqueSeq(
            uniq_dicts=uniq_dicts,
            search_keys=search_keys,
            seq_dict=seq_dict,

            max_missing=n,

            uniq_fields=uniq_fields,

            copy_fields=copy_fields,

            max_field=max_field,
            min_field=min_field,

            inner=inner,

            delimiter=delimiter
        )

        dup_keys.extend(dup_list)

        if len(search_keys) == 0:
            break

    uniq_dict = merge_dicts(uniq_dicts)

    unique_records = []

    for val in uniq_dict.values():

        out_seq = val.seq

        out_ann = parseAnnotation(
            out_seq.description,
            delimiter=delimiter
        )

        out_app = OrderedDict()

        if copy_fields and copy_actions:

            for f, a in zip(copy_fields, copy_actions):

                x = collapseAnnotation(
                    val.annotations,
                    a,
                    f,
                    delimiter=delimiter
                )

                out_app[f] = x[f]

                out_ann.pop(f, None)

        out_app["DUPCOUNT"] = val.count

        out_ann = mergeAnnotation(
            out_ann,
            out_app,
            delimiter=delimiter
        )

        out_seq.id = out_seq.name = flattenAnnotation(
            out_ann,
            delimiter=delimiter
        )

        out_seq.description = ""

        unique_records.append(out_seq)

    SeqIO.write(unique_records, output_unique, out_type)

    if output_duplicate:

        duplicate_records = [
            seq_dict[k]
            for k in dup_keys
        ]

        SeqIO.write(
            duplicate_records,
            output_duplicate,
            out_type
        )

    if output_undetermined and not keep_missing:

        undetermined_records = [
            seq_dict[k]
            for k in search_keys
        ]

        SeqIO.write(
            undetermined_records,
            output_undetermined,
            out_type
        )

    if keep_missing:

        extra_records = []

        for k in search_keys:

            out_seq = seq_dict[k]

            out_ann = parseAnnotation(
                out_seq.description,
                delimiter=delimiter
            )

            out_ann = mergeAnnotation(
                out_ann,
                {"DUPCOUNT": 1},
                delimiter=delimiter
            )

            out_seq.id = out_seq.name = flattenAnnotation(
                out_ann,
                delimiter=delimiter
            )

            out_seq.description = ""

            extra_records.append(out_seq)

        with open(output_unique, "a") as handle:
            SeqIO.write(extra_records, handle, out_type)

    return {

        "unique_file": output_unique,

        "duplicate_file": output_duplicate,

        "undetermined_file": output_undetermined,

        "unique_count": len(unique_records),

        "duplicate_count": len(dup_keys),

        "undetermined_count": len(search_keys)
    }