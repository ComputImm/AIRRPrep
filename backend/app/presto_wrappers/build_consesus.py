from collections import OrderedDict
from Bio import SeqIO

from presto.Defaults import (
    default_barcode_field,
    default_consensus_min_freq,
    default_consensus_min_qual,
    default_consensus_min_count,
    default_out_args,
)

from presto.Annotation import (
    flattenAnnotation,
    mergeAnnotation,
    getAnnotationValues,
    annotationConsensus,
)

from presto.Sequence import (
    subsetSeqSet,
    calculateDiversity,
    qualityConsensus,
    frequencyConsensus,
    indexSeqSets,
    calculateSetError,
    deleteSeqPositions,
    findGapPositions,
)

from presto.IO import (
    getFileType,
    readSeqFile,
    getOutputHandle,
    printLog,
)

from presto.Defaults import default_delimiter

def build_consensus_group(
    seq_list,
    group_id,
    cons_func,
    cons_args,
    min_count=default_consensus_min_count,
    primer_field=None,
    primer_freq=None,
    max_gap=None,
    max_error=None,
    max_diversity=None,
    copy_fields=None,
    copy_actions=None,
    delimiter=default_delimiter,
):
    """
    Pure synchronous replacement for processQueue()
    """

    log = OrderedDict()

    log["BARCODE"] = group_id
    log["SEQCOUNT"] = len(seq_list)

    # -----------------------------
    # Primer consensus
    # -----------------------------

    if primer_field is None:
        filtered = seq_list
        primer_ann = None

    else:
        primer_ann = OrderedDict()

        prcons = annotationConsensus(
            seq_list,
            primer_field,
            delimiter=delimiter,
        )

        log["PRIMER"] = ",".join(prcons["set"])
        log["PRCOUNT"] = ",".join([str(x) for x in prcons["count"]])
        log["PRCONS"] = prcons["cons"]
        log["PRFREQ"] = prcons["freq"]

        if primer_freq is None:

            filtered = seq_list

            primer_ann = mergeAnnotation(
                primer_ann,
                {"PRIMER": prcons["set"]},
                delimiter=delimiter,
            )

            primer_ann = mergeAnnotation(
                primer_ann,
                {"PRCOUNT": prcons["count"]},
                delimiter=delimiter,
            )

        elif prcons["freq"] >= primer_freq:

            filtered = subsetSeqSet(
                seq_list,
                primer_field,
                prcons["cons"],
                delimiter=delimiter,
            )

            primer_ann = mergeAnnotation(
                primer_ann,
                {"PRCONS": prcons["cons"]},
                delimiter=delimiter,
            )

            primer_ann = mergeAnnotation(
                primer_ann,
                {"PRFREQ": prcons["freq"]},
                delimiter=delimiter,
            )

        else:
            return None, log

    # -----------------------------
    # Count filter
    # -----------------------------
    
    cons_count = len(filtered)

    log["CONSCOUNT"] = cons_count

    if cons_count < min_count:
        return None, log

    # -----------------------------
    # Build consensus
    # -----------------------------

    consensus = cons_func(filtered, **cons_args)

    # -----------------------------
    # Gap removal
    # -----------------------------

    if max_gap is not None:

        gap_positions = set(findGapPositions(filtered, max_gap))

        consensus = deleteSeqPositions(
            consensus,
            gap_positions,
        )

    else:
        gap_positions = None

    # -----------------------------
    # Diversity filter
    # -----------------------------

    if max_diversity is not None:

        diversity = calculateDiversity(filtered)

        log["DIVERSITY"] = diversity

        if diversity > max_diversity:
            return None, log

    # -----------------------------
    # Error filter
    # -----------------------------

    if max_error is not None:

        if gap_positions is not None:
            seq_check = [
                deleteSeqPositions(s, gap_positions)
                for s in filtered
            ]
        else:
            seq_check = filtered

        error = calculateSetError(
            seq_check,
            consensus,
        )

        log["ERROR"] = error

        if error > max_error:
            return None, log

    # -----------------------------
    # Copy annotations
    # -----------------------------

    copy_ann = OrderedDict()

    if copy_fields and copy_actions:

        for field, action in zip(copy_fields, copy_actions):

            if action == "min":

                vals = getAnnotationValues(
                    filtered,
                    field,
                    delimiter=delimiter,
                )

                copy_ann[field] = "%.12g" % min(
                    [float(x or 0) for x in vals]
                )

            elif action == "max":

                vals = getAnnotationValues(
                    filtered,
                    field,
                    delimiter=delimiter,
                )

                copy_ann[field] = "%.12g" % max(
                    [float(x or 0) for x in vals]
                )

            elif action == "sum":

                vals = getAnnotationValues(
                    filtered,
                    field,
                    delimiter=delimiter,
                )

                copy_ann[field] = "%.12g" % sum(
                    [float(x or 0) for x in vals]
                )

            elif action == "set":

                vals = annotationConsensus(
                    filtered,
                    field,
                    delimiter=delimiter,
                )

                copy_ann[field] = vals["set"]

                copy_ann[f"{field}_COUNT"] = vals["count"]

            elif action == "majority":

                vals = annotationConsensus(
                    filtered,
                    field,
                    delimiter=delimiter,
                )

                copy_ann[field] = vals["cons"]

                copy_ann[f"{field}_FREQ"] = vals["freq"]

    # -----------------------------
    # Final annotations
    # -----------------------------

    cons_ann = OrderedDict([
        ("ID", group_id),
        ("CONSCOUNT", cons_count),
    ])

    if primer_ann is not None:
        cons_ann = mergeAnnotation(
            cons_ann,
            primer_ann,
            delimiter=delimiter,
        )

    if copy_ann:
        cons_ann = mergeAnnotation(
            cons_ann,
            copy_ann,
            delimiter=delimiter,
        )

    consensus.id = consensus.name = flattenAnnotation(
        cons_ann,
        delimiter=delimiter,
    )

    consensus.description = ""

    return consensus, log

