from __future__ import annotations

import importlib.util
from pathlib import Path
import tempfile
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RENDERER = PROJECT_ROOT / "rendering" / "build_report.py"
SPEC = importlib.util.spec_from_file_location("portable_renderer", RENDERER)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class OutputLocationPolicyTests(unittest.TestCase):
    def test_explicit_output_directory_has_highest_priority(self):
        with tempfile.TemporaryDirectory() as temp:
            source = str(Path(temp) / "report.md")
            expected = str(Path(temp) / "explicit")
            self.assertEqual(
                MODULE.resolve_output_directory(source, ["--out-dir", expected], {"TRAIL_RACE_OUTPUT_DIR": str(Path(temp) / "environment")}),
                str(Path(expected).resolve()),
            )

    def test_environment_fallback_precedes_source_directory(self):
        with tempfile.TemporaryDirectory() as temp:
            source = str(Path(temp) / "source" / "report.md")
            environment = str(Path(temp) / "environment")
            self.assertEqual(
                MODULE.resolve_output_directory(source, [], {"TRAIL_RACE_OUTPUT_DIR": environment}),
                str(Path(environment).resolve()),
            )

    def test_source_directory_is_final_renderer_fallback(self):
        with tempfile.TemporaryDirectory() as temp:
            source = str(Path(temp) / "source" / "report.md")
            self.assertEqual(MODULE.resolve_output_directory(source, [], {}), str((Path(temp) / "source").resolve()))

    def test_missing_or_invalid_explicit_parameter_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "requires a writable directory path"):
            MODULE.resolve_output_directory("report.md", ["--out-dir"], {})
        with self.assertRaisesRegex(ValueError, "output path is not a directory"):
            with tempfile.NamedTemporaryFile() as file:
                MODULE.resolve_output_directory("report.md", ["--out-dir", file.name], {})


if __name__ == "__main__":
    unittest.main()
