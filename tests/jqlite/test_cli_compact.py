"""Tests for the -c / --compact CLI flag wiring.

Default output stays 2-space pretty; the flag switches to single-line compact
JSON, one result per line. The flag may appear before or after the query, and
in either spelling. Both forms are deterministic.

The query argument is required (a missing query is a usage error, exit 2), so
these tests pass the explicit identity query ``.`` alongside the flag.
"""

import io
import json
import subprocess
import sys
from pathlib import Path

import pytest

from jqlite.cli import main

REPO_ROOT = Path(__file__).resolve().parents[2]


def run_main(input_text, argv=None):
    """Invoke main() with injected string IO; return (code, stdout, stderr)."""
    stdin = io.StringIO(input_text)
    stdout = io.StringIO()
    stderr = io.StringIO()
    code = main(argv or [], stdin=stdin, stdout=stdout, stderr=stderr)
    return code, stdout.getvalue(), stderr.getvalue()


def test_default_is_pretty():
    code, out, err = run_main('{"a": 1, "b": 2}', ["."])
    assert code == 0
    assert err == ""
    assert out == '{\n  "a": 1,\n  "b": 2\n}\n'


@pytest.mark.parametrize("flag", ["-c", "--compact"])
def test_compact_flag_single_line(flag):
    code, out, err = run_main('{"a": 1, "b": 2}', [flag, "."])
    assert code == 0
    assert err == ""
    assert out == '{"a":1,"b":2}\n'


@pytest.mark.parametrize("flag", ["-c", "--compact"])
def test_compact_flag_with_query(flag):
    # Query identity is explicit; flag may precede the query.
    code, out, err = run_main('{"a": 1, "b": 2}', [flag, "."])
    assert code == 0
    assert out == '{"a":1,"b":2}\n'


def test_compact_flag_after_query():
    code, out, err = run_main('{"a": 1, "b": 2}', [".", "-c"])
    assert code == 0
    assert out == '{"a":1,"b":2}\n'


def test_compact_one_result_per_line_for_stream():
    # Two stream values -> two compact lines, input order preserved.
    code, out, err = run_main('{"a": 1}\n{"b": 2}', ["-c", "."])
    assert code == 0
    assert out == '{"a":1}\n{"b":2}\n'


def test_compact_one_result_per_line_for_iteration():
    # Iteration emits one result per element; compact -> one per line.
    code, out, err = run_main("[1, 2, 3]", ["-c", ".[]"])
    assert code == 0
    assert out == "1\n2\n3\n"


def test_compact_nested_is_single_line():
    code, out, err = run_main('{"outer": {"inner": [1, 2]}}', ["-c", "."])
    assert code == 0
    assert out == '{"outer":{"inner":[1,2]}}\n'


def test_compact_preserves_key_order():
    code, out, err = run_main('{"z": 1, "a": 2}', ["-c", "."])
    assert out == '{"z":1,"a":2}\n'


def test_compact_unicode_preserved():
    code, out, err = run_main('"caf\u00e9 \u2615"', ["-c", "."])
    assert out == "\"caf\u00e9 \u2615\"\n"


def test_compact_is_deterministic():
    src = '{"z": [1, 2], "a": {"k": "v"}}'
    assert run_main(src, ["-c", "."]) == run_main(src, ["-c", "."])


def test_compact_output_roundtrips():
    code, out, err = run_main('{"b": 1, "a": [2, 3]}', ["-c", "."])
    assert json.loads(out) == {"b": 1, "a": [2, 3]}


def test_module_entrypoint_compact():
    proc = subprocess.run(
        [sys.executable, "-m", "jqlite", "-c", "."],
        input='{"a": 1}',
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )
    assert proc.returncode == 0
    assert proc.stdout == '{"a":1}\n'
    assert proc.stderr == ""
