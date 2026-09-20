# app/singlecell/tasks.py
"""
Celery task for the single-cell pipeline: [Assemble ->] Parse -> Validate ->
Write outputs.

Mirrors app/workers/celery_worker.py::process_file's status/error conventions
exactly, so the frontend's existing job-status polling (useJobProgress.ts)
works unmodified: "PROCESSING <name> STEP n OF N" / "DONE" / "FAILED".

The optional leading Assemble stage exists for the raw-read formats: a TRUST4
run can take hours, and without its own step the whole thing would look like a
stalled "Parse".
"""

import json
import logging
import time
import traceback
from pathlib import Path

from app.core.job_notifications import notify_job_finished
from app.core.job_store import update_job
from app.core.provenance import file_fingerprint, software_versions
from app.singlecell.errors import SingleCellAdapterError
from app.singlecell.fasta_generator import write_outputs, write_source_annotations
from app.singlecell.models import Trust4Options
from app.singlecell.registry import AdapterContext, get_adapter
from app.singlecell.validator import validate_records
from app.workers.celery_worker import celery

logger = logging.getLogger("celery_worker")

_CORE_STAGES = ("Parse", "Validate", "Write")


@celery.task
def process_single_cell_input(
    role_paths,
    outputs_dir,
    job_id,
    session_id,
    format_id,
    trust4_options=None,
    allow_productive=False,
    barcode_header_regex=None,
    role_names=None,
):
    try:
        options = Trust4Options(**(trust4_options or {}))
        # TRUST4 intermediates go beside the outputs, inside the job
        # workspace, so they're removed when the job's files are.
        work_dir = Path(outputs_dir).parent
        adapter = get_adapter(
            format_id,
            AdapterContext(
                trust4_options=options,
                work_dir=work_dir,
                allow_productive=allow_productive,
                barcode_header_regex=barcode_header_regex,
            ),
        )

        stages = [*adapter.pre_stages, *_CORE_STAGES]
        total = len(stages)
        completed: list[dict] = []

        def advance(next_index: int):
            """Mark everything before next_index done and announce it."""
            while len(completed) < next_index:
                completed.append(
                    {"index": len(completed), "name": stages[len(completed)]}
                )
            update_job(session_id, job_id, {
                "status": f"PROCESSING {stages[next_index]} STEP "
                          f"{next_index + 1} OF {total}",
                "step_stats": list(completed),
            })

        # An adapter with a pre-stage (TRUST4 assembly) reports when that
        # stage finishes, which moves the job on to Parse mid-call.
        adapter.on_stage_complete = lambda name: advance(stages.index(name) + 1)

        advance(0)
        records = adapter.parse({role: Path(p) for role, p in role_paths.items()})

        advance(stages.index("Validate"))
        records, warnings = validate_records(records)
        warnings = [*adapter.warnings, *warnings]

        advance(stages.index("Write"))
        fasta_path, tsv_path = write_outputs(records, Path(outputs_dir))
        # Lossless sidecar: the upstream annotation fields the normalized
        # output omits, keyed on the same sequence_id.
        annotations_path = write_source_annotations(
            records,
            adapter.source_annotations,
            adapter.source_annotation_fields,
            Path(outputs_dir),
        )
        _write_provenance(
            Path(outputs_dir),
            format_id=format_id,
            role_paths=role_paths,
            role_names=role_names or {},
            options={
                "trust4_options": trust4_options,
                "allow_productive": allow_productive,
                "barcode_header_regex": barcode_header_regex,
            },
            parse_report=adapter.parse_report,
            records=records,
            warnings=warnings,
            outputs=[p for p in (fasta_path, tsv_path, annotations_path) if p],
            source_annotations={
                "file": annotations_path.name if annotations_path else None,
                "read_from": list(adapter.source_annotation_origin),
                "fields": list(adapter.source_annotation_fields),
                "rows": len(adapter.source_annotations),
            },
        )

        update_job(session_id, job_id, {
            "status": "DONE",
            "output_file": str(fasta_path),
            "metadata_file": str(tsv_path),
            "source_annotations_file": str(annotations_path) if annotations_path else None,
            "record_count": len(records),
            "cell_count": len({r.cell_id for r in records}),
            "parse_report": adapter.parse_report,
            "warnings": warnings,
            "step_stats": [
                {"index": i, "name": name} for i, name in enumerate(stages)
            ],
        })
        # No-op unless this job carries a tracking code; see
        # app/core/job_notifications.py.
        notify_job_finished(session_id, job_id, succeeded=True)
    except SingleCellAdapterError as e:
        update_job(session_id, job_id, {"status": "FAILED", "error": str(e)})
        notify_job_finished(session_id, job_id, succeeded=False, error=str(e))
    except Exception as e:
        logger.error("Single-cell job %s failed: %s", job_id, traceback.format_exc())
        update_job(session_id, job_id, {
            "status": "FAILED",
            "error": f"Processing failed: {e}",
        })
        notify_job_finished(
            session_id, job_id, succeeded=False, error=f"Processing failed: {e}"
        )


def _write_provenance(
    outputs_dir: Path,
    *,
    format_id,
    role_paths,
    role_names,
    options,
    parse_report,
    records,
    warnings,
    outputs,
    source_annotations,
):
    """
    provenance.json beside final.fasta / metadata.tsv: which uploaded files
    (by name, size and SHA-256), which adapter options and which software
    versions produced this output, and the parse counts behind it.

    Every output sequence_id is the source file's own record identifier, and
    the upstream annotation fields the normalized output omits are written
    out beside it as source_annotations.tsv, whose checksum is recorded here
    together with the inputs' -- so recovering an omitted annotation does not
    depend on the uploader still holding the original file.
    """
    document = {
        "schema": "airrprep.singlecell.normalized",
        "schema_version": 1,
        "fields": list(records[0].model_fields) if records else [],
        "format_id": format_id,
        "created_at": time.time(),
        "software": software_versions(),
        "inputs": [
            {"role": role, **file_fingerprint(path, role_names.get(role))}
            for role, path in sorted(role_paths.items())
        ],
        "options": options,
        "parse_report": parse_report,
        "records": len(records),
        "cells": len({r.cell_id for r in records}),
        "warnings": warnings,
        "source_annotations": source_annotations,
        "outputs": [file_fingerprint(p) for p in outputs],
    }
    path = outputs_dir / "provenance.json"
    path.write_text(json.dumps(document, indent=2), encoding="utf-8")
    return path
