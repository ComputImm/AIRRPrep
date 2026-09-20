# -*- coding: utf-8 -*-
"""
Check that the benchmark inputs (inputs/<run>_{1,2}.fastq, the first 25,000
read pairs of each run) are reproducible from public data.

For each run and mate, the ENA FASTQ (fastq.gz over HTTPS) is streamed and only
its first 25,000 records are read, so a few MB are downloaded rather than the
whole file. Sequences, quality strings and header lines are compared record by
record with the local input, and reported separately: fastq-dump and ENA format
the defline differently, and ENA distributes some runs (here SRR4026043) with a
constant placeholder quality, so for those only the sequences can be checked
against ENA.

    python verify_inputs_ena.py        # writes inputs_ena_verified.json
"""

import gzip
import hashlib
import json
import ssl
import sys
import time
import urllib.request
from pathlib import Path

BENCH = Path(__file__).resolve().parent
INPUTS = BENCH / "inputs"
RECORDS = 25_000

ENA = {
    "SRR4026043": "https://ftp.sra.ebi.ac.uk/vol1/fastq/SRR402/003/SRR4026043/SRR4026043_{m}.fastq.gz",
    "ERR346600": "https://ftp.sra.ebi.ac.uk/vol1/fastq/ERR346/ERR346600/ERR346600_{m}.fastq.gz",
    "SRR1383456": "https://ftp.sra.ebi.ac.uk/vol1/fastq/SRR138/006/SRR1383456/SRR1383456_{m}.fastq.gz",
}


def records(lines):
    it = iter(lines)
    for header in it:
        seq, plus, qual = next(it), next(it), next(it)
        yield header.rstrip("\r\n"), seq.rstrip("\r\n"), qual.rstrip("\r\n")


def remote_records(url, n, attempts=12):
    last = None
    for _ in range(attempts):
        try:
            ctx = ssl.create_default_context()
            with urllib.request.urlopen(url, timeout=120, context=ctx) as resp:
                with gzip.GzipFile(fileobj=resp) as gz:
                    lines = (raw.decode("ascii") for raw in gz)
                    out = []
                    for rec in records(lines):
                        out.append(rec)
                        if len(out) == n:
                            return out
                    return out
        except Exception as e:  # flaky connection: retry from the start
            last = e
            time.sleep(5)
    raise RuntimeError(f"{url}: {last}")


def main():
    report = {}
    all_ok = True
    for run, pattern in ENA.items():
        for m in (1, 2):
            local_path = INPUTS / f"{run}_{m}.fastq"
            local = list(records(local_path.open()))
            remote = remote_records(pattern.format(m=m), RECORDS)
            same_seq = sum(a[1] == b[1] for a, b in zip(local, remote))
            same_qual = sum(a[2] == b[2] for a, b in zip(local, remote))
            same_header = sum(a[0] == b[0] for a, b in zip(local, remote))
            ena_placeholder_quality = all(len(set(b[2])) == 1 for b in remote[:1000])
            entry = {
                "local_records": len(local),
                "ena_records_read": len(remote),
                "identical_sequence": same_seq,
                "identical_quality": same_qual,
                "identical_header": same_header,
                "ena_quality_is_placeholder": ena_placeholder_quality,
                "local_sha256": hashlib.sha256(local_path.read_bytes()).hexdigest(),
                "example_headers": {"local": local[0][0], "ena": remote[0][0]},
                "ena_url": pattern.format(m=m),
            }
            ok = len(local) == len(remote) == same_seq == RECORDS and (
                same_qual == RECORDS or ena_placeholder_quality
            )
            all_ok &= ok
            report[f"{run}_{m}"] = entry
            print(f"{run}_{m}: sequence {same_seq}/{len(local)}, quality {same_qual}"
                  f"{' (ENA quality is a placeholder)' if ena_placeholder_quality else ''}, "
                  f"headers {same_header} -> {'OK' if ok else 'MISMATCH'}", flush=True)
    (BENCH / "inputs_ena_verified.json").write_text(json.dumps(report, indent=2))
    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
