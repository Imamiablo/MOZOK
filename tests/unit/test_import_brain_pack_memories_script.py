from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def test_import_brain_pack_memories_script_help_runs_from_project_root():
    repo_root = Path(__file__).resolve().parents[2]
    script_path = repo_root / "scripts" / "import_brain_pack_memories.py"

    result = subprocess.run(
        [sys.executable, str(script_path), "--help"],
        cwd=repo_root,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0
    assert "--dry-run" in result.stdout
    assert "Import brain-pack memories" in result.stdout
