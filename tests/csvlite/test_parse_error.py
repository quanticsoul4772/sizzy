"""Tests for exit code 4 (parse error) on malformed or undecodable stdin.

Two distinct stdin failures both map to the parse-error exit code (4):

* *malformed CSV* — the bytes decode to text but are not well-formed CSV. The
  stdlib :mod:`csv` reader is deliberately lenient (short rows pad, ragged rows
  are accepted), so the reliable trigger is a field larger than
  ``csv.field_size_limit()``, which raises :class:`csv.Error`.
* *undecodable input* — the byte stream is not valid text under the active
  encoding, so it cannot be decoded at all and reading raises
  :class:`UnicodeDecodeError`.

Both are content problems with the input on stdin (not invocation or query
problems), so both surface as a clean exit 4 with a stderr message rather than
an uncaught traceback.
"""

import csv
import io
import os
import subprocess
import sys
from pathlib import Path

from csvlite.cli import main
from csvlite.errors import EXIT_PARSE, ParseError

REPO_ROOT = Path(__file__).resolve().parents[2]


def run_main(input_text, argv=None):
    """Invoke main() with injected string IO; return (code, stdout, stderr)."""
    stdin = io.StringIO(input_text)
    stdout = io.StringIO()
    stderr = io.StringIO()
    code = main(argv or [], stdin=stdin, stdout=stdout, stderr=stderr)
    return code, stdout.getvalue(), stderr.getvalue()


def run_main_bytes(input_bytes, argv=None, *, encoding="utf-8"):
    """Invoke main() with a byte-backed text stdin; return (code, out, err).

    Wraps ``input_bytes`` in a :class:`io.TextIOWrapper` over a
    :class:`io.BytesIO` with a fixed ``encoding`` so the decode is deterministic
    regardless of the host's default stdin encoding.
    """
    stdin = io.TextIOWrapper(io.BytesIO(input_bytes), encoding=encoding)
    stdout = io.StringIO()
    stderr = io.StringIO()
    code = main(argv or [], stdin=stdin, stdout=stdout, stderr=stderr)
    return code, stdout.getvalue(), stderr.getvalue()


# --- malformed CSV (csv.Error) -> exit 4 ------------------------------------


def test_field_larger_than_limit_is_parse_error():
    # The csv reader raises csv.Error when a field exceeds field_size_limit.
    old_limit = csv.field_size_limit()
    csv.field_size_limit(10)
    try:
        code, out, err = run_main("name\n" + "a" * 100 + "\n", ["name"])
    finally:
        csv.field_size_limit(old_limit)
    assert code == EXIT_PARSE
    assert out == ""
    assert err.startswith("csvlite:")
    assert "malformed CSV on stdin" in err


def test_malformed_csv_message_to_stderr_not_stdout():
    old_limit = csv.field_size_limit()
    csv.field_size_limit(5)
    try:
        code, out, err = run_main("h\n" + "z" * 50 + "\n", ["h"])
    finally:
        csv.field_size_limit(old_limit)
    assert out == ""
    assert err != ""


# --- undecodable input (UnicodeDecodeError) -> exit 4 -----------------------


def test_undecodable_input_is_parse_error():
    # 0xFF is never a valid leading byte in UTF-8, so the second line cannot be
    # decoded; reading it raises UnicodeDecodeError, mapped to exit 4.
    code, out, err = run_main_bytes(b"name,age\n\xff\xfe\xfa\n", ["name"])
    assert code == EXIT_PARSE
    assert out == ""
    assert err.startswith("csvlite:")
    assert "undecodable input on stdin" in err


def test_undecodable_input_before_any_output():
    # The invalid bytes are on the header line itself: nothing is emitted.
    code, out, err = run_main_bytes(b"\xff\xff\n", ["whatever"])
    assert code == EXIT_PARSE
    assert out == ""


def test_undecodable_raises_parse_error_type():
    # Direct check that the read path raises ParseError (exit_code 4), not a
    # bare UnicodeDecodeError that would escape as an uncaught traceback.
    err = ParseError("x")
    assert err.exit_code == EXIT_PARSE


# --- distinct codes through the real module entry point ---------------------


def test_module_entrypoint_undecodable_exit_four():
    # Force UTF-8 strict decoding on the child's stdin (PYTHONIOENCODING) so the
    # invalid bytes raise regardless of the host's default console encoding.
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    proc = subprocess.run(
        [sys.executable, "-m", "csvlite", "name"],
        input=b"name\n\xff\xfe\xfa\n",
        capture_output=True,
        cwd=str(REPO_ROOT),
        env=env,
    )
    assert proc.returncode == EXIT_PARSE
    assert proc.stdout == b""
    assert b"csvlite:" in proc.stderr
