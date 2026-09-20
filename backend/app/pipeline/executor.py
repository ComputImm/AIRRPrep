import inspect
from pathlib import Path

from Bio import SeqIO
from presto.Multiprocessing import SeqData

from app.pipeline.presto_params import merge_out_args, sanitize_presto_params

from app.pipeline.sequence_stats import (
    build_step_stats_entry,
    count_sequences,
    count_sequences_across,
    make_lane_stats,
    resolve_output_path,
    stats_from_output_file,
    stats_from_wrapper_result,
)

from app.core.job_store import get_job, is_cancel_requested, update_job
from app.core.naming import (
    MIN_STEM_BUDGET,
    run_prefix,
    stem_budget,
    step_dir_name,
    step_stem,
)
from app.pipeline.contracts import STEP_CONTRACTS
from app.core.job_workspace import JobWorkspace
from app.pipeline.registry import PIPELINE_FUNCTIONS
from app.pipeline.splitting import step_splits_output
from app.pipeline.stream import (
    LANE_R1,
    LANE_R2,
    PipelineStream,
    StreamMode,
    StepStreamBehavior,
    get_step_stream_behavior,
    normalize_step_lanes,
)


FILTER_SEQ_STEPS = {
    "FilterSeq.length",
    "FilterSeq.quality",
    "FilterSeq.missing",
    "FilterSeq.repeats",
    "FilterSeq.trimqual",
    "FilterSeq.maskqual",
}

# Every registered step that is not a record-level FilterSeq filter and not a
# paired / merged stream step goes through run_file_level_step. Derived from the
# registry so a new wrapper only has to be registered once.
FILE_LEVEL_STEPS = {
    name
    for name in PIPELINE_FUNCTIONS
    if name not in FILTER_SEQ_STEPS
    and get_step_stream_behavior(name) == StepStreamBehavior.PER_LANE
}


class JobCancelled(Exception):
    """Raised at a step boundary when the user asked to stop the run."""


def describe_failure(error: BaseException) -> str:
    """
    One readable line for a step that died.

    pRESTO reports fatal problems by printing "ERROR> ..." and calling
    sys.exit, so the exception text arrives with that prefix and often a
    trailing newline. Stripping it is the difference between a status line the
    user can act on and one that looks like a crash dump.
    """
    text = str(error).strip()
    if "ERROR>" in text:
        text = text.split("ERROR>", 1)[1].strip()
    text = " ".join(text.split())
    if not text:
        text = type(error).__name__
    return text[:400]


def produces_table(step: str) -> bool:
    """True for steps whose contract output_type is a TSV, not sequences."""
    return STEP_CONTRACTS.get(step, {}).get("output_type") == "tab"


def run_filter_seq_step(
    input_file,
    output_file,
    step,
    params,
    file_type="fasta",
):
    func = PIPELINE_FUNCTIONS[step]
    sig = inspect.signature(func)
    filtered_params = {k: v for k, v in params.items() if k in sig.parameters}
    before = count_sequences(input_file)
    remaining = 0
    failed = 0

    # Failed records are written to the sibling ``{stem}_fail{suffix}`` file so
    # they can be downloaded from the API (the step-download endpoint resolves
    # this exact path for ``kind=fail``).
    out_path = Path(output_file)
    fail_path = out_path.with_name(f"{out_path.stem}_fail{out_path.suffix}")

    with open(output_file, "w") as out_handle, open(fail_path, "w") as fail_handle:
        for record in SeqIO.parse(input_file, file_type):
            data = SeqData(record.id, record)
            try:
                result = func(data, **filtered_params)
            except Exception:
                # Some pRESTO filters (e.g. FilterSeq.repeats) raise on empty or
                # all-missing sequences ("max() arg is an empty sequence").
                # Treat such records as failed instead of aborting the step.
                failed += 1
                SeqIO.write(record, fail_handle, file_type)
                continue

            if result.valid:
                SeqIO.write(result.results, out_handle, file_type)
                remaining += 1
            else:
                failed += 1
                SeqIO.write(record, fail_handle, file_type)

    # Drop the fail file when nothing failed, so the UI never offers an empty
    # download.
    if failed == 0:
        try:
            fail_path.unlink()
        except OSError:
            pass

    if before == 0:
        before = remaining + failed

    return make_lane_stats(before=before, remaining=remaining, failed=failed)


