"""
Audit of the claim that AIRRPrep does not redistribute USEARCH.

The manuscript states that USEARCH is proprietary, that it is not included in
AIRRPrep or its container image, and that no predefined workflow requires it.
These tests check that against the tree as it will be released, so the claim
cannot quietly stop being true:

  * no USEARCH (or ublast) executable or archive anywhere in the source tree;
  * nothing in the image build (Dockerfile, compose files, entrypoint) or in
    the Python requirements fetches or installs one;
  * the clustering default is an open tool the image carries, and so is the
    reference-assembly aligner default;
  * no predefined workflow names an operation that needs USEARCH;
  * selecting USEARCH without a binary fails with a message that says what it
    is and what to do, rather than "not found on PATH".

The proprietary USEARCH comparison itself lives outside this suite, in
`paper/test/component_matrix` (run with USEARCH_BIN pointed at a licensed
binary); only its commands, versions and outcome are published.

    cd presto-backend
    venv/Scripts/python.exe -m unittest tests.test_no_proprietary_binaries -v
"""

import re
import unittest
from pathlib import Path
from unittest import mock

BACKEND = Path(__file__).resolve().parent.parent
REPO = BACKEND.parent

#: Real USEARCH distributions are named like this. Matching on the name is
#: what a reviewer can check by eye, and it does not depend on the file being
#: readable as text.
_BINARY_NAMES = re.compile(
    r"^(usearch|ublast)([-_.]?\d|\.exe|\.gz|\.zip|\.tar)?", re.IGNORECASE
)

#: Directories that are not part of what is released.
_IGNORED_DIRS = {
    ".git", "__pycache__", "venv", "node_modules", "dist", ".pytest_cache",
    "uploads", "outputs", "jobs", "results", "temp", "work",
}


def walk_release_tree(root: Path):
    for path in root.rglob("*"):
        if any(part in _IGNORED_DIRS for part in path.parts):
            continue
        if path.is_file():
            yield path


class NoUsearchInTheTree(unittest.TestCase):
    def test_no_usearch_binary_or_archive_is_present(self):
        offenders = [
            p for p in walk_release_tree(BACKEND)
            if _BINARY_NAMES.match(p.name)
        ]
        self.assertEqual(
            [str(p.relative_to(BACKEND)) for p in offenders], [],
            "a USEARCH binary or archive is present in the backend tree",
        )

    def test_nothing_in_the_image_build_installs_usearch(self):
        for name in ("Dockerfile", "docker-compose.yml", "docker-entrypoint.sh"):
            path = BACKEND / name
            if not path.is_file():
                continue
            with self.subTest(file=name):
                text = path.read_text(encoding="utf-8", errors="replace").lower()
                for line in text.splitlines():
                    stripped = line.strip()
                    if "usearch" not in stripped:
                        continue
                    if stripped.startswith("#"):
                        continue  # a comment may explain the omission
                    # Saying that it is absent, or naming the setting an
                    # operator points at their own binary, is not installing it.
                    if "not included" in stripped or "usearch_bin" in stripped:
                        continue
                    self.fail(f"{name} references usearch on: {line.strip()}")

    def test_requirements_do_not_pull_in_usearch(self):
        text = (BACKEND / "requirements.txt").read_text(encoding="utf-8").lower()
        self.assertNotIn("usearch", text)

    def test_usearch_is_reachable_only_through_an_operator_setting(self):
        """It may be *selectable*; it must never be bundled."""
        from app import config

        self.assertEqual(config.CLUSTER_BINS["usearch"], "usearch")
        # i.e. a bare name resolved on PATH, from USEARCH_BIN -- never a path
        # inside the distribution.
        with mock.patch.dict("os.environ", {"USEARCH_BIN": "/opt/licensed/usearch"}):
            import importlib

            reloaded = importlib.reload(config)
            self.assertEqual(
                reloaded.CLUSTER_BINS["usearch"], "/opt/licensed/usearch"
            )
        importlib.reload(config)


class OpenToolsAreTheDefault(unittest.TestCase):
    def test_clustering_defaults_to_an_open_tool(self):
        from app.config import CLUSTER_BINS, DEFAULT_CLUSTER_TOOL

        self.assertNotEqual(DEFAULT_CLUSTER_TOOL, "usearch")
        self.assertIn(DEFAULT_CLUSTER_TOOL, CLUSTER_BINS)

    def test_reference_assembly_defaults_to_an_open_aligner(self):
        from app.config import ALIGNER_BINS, DEFAULT_REFERENCE_ALIGNER

        self.assertNotEqual(DEFAULT_REFERENCE_ALIGNER, "usearch")
        self.assertIn(DEFAULT_REFERENCE_ALIGNER, ALIGNER_BINS)

    def test_wrapper_signatures_carry_the_open_default(self):
        import inspect

        from app.presto_wrappers import assemble_pair, cluster_sets

        for func in (
            cluster_sets.run_cluster_sets_all,
            cluster_sets.run_cluster_sets_barcode,
            cluster_sets.run_cluster_sets_set,
        ):
            with self.subTest(func=func.__name__):
                default = inspect.signature(func).parameters["cluster_tool"].default
                self.assertNotEqual(default, "usearch")

        for func in (
            assemble_pair.run_assemble_reference,
            assemble_pair.run_assemble_sequential,
        ):
            with self.subTest(func=func.__name__):
                default = inspect.signature(func).parameters["aligner"].default
                self.assertNotEqual(default, "usearch")

    def test_a_request_cannot_name_the_executable(self):
        """--exec has no safe equivalent on a hosted service."""
        import inspect

        from app.presto_wrappers import assemble_pair, cluster_sets

        for func in (
            assemble_pair.run_assemble_reference,
            assemble_pair.run_assemble_sequential,
            cluster_sets.run_cluster_sets_all,
            cluster_sets.run_cluster_sets_barcode,
            cluster_sets.run_cluster_sets_set,
        ):
            with self.subTest(func=func.__name__):
                names = set(inspect.signature(func).parameters)
                self.assertEqual(
                    names & {"aligner_exec", "db_exec", "cluster_exec", "exec"},
                    set(),
                )


class NoPredefinedWorkflowNeedsUsearch(unittest.TestCase):
    def test_no_predefined_workflow_uses_a_usearch_only_step(self):
        from tests.test_workflow_validation import (
            NONUMI_2X250,
            RACE_325_275,
            UMI_2X250,
        )

        for workflow in (RACE_325_275, UMI_2X250, NONUMI_2X250):
            for step in workflow:
                params = step.get("params") or {}
                with self.subTest(step=step["name"]):
                    self.assertNotEqual(params.get("cluster_tool"), "usearch")
                    self.assertNotEqual(params.get("aligner"), "usearch")
                    # A ClusterSets step with no tool named would inherit the
                    # default; that default is asserted open above, but a
                    # predefined workflow should not depend on it either.
                    self.assertFalse(
                        step["name"].startswith("ClusterSets")
                        and "cluster_tool" not in params
                    )


class MissingBinaryMessages(unittest.TestCase):
    def test_selecting_usearch_without_a_binary_explains_why(self):
        from app.presto_wrappers import cluster_sets

        with mock.patch.dict(
            cluster_sets.CLUSTER_BINS,
            {"usearch": "definitely-not-installed-usearch"},
        ):
            with self.assertRaises(RuntimeError) as cm:
                cluster_sets._resolve_cluster_tool("usearch", 0.9)

        message = str(cm.exception)
        self.assertIn("proprietary", message)
        self.assertIn("USEARCH_BIN", message)
        self.assertIn("vsearch", message)


if __name__ == "__main__":
    unittest.main()
