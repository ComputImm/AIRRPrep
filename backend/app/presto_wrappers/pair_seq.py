import os

from collections import OrderedDict
from time import time

from Bio import SeqIO

from presto.Defaults import (
    default_coord,
    default_out_args,
)

from presto.Annotation import (
    collapseAnnotation,
    parseAnnotation,
    flattenAnnotation,
    mergeAnnotation,
    getCoordKey,
)

from presto.IO import (
    getFileType,
    readSeqFile,
    countSeqFile,
    getOutputHandle,
    printLog,
    printMessage,
    printProgress,
)
def pair_seq(
    seq_file_1,
    seq_file_2,
    fields_1=None,
    fields_2=None,
    action=None,
    coord_type=default_coord,
    out_args=None,
):
    """
    Pure callable wrapper for pRESTO PairSeq
    """
    merged_out_args = dict(default_out_args)
    if out_args:
        merged_out_args.update(out_args)
    out_args = merged_out_args

    # -----------------------------------
    # Coord key function
    # -----------------------------------

    def key_func(x):
        return getCoordKey(
            x,
            coord_type=coord_type,
            delimiter=out_args["delimiter"],
        )

    # -----------------------------------
    # Logging
    # -----------------------------------

    log = OrderedDict()

    log["START"] = "PairSeq"
    log["FILE1"] = os.path.basename(seq_file_1)
    log["FILE2"] = os.path.basename(seq_file_2)

    printLog(log)

    # -----------------------------------
    # Output types
    # -----------------------------------

    if 'out_type' not in out_args or out_args["out_type"] is None:

        out_type_1 = getFileType(seq_file_1)
        out_type_2 = getFileType(seq_file_2)

    else:

        out_type_1 = out_type_2 = out_args["out_type"]

    # -----------------------------------
    # Output names
    # -----------------------------------

    # out_name is the run-wide stem the executor picked (dataset, tracking
    # code, step number); honouring it is what keeps PairSeq's two outputs
    # named like every other step's instead of "paired-1"/"paired-2".
    base_name = out_args.get("out_name")

    # getOutputHandle documents out_name as the bare stem -- it joins out_dir
    # on internally. Baking out_dir into this string too (as a prior version
    # did) double-joined the directory; that happened to be masked on Windows
    # only because out_dir is always an absolute, drive-lettered path here, so
    # os.path.join silently discards the first half when the second already
    # has a drive+root. Anything relative would break it for real.
    if base_name:

        out_name_1 = f"{base_name}_R1"
        out_name_2 = f"{base_name}_R2"

    else:

        out_name_1 = "paired-1"
        out_name_2 = "paired-2"

    # -----------------------------------
    # Read/index files
    # -----------------------------------

    start_time = time()

    printMessage(
        "Indexing files",
        start_time=start_time,
    )

    seq_count_1 = countSeqFile(seq_file_1)

    seq_dict_1 = readSeqFile(
        seq_file_1,
        index=True,
        key_func=key_func,
    )

    seq_count_2 = countSeqFile(seq_file_2)

    seq_iter_2 = readSeqFile(
        seq_file_2,
        index=False,
    )

    printMessage(
        "Done",
        start_time=start_time,
        end=True,
    )

    # -----------------------------------
    # Open outputs
    # -----------------------------------

    pass_handle_1 = getOutputHandle(
        seq_file_1,
        "pair-pass",
        out_dir=out_args["out_dir"],
        out_name=out_name_1,
        out_type=out_type_1,
        gzip_output=out_args.get("gzip_output", False),
    )

    pass_handle_2 = getOutputHandle(
        seq_file_2,
        "pair-pass",
        out_dir=out_args["out_dir"],
        out_name=out_name_2,
        out_type=out_type_2,
        gzip_output=out_args.get("gzip_output", False),
    )

    fail_handle_1 = None
    fail_handle_2 = None

    pass_keys = []

    if out_args["failed"]:

        fail_handle_1 = getOutputHandle(
            seq_file_1,
            "pair-fail",
            out_dir=out_args["out_dir"],
            out_name=out_name_1,
            out_type=out_type_1,
            gzip_output=out_args.get("gzip_output", False),
        )

        fail_handle_2 = getOutputHandle(
            seq_file_2,
            "pair-fail",
            out_dir=out_args["out_dir"],
            out_name=out_name_2,
            out_type=out_type_2,
            gzip_output=out_args.get("gzip_output", False),
        )

    # -----------------------------------
    # Pairing loop
    # -----------------------------------

    start_time = time()

    rec_count = 0
    pair_count = 0

    for seq_2 in seq_iter_2:

        printProgress(
            rec_count,
            seq_count_2,
            0.05,
            start_time=start_time,
        )

        rec_count += 1

        coord_2 = getCoordKey(
            seq_2.id,
            coord_type=coord_type,
            delimiter=out_args["delimiter"],
        )

        seq_1 = seq_dict_1.get(coord_2)

        # -----------------------------------
        # Found pair
        # -----------------------------------

        if seq_1 is not None:

            pair_count += 1

            if fields_1 is not None or fields_2 is not None:

                ann_1 = parseAnnotation(
                    seq_1.description,
                    delimiter=out_args["delimiter"],
                )

                ann_2 = parseAnnotation(
                    seq_2.description,
                    delimiter=out_args["delimiter"],
                )

                # -----------------------------
                # Copy file1 -> file2
                # -----------------------------

                if fields_1 is not None:

                    copy_ann = OrderedDict([
                        (k, v)
                        for k, v in ann_1.items()
                        if k in fields_1
                    ])

                    merge_ann = mergeAnnotation(
                        ann_2,
                        copy_ann,
                        prepend=True,
                        delimiter=out_args["delimiter"],
                    )

                    if action is not None:

                        merge_ann = collapseAnnotation(
                            merge_ann,
                            action,
                            fields=fields_1,
                            delimiter=out_args["delimiter"],
                        )

                    seq_2.id = flattenAnnotation(
                        merge_ann,
                        delimiter=out_args["delimiter"],
                    )

                    seq_2.description = ""

                # -----------------------------
                # Copy file2 -> file1
                # -----------------------------

                if fields_2 is not None:

                    copy_ann = OrderedDict([
                        (k, v)
                        for k, v in ann_2.items()
                        if k in fields_2
                    ])

                    merge_ann = mergeAnnotation(
                        ann_1,
                        copy_ann,
                        prepend=False,
                        delimiter=out_args["delimiter"],
                    )

                    if action is not None:

                        merge_ann = collapseAnnotation(
                            merge_ann,
                            action,
                            fields=fields_2,
                            delimiter=out_args["delimiter"],
                        )

                    seq_1.id = flattenAnnotation(
                        merge_ann,
                        delimiter=out_args["delimiter"],
                    )

                    seq_1.description = ""

            # -----------------------------
            # Write paired
            # -----------------------------

            SeqIO.write(
                seq_1,
                pass_handle_1,
                out_type_1,
            )

            SeqIO.write(
                seq_2,
                pass_handle_2,
                out_type_2,
            )

            if out_args["failed"]:
                pass_keys.append(coord_2)

        # -----------------------------------
        # Unpaired file2
        # -----------------------------------

        else:

            if out_args["failed"]:

                SeqIO.write(
                    seq_2,
                    fail_handle_2,
                    out_type_2,
                )

    # -----------------------------------
    # Final progress
    # -----------------------------------

    printProgress(
        rec_count,
        seq_count_2,
        0.05,
        start_time=start_time,
    )

    # -----------------------------------
    # Unpaired file1
    # -----------------------------------

    if out_args["failed"]:

        start_time = time()

        printMessage(
            "Finding unpaired",
            start_time=start_time,
        )

        pass_keys = set(pass_keys)

        unpaired = set(seq_dict_1).difference(pass_keys)

        for key in unpaired:

            SeqIO.write(
                seq_dict_1[key],
                fail_handle_1,
                out_type_1,
            )

        printMessage(
            "Done",
            start_time=start_time,
            end=True,
        )

    # -----------------------------------
    # Final log
    # -----------------------------------

    log = OrderedDict()

    log["OUTPUT1"] = os.path.basename(pass_handle_1.name)
    log["OUTPUT2"] = os.path.basename(pass_handle_2.name)

    log["SEQUENCES1"] = seq_count_1
    log["SEQUENCES2"] = seq_count_2

    log["PASS"] = pair_count

    log["END"] = "PairSeq"

    printLog(log)

    # -----------------------------------
    # Close handles
    # -----------------------------------

    pass_handle_1.close()
    pass_handle_2.close()

    if fail_handle_1:
        fail_handle_1.close()

    if fail_handle_2:
        fail_handle_2.close()

    return [
        (
            pass_handle_1.name,
            pass_handle_2.name,
        )
    ]