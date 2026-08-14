"""PKT-EXAMPLE acceptance: todo_cli --version prints the schema version."""
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from orchestrator import todo_cli


def test_version_flag_prints_schema_version(capsys):
    rc = todo_cli.main(["--version"])
    assert rc == 0
    out = capsys.readouterr().out.strip()
    assert out == todo_cli.TODO_CLI_SCHEMA_VERSION
    assert out.startswith("todo_cli/")