def run_file_level_step(input_file, output_file, step, params):
    func = PIPELINE_FUNCTIONS[step]
    sig = inspect.signature(func)
    bound = sanitize_presto_params(params)
    bound["seq_file"] = input_file
    bound["out_file"] = output_file
    filtered = {
        key: value for key, value in bound.items() if key in sig.parameters
    }
    before = count_sequences(input_file)
    result = func(**filtered)

    stats = stats_from_wrapper_result(before, result)
    if stats is None:
        output_path = resolve_output_path(result, output_file)
        stats = stats_from_output_file(before, output_path)

    if isinstance(result, dict) and "primary" in result:
        return result, stats
    if isinstance(result, dict) and "pass" in result:
        return result, stats
    return result, stats


def collect_parts(result: object, lane: str | None = None) -> list[dict]:
    """
    Turn a wrapper's ``parts`` into the entries stored on the step stats.

    Only fan-out steps report parts (SplitSeq, see its wrapper module). Each
    entry carries the on-disk path for the download endpoint plus what the UI
    shows: the label pRESTO gave the part, its file name, and how many records
    landed in it.

    A step that wrote a single file has no parts to list -- SplitSeq.sort
    without max_count, or a one-size sample, produce exactly one output, and
    listing it as "part 1" would make an ordinary step look like a fan-out.
    """
    if not isinstance(result, dict):
        return []
    if len(result.get("outputs") or []) < 2:
        return []

    entries = []
    for part in result.get("parts") or []:
        path = Path(str(part["path"]))
        label = str(part.get("label") or path.stem)
        entries.append({
            # Prefixed on both lanes when a step split two of them, so "part1"
            # is never ambiguous between R1 and R2.
            "label": f"{lane}:{label}" if lane else label,
            "lane": lane,
            "name": path.name,
            "path": str(path),
            "sequences": count_sequences(str(path)),
        })
    return entries


def run_split_seq_samplepair_step(
    stream: PipelineStream,
    step_dir: Path,
    params: dict,
    out_stem: str,
) -> tuple[str, str, dict[str, dict[str, int]], dict[str, str], list[dict]]:
    func = PIPELINE_FUNCTIONS["SplitSeq.samplepair"]
    sig = inspect.signature(func)
    bound = sanitize_presto_params(params)
    bound["seq_file_1"] = stream.r1
    bound["seq_file_2"] = stream.r2
    bound["out_args"] = merge_out_args(
        step_dir,
        {"out_name": out_stem, **(bound.pop("out_args", None) or {})},
    )
    filtered = {
        key: value for key, value in bound.items() if key in sig.parameters
    }
    before_r1 = count_sequences(stream.r1)
    before_r2 = count_sequences(stream.r2)
    try:
        result = func(**filtered)
    except SystemExit as e:
        raise RuntimeError(str(e).strip() or "SplitSeq.samplepair failed") from e

    out1 = str(result["primary"])
    out2 = str(result["primary_r2"])
    remaining_r1 = count_sequences(out1)
    remaining_r2 = count_sequences(out2)
    by_lane = {
        LANE_R1: make_lane_stats(before_r1, remaining_r1, before_r1 - remaining_r1),
        LANE_R2: make_lane_stats(before_r2, remaining_r2, before_r2 - remaining_r2),
    }
    return out1, out2, by_lane, {LANE_R1: out1, LANE_R2: out2}, collect_parts(result)


