"""
Stream-aware pipeline state: single-file vs dual R1/R2 lanes.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Optional


class StreamMode(str, Enum):
    SINGLE = "single"
    DUAL = "dual"


class StepStreamBehavior(str, Enum):
    PER_LANE = "per_lane"
    PAIRED_IO = "paired_io"
    MERGE_PAIRED = "merge_paired"


LANE_R1 = "R1"
LANE_R2 = "R2"
VALID_LANES = frozenset({LANE_R1, LANE_R2})

STEP_STREAM_BEHAVIOR: dict[str, StepStreamBehavior] = {
    "PairSeq.default": StepStreamBehavior.PAIRED_IO,
    "SplitSeq.samplepair": StepStreamBehavior.PAIRED_IO,
    "AssembleSeq.align": StepStreamBehavior.MERGE_PAIRED,
    "AssembleSeq.join": StepStreamBehavior.MERGE_PAIRED,
    "AssembleSeq.reference": StepStreamBehavior.MERGE_PAIRED,
    "AssembleSeq.sequential": StepStreamBehavior.MERGE_PAIRED,
}


def get_step_stream_behavior(step_name: str) -> StepStreamBehavior:
    return STEP_STREAM_BEHAVIOR.get(step_name, StepStreamBehavior.PER_LANE)


def normalize_step_lanes(
    step_data: dict,
    stream_mode: StreamMode,
) -> list[str]:
    """
    Resolve which lanes a per-lane step targets.

    - omitted / "both" → all active lanes (backward compatible)
    - "R1" / "R2" or ["R1"] → asymmetric run on that lane only
    """
    behavior = get_step_stream_behavior(step_data["name"])
    if behavior != StepStreamBehavior.PER_LANE:
        if stream_mode == StreamMode.SINGLE:
            return [LANE_R1]
        return [LANE_R1, LANE_R2]

    raw = step_data.get("lanes", step_data.get("lane"))

    if raw is None:
        if stream_mode == StreamMode.SINGLE:
            return [LANE_R1]
        return [LANE_R1, LANE_R2]

    if isinstance(raw, str):
        key = raw.strip().upper()
        if key in ("BOTH", "ALL", "PAIR", "PAIRED"):
            return [LANE_R1, LANE_R2] if stream_mode == StreamMode.DUAL else [LANE_R1]
        if key in VALID_LANES:
            return [key]
        raise ValueError(f"Invalid lane value: {raw}")

    lanes = []
    for item in raw:
        key = str(item).strip().upper()
        if key not in VALID_LANES:
            raise ValueError(f"Invalid lane value: {item}")
        lanes.append(key)

    return list(dict.fromkeys(lanes))


@dataclass
class PipelineStream:
    mode: StreamMode
    r1: str
    r2: Optional[str] = None

    @classmethod
    def from_input_files(cls, file_paths: list[str]) -> "PipelineStream":
        if len(file_paths) == 1:
            return cls(mode=StreamMode.SINGLE, r1=file_paths[0])
        if len(file_paths) == 2:
            return cls(
                mode=StreamMode.DUAL,
                r1=file_paths[0],
                r2=file_paths[1],
            )
        raise ValueError(
            f"Expected 1 or 2 input files, got {len(file_paths)}"
        )

    def path_for_lane(self, lane: str) -> str:
        if lane == LANE_R1:
            return self.r1
        if lane == LANE_R2:
            if self.r2 is None:
                raise ValueError(f"Lane {lane} is not available in {self.mode.value} stream")
            return self.r2
        raise ValueError(f"Unknown lane: {lane}")

    def with_lane_path(self, lane: str, path: str) -> "PipelineStream":
        if lane == LANE_R1:
            return PipelineStream(mode=self.mode, r1=path, r2=self.r2)
        return PipelineStream(mode=self.mode, r1=self.r1, r2=path)

    def primary_path(self) -> str:
        return self.r1

    def active_lanes(self) -> tuple[str, ...]:
        if self.mode == StreamMode.SINGLE:
            return (LANE_R1,)
        return (LANE_R1, LANE_R2)

    def to_status_dict(self) -> dict:
        state = {"mode": self.mode.value, "r1": self.r1}
        if self.r2 is not None:
            state["r2"] = self.r2
        return state


def lane_output_path(step_dir: Path, lane: str, file_type: str) -> Path:
    return step_dir / f"{lane}_output.{file_type}"
