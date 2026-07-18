"""Tests for the jqlite scaffold: identity query, 2-space deterministic output.

The query argument is required (a missing query is a usage error, exit 2), so
these identity tests pass the explicit identity query ``.``.
"""

import io
import json
import subprocess
import sys
from pathlib import Path

import pytest

from jqlite.cli import identity, main

REPO_ROOT = Path(__file__).resolve().parents[2]


def run_main(input_text: str, argv=None):
    """Invoke main() with injected string IO; return (code, stdout, stderr)."""
    stdin = io.StringIO(input_text)
    stdout = io.StringIO()
    stderr = io.StringIO()
    code = main(argv or [], stdin=stdin, stdout=stdout, stderr=stderr)
    return code, stdout.getvalue(), stderr.getvalue()


def test_identity_returns_value_unchanged():
    obj = {"a": 1, "b": [2, 3]}
    assert identity(obj) is obj


@pytest.mark.parametrize(
    "value",
    [
        {"b": 1, "a": 2},
        [1, 2, 3],
        "hello",
        42,
        3.5,
        True,
        False,
        None,
        {},
        [],
        {"nested": {"x": [1, {"y": 2}]}},
    ],
)
def test_identity_echoes_value(value):
    code, out, err = run_main(json.dumps(value), ["."])
    assert code == 0
    assert err == ""
    assert json.loads(out) == value


def test_output_is_two_space_indented():
    code, out, err = run_main('{"a": 1, "b": 2}', ["."])
    assert code == 0
    assert out == '{\n  "a": 1,\n  "b": 2\n}\n'


def test_preserves_input_key_order():
    # Identity echoes unchanged: keys are NOT sorted.
    code, out, err = run_main('{"b": 1, "a": 2}', ["."])
    assert out == '{\n  "b": 1,\n  "a": 2\n}\n'


def test_nested_indentation():
    code, out, err = run_main('{"outer": {"inner": [1, 2]}}', ["."])
    assert out == (
        "{\n"
        '  "outer": {\n'
        '    "inner": [\n'
        "      1,\n"
        "      2\n"
        "    ]\n"
        "  }\n"
        "}\n"
    )


def test_unicode_preserved():
    code, out, err = run_main('"caf\u00e9 \u2615"', ["."])
    assert out == "\"caf\u00e9 \u2615\"\n"


def test_output_is_deterministic():
    src = '{"z": [1, 2], "a": {"k": "v"}}'
    assert run_main(src, ["."]) == run_main(src, ["."])


def test_trailing_newline():
    code, out, err = run_main("42", ["."])
    assert out == "42\n"


def test_module_entrypoint_exit_zero():
    proc = subprocess.run(
        [sys.executable, "-m", "jqlite", "."],
        input='{"a": 1}',
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )
    assert proc.returncode == 0
    assert proc.stdout == '{\n  "a": 1\n}\n'
    assert proc.stderr == ""