def run_single_step(
    input_file,
    output_file,
    step,
    params,
    file_type="fasta",
):
    """Run one per-lane step; returns (lane stats, the raw wrapper result)."""
    if step in FILTER_SEQ_STEPS:
        stats = run_filter_seq_step(
            input_file=input_file,
            output_file=output_file,
            step=step,
            params=params,
            file_type=file_type,
        )
        return stats, None
    if step in FILE_LEVEL_STEPS:
        result, stats = run_file_level_step(
            input_file=input_file,
            output_file=output_file,
            step=step,
            params=params,
        )
        # A true fan-out spread the reads over every part, so counting only the
        # one the pipeline would continue on would report the rest as lost.
        # A bounded split that is *not* a fan-out (SplitSeq.group with a
        # threshold) is a filter -- there the discarded part is genuinely
        # removed, so the default primary-only count is the honest one.
        if (
            step_splits_output(step, params)
            and isinstance(result, dict)
            and len(result.get("outputs") or []) > 1
        ):
            # Clamped because independently drawn samples can overlap, and a
            # retention figure above 100% would just look like a bug.
            total = count_sequences_across(result["outputs"])
            stats = make_lane_stats(
                before=stats["before"],
                remaining=min(stats["before"], total) if stats["before"] else total,
                failed=0,
            )
        return stats, result
    raise ValueError(f"Unknown pipeline step type: {step}")


def _lane_output_path(
    step_dir: Path,
    lane: str,
    file_type: str,
    final_output: str | None,
    stream: PipelineStream,
    step: str,
    out_stem: str,
) -> str:
    """
    Where one lane of one step writes.

    Intermediates land in the step's directory under the run-wide stem plus the
    step number, step name and lane, so a downloaded file still says which run,
    which step and which read it came from. The final step writes into
    ``outputs/`` under the run stem alone.
    """
    table_out = produces_table(step)
    ext = ".tsv" if table_out else f".{file_type}"

    if final_output and stream.mode == StreamMode.SINGLE:
        if table_out:
            return str(Path(final_output).with_suffix(".tsv"))
        return final_output
    if final_output and stream.mode == StreamMode.DUAL:
        base = Path(final_output)
        suffix = ".tsv" if table_out else base.suffix
        return str(base.parent / f"{base.stem}_{lane}{suffix}")
    return str(step_dir / f"{out_stem}_{lane}{ext}")


def run_pair_seq_step(
    stream: PipelineStream,
    step_dir: Path,
    params: dict,
    out_stem: str,
) -> tuple[str, str, dict[str, dict[str, int]], dict[str, str]]:
    func = PIPELINE_FUNCTIONS["PairSeq.default"]
    sig = inspect.signature(func)
    bound = sanitize_presto_params(params)
    bound["seq_file_1"] = stream.r1
    bound["seq_file_2"] = stream.r2
    bound["out_args"] = merge_out_args(
        step_dir,
        {"out_name": out_stem, **(bound.pop("out_args", None) or {})},
    )
    filtered = {
        key: value for key, value in bound.items() if key in sig.parameters
    }

    before_r1 = count_sequences(stream.r1)
    before_r2 = count_sequences(stream.r2)

    try:
        result = func(**filtered)
    except SystemExit as e:
        raise RuntimeError(str(e).strip() or "PairSeq failed") from e

    out1, out2 = result[0]
    remaining = count_sequences(out1)
    by_lane = {
        LANE_R1: make_lane_stats(before_r1, remaining, before_r1 - remaining),
        LANE_R2: make_lane_stats(before_r2, remaining, before_r2 - remaining),
    }
    output_paths = {LANE_R1: str(out1), LANE_R2: str(out2)}
    return str(out1), str(out2), by_lane, output_paths


