import pandas as pd
from Bio import SeqIO
from pathlib import Path

# ============================================================
# PATHS
# ============================================================

input_csv = Path("sc5p_v2_hs_PBMC_10k_t_filtered_contig_annotations.csv")
input_fasta = Path("sc5p_v2_hs_PBMC_10k_t_filtered_contig.fasta")

output_fasta = Path("cell_ranger_filter\\final (1).fasta")
output_metadata = Path("cell_ranger_filter\\metadata (1).tsv")


# ============================================================
# LOAD DATA
# ============================================================

input_df = pd.read_csv(input_csv)
output_df = pd.read_csv(output_metadata, sep="\t")


# ============================================================
# STEP 7 — SEQUENCE VALIDATION
# ============================================================

print("=" * 70)
print("STEP 7 — SEQUENCE VALIDATION")
print("=" * 70)

input_records = {
    record.id: str(record.seq)
    for record in SeqIO.parse(input_fasta, "fasta")
}

output_records = {
    record.id: str(record.seq)
    for record in SeqIO.parse(output_fasta, "fasta")
}

common_ids = set(input_records) & set(output_records)

missing_ids = set(input_records) - set(output_records)
extra_ids = set(output_records) - set(input_records)

sequence_mismatches = []

for contig_id in common_ids:

    if input_records[contig_id] != output_records[contig_id]:
        sequence_mismatches.append(contig_id)

print(f"Input FASTA sequences : {len(input_records)}")
print(f"Output FASTA sequences: {len(output_records)}")
print(f"Common IDs            : {len(common_ids)}")
print(f"Missing IDs           : {len(missing_ids)}")
print(f"Extra IDs             : {len(extra_ids)}")
print(f"Sequence mismatches   : {len(sequence_mismatches)}")

sequence_pass = (
    len(missing_ids) == 0
    and len(extra_ids) == 0
    and len(sequence_mismatches) == 0
)

print(
    "\nRESULT:",
    "PASS" if sequence_pass else "FAIL"
)


# ============================================================
# STEP 8 — BARCODE VALIDATION
# ============================================================

print("\n" + "=" * 70)
print("STEP 8 — BARCODE VALIDATION")
print("=" * 70)


# Input:
# contig_id
# barcode

# Output:
# sequence_id
# cell_id

input_barcode = dict(
    zip(
        input_df["contig_id"],
        input_df["barcode"]
    )
)

output_barcode = dict(
    zip(
        output_df["sequence_id"],
        output_df["cell_id"]
    )
)

common_ids = set(input_barcode) & set(output_barcode)

barcode_mismatches = []

for contig_id in common_ids:

    input_value = str(input_barcode[contig_id])
    output_value = str(output_barcode[contig_id])

    if input_value != output_value:
        barcode_mismatches.append(
            (
                contig_id,
                input_value,
                output_value
            )
        )


missing_barcode = set(input_barcode) - set(output_barcode)

extra_barcode = set(output_barcode) - set(input_barcode)


print(f"Input records        : {len(input_barcode)}")
print(f"Output records       : {len(output_barcode)}")
print(f"Common records       : {len(common_ids)}")
print(f"Missing records      : {len(missing_barcode)}")
print(f"Extra records        : {len(extra_barcode)}")
print(f"Barcode mismatches   : {len(barcode_mismatches)}")


barcode_pass = (
    len(missing_barcode) == 0
    and len(barcode_mismatches) == 0
)

print(
    "\nRESULT:",
    "PASS" if barcode_pass else "FAIL"
)


# ============================================================
# STEP 9 — METADATA VALIDATION
# ============================================================

print("\n" + "=" * 70)
print("STEP 9 — METADATA VALIDATION")
print("=" * 70)


metadata_pairs = [
    ("umis", "umi_count"),
    ("reads", "read_count"),
    ("is_cell", "is_cell"),
    ("high_confidence", "high_confidence"),
    ("productive", "productive"),
]


# ------------------------------------------------------------
# Create dictionaries based on contig_id / sequence_id
# ------------------------------------------------------------

input_indexed = input_df.set_index("contig_id")
output_indexed = output_df.set_index("sequence_id")


common_ids = (
    set(input_indexed.index)
    & set(output_indexed.index)
)


print(f"Common records: {len(common_ids)}")


metadata_results = {}


for input_col, output_col in metadata_pairs:

    mismatches = []

    for seq_id in common_ids:

        input_value = input_indexed.loc[
            seq_id, input_col
        ]

        output_value = output_indexed.loc[
            seq_id, output_col
        ]

        # Handle NaN == NaN
        if pd.isna(input_value) and pd.isna(output_value):
            continue

        if str(input_value) != str(output_value):
            mismatches.append(
                (
                    seq_id,
                    input_value,
                    output_value
                )
            )

    passed = len(mismatches) == 0

    metadata_results[input_col] = passed

    print(
        f"{input_col:18s} -> "
        f"{output_col:18s} : "
        f"{'PASS' if passed else 'FAIL'} "
        f"({len(mismatches)} mismatches)"
    )

    if mismatches:

        print("  Examples:")

        for item in mismatches[:5]:

            print(
                f"    {item[0]} | "
                f"input={item[1]} | "
                f"output={item[2]}"
            )


# ============================================================
# INTENTIONALLY DISCARDED ANNOTATIONS
# ============================================================

print("\n" + "=" * 70)
print("INTENTIONALLY DISCARDED ANNOTATIONS")
print("=" * 70)

discarded_columns = [
    "chain",
    "v_gene",
    "d_gene",
    "j_gene",
    "c_gene",
    "cdr3",
    "cdr3_nt",
    "raw_clonotype_id",
    "raw_consensus_id",
]

for column in discarded_columns:

    if column in input_df.columns:

        print(
            f"{column:20s} : "
            "Present in Cell Ranger / not present in standardized output"
        )


# ============================================================
# FINAL RESULT
# ============================================================

print("\n" + "=" * 70)
print("FINAL VALIDATION SUMMARY")
print("=" * 70)

all_metadata_pass = all(
    metadata_results.values()
)

overall_pass = (
    sequence_pass
    and barcode_pass
    and all_metadata_pass
)

print(
    f"STEP 7 — Sequence      : "
    f"{'PASS' if sequence_pass else 'FAIL'}"
)

print(
    f"STEP 8 — Barcode       : "
    f"{'PASS' if barcode_pass else 'FAIL'}"
)

for field, result in metadata_results.items():

    print(
        f"        {field:18s}: "
        f"{'PASS' if result else 'FAIL'}"
    )

print("\n" + "-" * 70)

print(
    "OVERALL RESULT:",
    "PASS" if overall_pass else "FAIL"
)