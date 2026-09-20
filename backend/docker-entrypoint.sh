#!/bin/sh
# Sizes the container's CPU usage to two thirds of whatever machine it lands
# on, so the same image can be deployed to any server without retuning.
#
# The cap has to be applied here rather than in docker-compose.yml: compose's
# `cpus:` is a static number baked into the file, but the budget depends on
# the host we are actually starting on. app/core/cpu.py does the detection
# (honouring a cgroup limit if one was set), and the result is applied to the
# two things that would otherwise consume every core — the Celery worker pool
# and TRUST4's thread count.
set -e

CPU_TOTAL="$(python -c 'from app.core.cpu import available_cpus; print(available_cpus())')"
CPU_BUDGET="$(python -c 'from app.core.cpu import budgeted_cpus; print(budgeted_cpus())')"
export CPU_BUDGET

# An explicit TRUST4_THREADS always wins; otherwise it follows the budget.
if [ -z "${TRUST4_THREADS:-}" ]; then
    TRUST4_THREADS="$CPU_BUDGET"
    export TRUST4_THREADS
fi

echo "cpu: using ${CPU_BUDGET} of ${CPU_TOTAL} available cores" \
     "(CPU_FRACTION=${CPU_FRACTION:-0.6667}, TRUST4_THREADS=${TRUST4_THREADS})" >&2

# Celery defaults its pool to one process per core. Size it to the budget
# instead, unless the caller passed an explicit --concurrency.
if [ "$1" = "celery" ]; then
    for arg in "$@"; do
        case "$arg" in
            --concurrency|--concurrency=*|-c) exec "$@" ;;
        esac
    done
    exec "$@" --concurrency="$CPU_BUDGET"
fi

exec "$@"