def run_assemble_seq_step(
    stream: PipelineStream,
    output_file: str,
    params: dict,
    file_type: str,
    step_name: str,
) -> tuple[dict, dict[str, dict[str, int]], dict[str, str]]:
    func = PIPELINE_FUNCTIONS[step_name]
    sig = inspect.signature(func)
    bound = sanitize_presto_params(params)
    swap = bool(bound.pop("swap_head_tail", False))
    head = stream.r2 if swap else stream.r1
    tail = stream.r1 if swap else stream.r2
    bound["head_file"] = head
    bound["tail_file"] = tail
    bound["output_file"] = output_file
    bound.setdefault("file_type", file_type)
    filtered = {
        key: value for key, value in bound.items() if key in sig.parameters
    }
    try:
        result = func(**filtered)
    except SystemExit as e:
        raise RuntimeError(str(e).strip() or "AssembleSeq failed") from e

    pairs_before = int(result["pass_count"]) + int(result["fail_count"])
    by_lane = {
        "merged": make_lane_stats(
            before=pairs_before,
            remaining=int(result["pass_count"]),
            failed=int(result["fail_count"]),
        ),
    }
    output_paths = {"merged": str(result["pass"])}
    if result.get("fail"):
        output_paths["merged_fail"] = str(result["fail"])
    return result, by_lane, output_paths


def run_targeted_lanes_step(
    stream: PipelineStream,
    step: str,
    params: dict,
    step_dir: Path,
    file_type: str,
    final_output: str | None,
    target_lanes: list[str],
    out_stem: str,
) -> tuple[PipelineStream, dict[str, dict[str, int]], dict[str, str], list[dict]]:
    updated = stream
    by_lane: dict[str, dict[str, int]] = {}
    output_paths: dict[str, str] = {}
    parts: list[dict] = []

    for lane in target_lanes:
        if lane == LANE_R2 and stream.mode == StreamMode.SINGLE:
            raise ValueError(
                f"Step {step} targets R2 but pipeline has a single input file"
            )

        input_path = updated.path_for_lane(lane)
        output_path = _lane_output_path(
            step_dir, lane, file_type, final_output, stream, step, out_stem
        )

        lane_stats, result = run_single_step(
            input_file=input_path,
            output_file=output_path,
            step=step,
            params=params,
            file_type=file_type,
        )
        by_lane[lane] = lane_stats

        parts.extend(collect_parts(result, lane if len(target_lanes) > 1 else None))

        # Several pRESTO wrappers name their own outputs and never write
        # `output_path` itself: SplitSeq.sort writes "{stem}_sorted", a fan-out
        # writes "{stem}_part000001" and friends, a thresholded group split
        # writes the "atleast" file the pipeline should continue on. Asking the
        # result where the file actually is keeps the recorded path, the
        # sequence counts and the next step's input in agreement -- taking
        # `output_path` on faith left the next step opening a file that was
        # never created. A wrapper that did write `output_path` (FilterSeq,
        # MaskPrimers, ...) resolves back to it unchanged.
        output_path = resolve_output_path(result, output_path)

        output_paths[lane] = output_path
        updated = updated.with_lane_path(lane, output_path)

    return updated, by_lane, output_paths, parts


def _require_dual_stream(stream: PipelineStream, step: str) -> None:
    if stream.mode != StreamMode.DUAL or stream.r2 is None:
        raise ValueError(
            f"{step} requires two active lanes (R1 and R2); "
            "provide two input files and run both lanes before this step"
        )


def run_pipeline_step(
    stream: PipelineStream,
    step_data: dict,
    step_dir: Path,
    file_type: str,
    final_output: str | None,
    out_stem: str,
) -> tuple[PipelineStream, dict[str, dict[str, int]], dict[str, str], list[dict]]:
    step = step_data["name"]
    params = sanitize_presto_params(step_data.get("params", {}))
    behavior = get_step_stream_behavior(step)

    if behavior == StepStreamBehavior.PAIRED_IO:
        _require_dual_stream(stream, step)
        if step == "SplitSeq.samplepair":
            r1_out, r2_out, by_lane, output_paths, parts = (
                run_split_seq_samplepair_step(stream, step_dir, params, out_stem)
            )
        else:
            r1_out, r2_out, by_lane, output_paths = run_pair_seq_step(
                stream, step_dir, params, out_stem
            )
            parts = []
        return (
            PipelineStream(mode=StreamMode.DUAL, r1=r1_out, r2=r2_out),
            by_lane,
            output_paths,
            parts,
        )

    if behavior == StepStreamBehavior.MERGE_PAIRED:
        _require_dual_stream(stream, step)
        out_path = final_output or str(step_dir / f"{out_stem}_assembled.{file_type}")
        result, by_lane, output_paths = run_assemble_seq_step(
            stream, out_path, params, file_type, step
        )
        return (
            PipelineStream(mode=StreamMode.SINGLE, r1=result["pass"]),
            by_lane,
            output_paths,
            [],
        )

    target_lanes = normalize_step_lanes(step_data, stream.mode)
    return run_targeted_lanes_step(
        stream,
        step,
        params,
        step_dir,
        file_type,
        final_output,
        target_lanes,
        out_stem,
    )


