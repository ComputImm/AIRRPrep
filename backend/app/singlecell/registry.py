# app/singlecell/registry.py
"""format_id -> adapter factory, the single-cell equivalent of
app/pipeline/registry.py's PIPELINE_FUNCTIONS mapping.

Factories take an AdapterContext rather than no arguments so the two
TRUST4-backed adapters can receive their run options and a workspace
directory; the file-only adapters simply ignore it.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from app.singlecell.adapters.bam_adapter import BamAdapter
from app.singlecell.adapters.base import SingleCellAdapter
from app.singlecell.adapters.cellranger_adapter import CellRangerAdapter
from app.singlecell.adapters.fastq_adapter import FastqAdapter
from app.singlecell.adapters.generic_fasta_adapter import GenericFastaAdapter
from app.singlecell.adapters.trust4_adapter import Trust4Adapter
from app.singlecell.models import Trust4Options


@dataclass
class AdapterContext:
    trust4_options: Trust4Options | None = None
    #: Where an adapter may write large intermediates (TRUST4 assembly
    #: output). None means "nowhere in particular" — only the /validate path,
    #: which never assembles, leaves this unset.
    work_dir: Path | None = None
    #: Opt-in for carrying Cell Ranger's `productive` call through. Off by
    #: default: it is annotation-derived, so the spec keeps it null unless the
    #: user explicitly asks for it.
    allow_productive: bool = False
    #: Regex with one capture group, applied to FASTA headers to recover the
    #: cell barcode. The generic-FASTA alternative to a mapping file.
    barcode_header_regex: str | None = None

    @property
    def options(self) -> Trust4Options:
        return self.trust4_options or Trust4Options()


ADAPTER_FACTORIES: dict[str, Callable[[AdapterContext], SingleCellAdapter]] = {
    "cellranger_vdj_all": lambda ctx: CellRangerAdapter(
        "all_contig", allow_productive=ctx.allow_productive
    ),
    "cellranger_vdj_filtered": lambda ctx: CellRangerAdapter(
        "filtered_contig", allow_productive=ctx.allow_productive
    ),
    "cellranger_airr_tsv": lambda ctx: CellRangerAdapter(
        "airr_tsv", allow_productive=ctx.allow_productive
    ),
    "trust4": lambda ctx: Trust4Adapter(),
    "fastq_10x": lambda ctx: FastqAdapter(
        options=ctx.options, work_dir=ctx.work_dir
    ),
    "bam_10x": lambda ctx: BamAdapter(options=ctx.options, work_dir=ctx.work_dir),
    "generic_fasta": lambda ctx: GenericFastaAdapter(
        barcode_header_regex=ctx.barcode_header_regex
    ),
}


def get_adapter(
    format_id: str, context: AdapterContext | None = None
) -> SingleCellAdapter:
    factory = ADAPTER_FACTORIES.get(format_id)
    if factory is None:
        raise ValueError(f"Unknown single-cell format_id: {format_id}")
    return factory(context or AdapterContext())
