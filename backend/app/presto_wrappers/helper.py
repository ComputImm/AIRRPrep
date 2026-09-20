from Bio import SeqIO
from presto.IO import getFileType
from presto.Multiprocessing import SeqData


def _process_sequences(
    seq_file,
    output_pass,
    output_fail,
    process_func,
    process_args,
    file_type=None
):
    # Real pRESTO detects fasta vs fastq from the file itself (getFileType)
    # rather than trusting a caller-supplied guess; a hardcoded "fastq"
    # default here made every FASTA-input MaskPrimers step raise inside
    # Bio.SeqIO the moment the pipeline's lane wasn't fastq.
    file_type = file_type or getFileType(seq_file)

    passed = []
    failed = []
    for record in SeqIO.parse(seq_file, file_type):

        data = SeqData(record.id, record)

        result = process_func(data, **process_args)

        if result.valid:
            passed.append(result.results)
        else:
            failed.append(record)

    SeqIO.write(passed, output_pass, file_type)
    SeqIO.write(failed, output_fail, file_type)

    return {
        "pass": output_pass,
        "fail": output_fail,
        "pass_count": len(passed),
        "fail_count": len(failed)
    }


def resolve_uploaded_file(file_id):
    """Absolute path of an uploaded file_id (primer / reference / offset table)."""
    from app.core.file_store import get_file

    stored = get_file(file_id)
    if stored is None:
        raise ValueError(f"File not found: {file_id}")
    return stored.path