def _append_step_stats(session_id: str, job_id: str, entry: dict) -> list[dict]:
    job = get_job(session_id, job_id) or {}
    step_stats = list(job.get("step_stats", []))
    step_stats.append(entry)
    return step_stats


def ends_in_split(steps: list[dict]) -> bool:
    """Whether the run's last step fans out, leaving no single final output."""
    if not steps:
        return False
    last = steps[-1]
    return step_splits_output(last["name"], last.get("params") or {})


def _last_step_index(steps: list[dict]) -> int:
    """
    Index of the step that writes the run's final output.

    Normally the last one. A fan-out step is different: it wrote a set of part
    files that pRESTO named itself, and copying one of them out as "the" final
    output would misrepresent a five-way split as a single result. Such a run
    has no single final output, so nothing is promoted to outputs/.
    """
    return -1 if ends_in_split(steps) else len(steps) - 1


def run_pipeline(
    input_files,
    output_file,
    steps,
    job_id,
    session_id,
    file_type="fasta",
    convert_to_fasta=False,
    run_stem=None,
):
    """
    Execute a pipeline step by step.

    ``run_stem`` is the ``<dataset>_<code>`` prefix every file of this run is
    named after (see app/core/naming.py). It is passed in rather than derived
    here because only the caller knows the uploaded file names and whether the
    run got a tracking code.
    """
    if isinstance(input_files, str):
        input_files = [input_files]

    stream = PipelineStream.from_input_files(input_files)

    workspace = JobWorkspace(session_id=session_id, job_id=job_id)
    workspace.create()

    prefix = run_stem or run_prefix("dataset", job_id)

    # Fail here rather than three steps in. The workspace path is fixed for the
    # whole run, so if it leaves no room for a usable file name -- a very deep
    # install directory on Windows, where the ceiling is 260 characters -- that
    # is knowable now, and a message naming the cause beats pRESTO's
    # "cannot be opened" from inside step four.
    probe = workspace.steps_path / step_dir_name(len(steps) or 1)
    room = stem_budget(probe, f".{file_type}")
    if room < MIN_STEM_BUDGET:
        message = (
            f"The job folder path is too long for this system: it leaves only "
            f"{room} characters for output file names. Move the application to "
            f"a shorter path, or enable long paths on Windows."
        )
        update_job(
            session_id,
            job_id,
            {"status": f"FAILED {message}", "error": message},
        )
        return None

    split_ending = ends_in_split(steps)
    update_job(
        session_id,
        job_id,
        {
            "step_stats": [],
            "stream": stream.to_status_dict(),
            "run_prefix": prefix,
            # Recorded on the run, not inferred from the last step's parts: a
            # thresholded group split writes two files yet the pipeline carries
            # on, so "wrote several files" and "has no final output" are not
            # the same question.
            "ends_in_split": split_ending,
        },
    )

    final_step_index = _last_step_index(steps)

    for idx, step_data in enumerate(steps):
        step = step_data["name"]

        # Stopping between steps leaves the finished ones intact and
        # downloadable; interrupting a pRESTO call mid-write would not.
        if is_cancel_requested(session_id, job_id):
            update_job(
                session_id,
                job_id,
                {
                    "status": (
                        f"CANCELLED before {step} STEP {idx + 1} OF {len(steps)}"
                    ),
                    "stream": stream.to_status_dict(),
                    "cancelled": True,
                },
            )
            raise JobCancelled(f"Cancelled before step {idx + 1} ({step})")

        lanes_label = ""
        if get_step_stream_behavior(step) == StepStreamBehavior.PER_LANE:
            try:
                lanes_label = (
                    f" lanes={','.join(normalize_step_lanes(step_data, stream.mode))}"
                )
            except ValueError as e:
                update_job(
                    session_id,
                    job_id,
                    {
                        "status": (
                            f"Fail {step} STEP {idx + 1} OF {len(steps)} "
                            f"detail: {str(e)}"
                        ),
                        "stream": stream.to_status_dict(),
                    },
                )
                raise

        update_job(
            session_id,
            job_id,
            {
                "status": (
                    f"PROCESSING {step}{lanes_label} "
                    f"STEP {idx + 1} OF {len(steps)}"
                ),
                "stream": stream.to_status_dict(),
            },
        )

        step_dir = workspace.steps_path / step_dir_name(idx + 1)
        step_dir.mkdir(exist_ok=True)
        # Names are fitted to what the directory leaves, so a deep workspace or
        # a long dataset name shortens the label instead of producing a path
        # the filesystem will not open. See app/core/naming.py.
        suffix = ".tsv" if produces_table(step) else f".{file_type}"
        out_stem = step_stem(
            prefix, idx + 1, step, budget=stem_budget(step_dir, suffix)
        )

        final_output = None
        if idx == final_step_index:
            final_suffix = (
                ".tsv" if produces_table(step) else Path(output_file).suffix
            )
            final_output = str(workspace.outputs_path / f"{prefix}{final_suffix}")

        try:
            stream, by_lane, output_paths, parts = run_pipeline_step(
                stream=stream,
                step_data=step_data,
                step_dir=step_dir,
                file_type=file_type,
                final_output=final_output,
                out_stem=out_stem,
            )
        except JobCancelled:
            raise
        # SystemExit is a BaseException, not an Exception: pRESTO calls
        # sys.exit on any fatal problem, so without naming it here those
        # failures sailed past this handler and the job reported a bare
        # FAILED, with nothing to say which step died or why.
        except (Exception, SystemExit) as e:
            update_job(
                session_id,
                job_id,
                {
                    "status": (
                        f"Fail {step} STEP {idx + 1} OF {len(steps)} "
                        f"detail: {describe_failure(e)}"
                    ),
                    "stream": stream.to_status_dict(),
                    "error": describe_failure(e),
                },
            )
            return None

        step_entry = build_step_stats_entry(
            index=idx + 1,
            step_name=step,
            by_lane=by_lane,
            output_paths=output_paths,
            parts=parts,
        )
        step_stats = _append_step_stats(session_id, job_id, step_entry)

        totals = step_entry
        parts_label = f" parts={len(parts)}" if parts else ""
        update_job(
            session_id,
            job_id,
            {
                "status": (
                    f"DONE {step}{lanes_label} "
                    f"STEP {idx + 1} OF {len(steps)} | "
                    f"before={totals['before']} "
                    f"failed={totals['failed']} "
                    f"remaining={totals['remaining']}{parts_label}"
                ),
                "stream": stream.to_status_dict(),
                "step_stats": step_stats,
                "last_step_stats": step_entry,
            },
        )
        if totals['remaining'] == 0:
            update_job(
                session_id,
                job_id,
                {
                    "status": (
                        f"Fail in the step {step} {step}{lanes_label} "
                        f"STEP {idx + 1} OF {len(steps)} | "
                        "the output is empty so there is no possibility to "
                        "continue from here"
                    ),
                    "stream": stream.to_status_dict(),
                },
            )
            return None

    current_output = stream.primary_path()

    if convert_to_fasta and file_type != "fasta":
        fasta_output = str(workspace.outputs_path / f"{prefix}.fasta")
        convert_file_to_fasta(
            input_file=current_output,
            output_file=fasta_output,
            input_type=file_type,
        )
        return fasta_output

    return current_output


def convert_file_to_fasta(input_file, output_file, input_type):
    with open(output_file, "w") as out_handle:
        for record in SeqIO.parse(input_file, input_type):
            SeqIO.write(record, out_handle, "fasta")
