# app/singlecell/adapters/_util.py
"""Small shared helpers used by multiple adapters."""

import gzip
from pathlib import Path

from Bio import SeqIO


def read_fasta_dict(path: Path) -> dict[str, str]:
    """Read a FASTA file into {record_id: sequence}."""
    return {rec.id: str(rec.seq) for rec in SeqIO.parse(str(path), "fasta")}


def read_fasta_with_headers(path: Path) -> list[tuple[str, str, str]]:
    """Read a FASTA into [(record_id, full_header_line, sequence)].

    Needed wherever the barcode has to be recovered from the header itself
    rather than from a companion table — read_fasta_dict drops everything
    after the first whitespace, which is exactly where such barcodes live.
    """
    return [
        (rec.id, rec.description, str(rec.seq))
        for rec in SeqIO.parse(str(path), "fasta")
    ]


def read_bam_reference_names(path: Path, limit: int = 5000) -> list[str]:
    """Read the @SQ reference names out of a BAM header.

    BGZF is gzip-compatible, so the header decompresses with the stdlib and
    no pysam/samtools dependency is needed. Reads only as far as the
    reference list, and stops after `limit` names — enough to tell what
    coordinate space the file is aligned to, which is all callers want.
    """
    with path.open("rb") as fh:
        gz = gzip.GzipFile(fileobj=fh)
        buf = gz.read(1 << 20)
        if buf[:4] != b"BAM\x01":
            raise ValueError("Not a BAM file (missing BAM\\1 magic)")

        def ensure(n: int) -> None:
            nonlocal buf
            while len(buf) < n:
                chunk = gz.read(1 << 20)
                if not chunk:
                    raise ValueError("BAM header ended unexpectedly")
                buf += chunk

        ensure(8)
        l_text = int.from_bytes(buf[4:8], "little")
        offset = 8 + l_text
        ensure(offset + 4)
        n_ref = int.from_bytes(buf[offset:offset + 4], "little")
        offset += 4

        names: list[str] = []
        for _ in range(min(n_ref, limit)):
            ensure(offset + 4)
            l_name = int.from_bytes(buf[offset:offset + 4], "little")
            offset += 4
            ensure(offset + l_name + 4)
            # l_name includes the trailing NUL.
            names.append(buf[offset:offset + l_name - 1].decode("ascii", "replace"))
            offset += l_name + 4
        return names


def read_reference_chromosomes(fasta: Path) -> set[str]:
    """Chromosome names a TRUST4 coordinate reference (bcrtcr.fa) declares.

    Header format is `>GENE chrN start end strand`, so the chromosome is the
    second whitespace-separated field.
    """
    chromosomes: set[str] = set()
    with fasta.open() as fh:
        for line in fh:
            if not line.startswith(">"):
                continue
            parts = line[1:].split()
            if len(parts) >= 2:
                chromosomes.add(parts[1])
    return chromosomes


def parse_bool(value: str | None) -> bool | None:
    if value is None:
        return None
    v = value.strip().lower()
    if v in ("true", "t", "1", "yes"):
        return True
    if v in ("false", "f", "0", "no"):
        return False
    return None


def parse_int(value: str | None) -> int | None:
    if value is None:
        return None
    v = value.strip()
    if not v:
        return None
    try:
        return int(float(v))
    except ValueError:
        return None


def first_present(row: dict, keys: list[str]) -> str | None:
    """Return the first non-empty value among `keys` in `row` (case-insensitive)."""
    lower_row = {k.lower(): v for k, v in row.items()}
    for key in keys:
        value = lower_row.get(key.lower())
        if value not in (None, ""):
            return value
    return None
