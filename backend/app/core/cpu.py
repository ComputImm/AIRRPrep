# app/core/cpu.py
"""
How much CPU this deployment is allowed to use.

The heavy work here (TRUST4 assembly, and every pRESTO step that shells out to
blastn, usearch, vsearch, cd-hit-est or muscle) is CPU-bound and scales with
however many cores it is told to use. That number comes from configuration:
set WORKER_CPUS to pin it exactly, or CPU_FRACTION to take a share of the
machine. With neither set the deployment uses every core it can see — a
single-core default would leave an external aligner running one query at a
time while the rest of the machine sits idle.

Detection deliberately prefers the cgroup quota over the host core count: if
the container was started with a CPU limit, the host's core count is a lie
and sizing off it would oversubscribe the container.
"""

import os
from pathlib import Path

#: Exact number of CPUs to use. Unset means "decide from CPU_FRACTION".
_WORKER_CPUS = os.getenv("WORKER_CPUS", "").strip()

#: Share of the available CPUs to use when WORKER_CPUS is not set. Unset means
#: the whole machine; set it (e.g. 0.6667) to leave headroom for other work.
_CPU_FRACTION = os.getenv("CPU_FRACTION", "").strip()
CPU_FRACTION = float(_CPU_FRACTION) if _CPU_FRACTION else 1.0

_CGROUP_V2_MAX = Path("/sys/fs/cgroup/cpu.max")
_CGROUP_V1_QUOTA = Path("/sys/fs/cgroup/cpu/cpu.cfs_quota_us")
_CGROUP_V1_PERIOD = Path("/sys/fs/cgroup/cpu/cpu.cfs_period_us")


def _cgroup_v2_cpus() -> float | None:
    try:
        quota, period = _CGROUP_V2_MAX.read_text().split()
    except (OSError, ValueError):
        return None
    if quota == "max":
        return None
    try:
        return float(quota) / float(period)
    except (ValueError, ZeroDivisionError):
        return None


def _cgroup_v1_cpus() -> float | None:
    try:
        quota = int(_CGROUP_V1_QUOTA.read_text().strip())
        period = int(_CGROUP_V1_PERIOD.read_text().strip())
    except (OSError, ValueError):
        return None
    if quota <= 0 or period <= 0:
        return None
    return quota / period


def available_cpus() -> int:
    """Cores this process may actually run on, honouring a container limit."""
    for probe in (_cgroup_v2_cpus, _cgroup_v1_cpus):
        limit = probe()
        if limit:
            return max(1, int(limit))

    # sched_getaffinity respects CPU pinning; os.cpu_count() does not.
    try:
        return max(1, len(os.sched_getaffinity(0)))  # type: ignore[attr-defined]
    except AttributeError:  # not Linux (local dev on Windows/macOS)
        return max(1, os.cpu_count() or 1)


def budgeted_cpus(fraction: float | None = None) -> int:
    """
    Cores this deployment may use, from configuration.

    WORKER_CPUS wins when it is set to a usable number; otherwise the share in
    CPU_FRACTION applies, which defaults to all of them. An explicit setting is
    still capped at what the machine actually has: asking for more cores than
    exist only adds context switching, and for the external aligners it would
    mean more concurrent processes than there are cores to run them on.
    """
    ceiling = available_cpus()
    if _WORKER_CPUS:
        try:
            configured = int(_WORKER_CPUS)
        except ValueError:
            configured = 0
        if configured > 0:
            return max(1, min(configured, ceiling))
    frac = CPU_FRACTION if fraction is None else fraction
    return max(1, min(ceiling, int(ceiling * frac)))
