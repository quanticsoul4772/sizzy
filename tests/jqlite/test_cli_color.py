"""Tests for the optional --color CLI flag.

``--color`` syntax-highlights output with rich when that optional dependency is
installed, and is a clean no-op (identical plain output) when it is not. jqlite
must run stdlib-only, so every test here passes whether or not rich is
installed: the flag-parsing and fallback tests are unconditional, and the
highlighting assertion is guarded on rich's actual availability.
"""

import io
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

from jqlite import output
from jqlite.cli import _parse_args, main

REPO_ROOT = Path(__file__).resolve().parents[2]

# Matches a CSI ANSI escape sequence (what rich emits for color), so a test can
# strip styling and recover the underlying text.
_ANSI = re.compile(r"\x1b\[[0-9;]*m")


def run_main(input_text, argv=None):
    """Invoke main() with injected string IO; return (code, stdout, stderr)."""
    stdin = io.StringIO(input_text)
    stdout = io.StringIO()
    stderr = io.StringIO()
    code = main(argv or [], stdin=stdin, stdout=stdout, stderr=stderr)
    return code, stdout.getvalue(), stderr.getvalue()


def strip_ansi(text):
    """Remove ANSI color escapes so highlighted output can be compared by text."""
    return _ANSI.sub("", text)


# --- flag parsing (unconditional) ---------------------------------------------


def test_parse_args_color_off_by_default():
    compact, color, query = _parse_args(["."])
    assert color is False
    assert compact is False
    assert query == "."


def test_parse_args_color_flag_sets_color():
    compact, color, query = _parse_args(["--color", "."])
    assert color is True
    assert query == "."


def test_parse_args_color_flag_after_query():
    compact, color, query = _parse_args([".", "--color"])
    assert color is True
    assert query == "."


def test_parse_args_color_with_compact():
    compact, color, query = _parse_args(["--color", "-c", "."])
    assert color is True
    assert compact is True
    assert query == "."


def test_color_flag_does_not_consume_query():
    # --color must not be mistaken for the positional query.
    code, out, err = run_main('{"a": 1}', ["--color"])
    assert code == 2
    assert "no query" in err


# --- end-to-end via main (rich is installed in this env, but assertions are
#     written to hold either way) -----------------------------------------------


def test_color_flag_runs_clean():
    code, out, err = run_main('{"a": 1}', ["--color", "."])
    assert code == 0
    assert err == ""
    assert out != ""


def test_color_output_roundtrips_after_stripping_ansi():
    code, out, err = run_main('{"b": 1, "a": [2, 3]}', ["--color", "."])
    assert code == 0
    assert json.loads(strip_ansi(out)) == {"b": 1, "a": [2, 3]}


def test_color_highlights_when_rich_available():
    rich_available = output._import_rich() is not None
    code, out, err = run_main('{"a": 1}', ["--color", "."])
    assert code == 0
    if rich_available:
        # rich emits ANSI escapes for highlighting.
        assert "\x1b[" in out
    else:
        # No rich -> plain pretty output, no escapes.
        assert "\x1b[" not in out
        assert out == '{\n  "a": 1\n}\n'


# --- the no-rich fallback (forced, so it runs even with rich installed) --------


def test_color_falls_back_to_plain_pretty_without_rich(monkeypatch):
    monkeypatch.setattr(output, "_import_rich", lambda: None)
    code, out, err = run_main('{"a": 1, "b": 2}', ["--color", "."])
    assert code == 0
    assert err == ""
    # Identical to the default plain pretty form.
    assert out == '{\n  "a": 1,\n  "b": 2\n}\n'


def test_color_falls_back_to_plain_compact_without_rich(monkeypatch):
    monkeypatch.setattr(output, "_import_rich", lambda: None)
    code, out, err = run_main('{"a": 1, "b": 2}', ["--color", "-c", "."])
    assert code == 0
    assert out == '{"a":1,"b":2}\n'


def test_dump_color_equals_plain_when_rich_absent(monkeypatch):
    monkeypatch.setattr(output, "_import_rich", lambda: None)
    value = {"z": [1, 2], "a": {"k": "v"}}
    assert output.dump_color(value) == output.dump_pretty(value)
    assert output.dump_color(value, compact=True) == output.dump_compact(value)


def test_dump_color_default_is_no_op():
    # dump() without color must be byte-identical to the plain pretty form.
    value = {"a": 1}
    assert output.dump(value) == output.dump_pretty(value)
    assert output.dump(value, compact=True) == output.dump_compact(value)


# --- module entrypoint --------------------------------------------------------


def test_module_entrypoint_color():
    proc = subprocess.run(
        [sys.executable, "-m", "jqlite", "--color", "."],
        input='{"a": 1}',
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )
    assert proc.returncode == 0
    assert proc.stderr == ""
    # Whether or not rich is installed, the JSON content round-trips.
    assert json.loads(strip_ansi(proc.stdout)) == {"a": 1}