def build_consensus(
    seq_file,
    barcode_field=default_barcode_field,
    min_count=default_consensus_min_count,
    min_freq=default_consensus_min_freq,
    min_qual=default_consensus_min_qual,
    primer_field=None,
    primer_freq=None,
    max_gap=None,
    max_error=None,
    max_diversity=None,
    copy_fields=None,
    copy_actions=None,
    dependent=False,
    out_file=None,
    out_args=None,
):
    """
    Synchronous replacement for BuildConsensus.buildConsensus
    """
    merged_out_args = dict(default_out_args)
    if out_args:
        merged_out_args.update(out_args)
    out_args = merged_out_args

    log = OrderedDict()

    log["START"] = "BuildConsensus"
    log["FILE"] = seq_file

    printLog(log)

    # -----------------------------
    # Input type
    # -----------------------------

    in_type = getFileType(seq_file)

    if in_type == "fastq":

        cons_func = qualityConsensus

        cons_args = {
            "min_qual": min_qual,
            "min_freq": min_freq,
            "dependent": dependent,
        }

    elif in_type == "fasta":

        cons_func = frequencyConsensus

        cons_args = {
            "min_freq": min_freq,
        }

    else:
        raise ValueError(
            "Input must be FASTA or FASTQ"
        )

    # -----------------------------
    # Read sequences
    # -----------------------------

    seq_records = SeqIO.to_dict(
        readSeqFile(seq_file)
    )

    # -----------------------------
    # Group sequences
    # -----------------------------

    grouped = indexSeqSets(
        seq_records,
        field=barcode_field,
        delimiter=out_args["delimiter"],
    )

    # -----------------------------
    # Output
    # -----------------------------

    if out_file is None:

        out_handle = getOutputHandle(
            seq_file,
            "consensus-pass",
            out_dir=out_args["out_dir"],
            out_name=out_args["out_name"],
            out_type=out_args["out_type"] or in_type,
        )

    else:

        out_handle = open(out_file, "w")

    pass_count = 0
    fail_count = 0

    # -----------------------------
    # Process groups
    # -----------------------------

    for group_id, seq_keys in grouped.items():
        seq_list = [
                seq_records[k]
                for k in seq_keys
            ]
        consensus, group_log = build_consensus_group(
            seq_list=seq_list,
            group_id=group_id,
            cons_func=cons_func,
            cons_args=cons_args,
            min_count=min_count,
            primer_field=primer_field,
            primer_freq=primer_freq,
            max_gap=max_gap,
            max_error=max_error,
            max_diversity=max_diversity,
            copy_fields=copy_fields,
            copy_actions=copy_actions,
            delimiter=out_args["delimiter"],
        )

        if consensus is None:
            fail_count += 1
            continue

        SeqIO.write(
            consensus,
            out_handle,
            out_args["out_type"] or in_type,
        )

        pass_count += 1

    out_handle.close()

    # -----------------------------
    # Final log
    # -----------------------------

    final_log = OrderedDict()

    final_log["GROUPS"] = len(grouped)
    final_log["PASS"] = pass_count
    final_log["FAIL"] = fail_count
    final_log["END"] = "BuildConsensus"

    printLog(final_log)

    return out_handle.name