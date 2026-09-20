"""
Central pRESTO defaults — frontend never needs to send delimiter / out_args.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from presto.Defaults import default_delimiter, default_out_args

_INT_RE = re.compile(r"^-?\d+$")
_FLOAT_RE = re.compile(r"^-?\d+\.\d+$|^-?\d+(?:\.\d+)?[eE][-+]?\d+$")


def _coerce_scalar(value: Any) -> Any:
    """
    Convert numeric-looking string scalars to int/float.

    The frontend sometimes sends numeric params as strings (e.g. "20"); pRESTO
    functions compare them numerically, so a str would raise
    "'>=' not supported between instances of 'int' and 'str'". Non-numeric
    strings (field names, modes, coords) are left untouched.
    """
    if isinstance(value, str):
        text = value.strip()
        if _INT_RE.match(text):
            try:
                return int(text)
            except ValueError:
                return value
        if _FLOAT_RE.match(text):
            try:
                return float(text)
            except ValueError:
                return value
    return value


# List parameters whose *items* are numbers rather than annotation names.
#
# Almost every pRESTO list parameter is a list of field or action names, so
# list items are left alone by default. `max_count` is the exception: for
# SplitSeq sample/samplepair it is a list of sample sizes, and pRESTO formats
# it with "%i" ("Sampling n=%i" % n). A browser form sends every value as text,
# so without this the run dies inside pRESTO with
# "%i format: a real number is required, not str".
_NUMERIC_LIST_PARAMS = frozenset({"max_count"})

# Re-export for docs / metadata
PRESTO_DEFAULT_DELIMITER = default_delimiter
PRESTO_DEFAULT_OUT_ARGS = default_out_args


def normalize_delimiter(value: Any = None):
    """pRESTO annotation delimiter: 3-tuple (field_sep, value_sep, list_sep)."""
    if value is None:
        return default_delimiter
    if isinstance(value, tuple) and len(value) == 3:
        return value
    if isinstance(value, list) and len(value) == 3:
        return tuple(value)
    return default_delimiter


def merge_out_args(
    step_dir: str | Path | None = None,
    overrides: dict | None = None,
) -> dict:
    """Full out_args dict starting from pRESTO defaults."""
    out_args = dict(default_out_args)
    if overrides:
        for key, value in overrides.items():
            if value is not None:
                out_args[key] = value
    if step_dir is not None:
        out_args["out_dir"] = str(step_dir)
    out_args["delimiter"] = normalize_delimiter(out_args.get("delimiter"))
    return out_args


def sanitize_presto_params(params: dict | None) -> dict:
    """
    Remove empty optional pRESTO keys so wrapper/function defaults apply.
    Frontend may omit delimiter and out_args entirely.
    """
    if not params:
        return {}

    cleaned = dict(params)
    for key in ("delimiter", "out_args", "coord_type"):
        if key not in cleaned:
            continue
        value = cleaned[key]
        if value is None or value == "" or value == {} or value == []:
            del cleaned[key]

    # Coerce numeric-looking string params to int/float. List items are left
    # alone — pRESTO list params are field names — except for the few that are
    # genuinely lists of numbers (see _NUMERIC_LIST_PARAMS).
    for key, value in list(cleaned.items()):
        if key in ("out_args", "delimiter"):
            continue
        if key in _NUMERIC_LIST_PARAMS and isinstance(value, (list, tuple)):
            cleaned[key] = [_coerce_scalar(item) for item in value]
            continue
        cleaned[key] = _coerce_scalar(value)

    if "out_args" in cleaned and isinstance(cleaned["out_args"], dict):
        nested = {
            k: v
            for k, v in cleaned["out_args"].items()
            if v is not None and v != "" and v != {} and v != []
        }
        if nested:
            cleaned["out_args"] = nested
        else:
            del cleaned["out_args"]

    return cleaned
