"""Checks that the editable SDK import does not depend on the repository cwd."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_editable_install_is_importable_outside_repository(tmp_path) -> None:
    outside_directory = tmp_path.resolve()
    assert not outside_directory.is_relative_to(PROJECT_ROOT)

    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    command = (
        "from pathlib import Path; "
        "import ragops; "
        "from ragops.tracing import RagTracePayload, TraceCollector, TracedRagRunner; "
        "print(Path(ragops.__file__).resolve())"
    )

    completed = subprocess.run(
        [sys.executable, "-c", command],
        cwd=outside_directory,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )

    imported_package = Path(completed.stdout.strip())
    expected_package = (PROJECT_ROOT / "src" / "ragops" / "__init__.py").resolve()
    assert imported_package == expected_package
