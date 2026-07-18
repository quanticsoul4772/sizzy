"""Tests for RFC-4180-style CSV quoting on the csvlite read/write path.

Exercises the stdlib :mod:`csv` round-trip: quoted fields, embedded commas,
embedded newlines, and escaped (doubled) quotes are parsed by ``csv.reader`` and
re-quoted by ``csv.writer`` so the emitted CSV round-trips. The in-memory cases
inject :class:`io.StringIO`; the real-``sys.stdin`` cases drive ``python -m
csvlite`` over a pipe with raw bytes, which is the only way to exercise the
``newline=""`` handling that keeps a newline embedded in a quoted field from
being corrupted by the text layer's universal-newline translation.
"""

import io
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def run_main(input_text, argv=None):
    """Invoke main() with injected string IO; return (code, stdout, stderr)."""
    from csvlite.cli import main

    stdin = io.StringIO(input_text)
    stdout = io.StringIO()
    stderr = io.StringIO()
    code = main(argv or [], stdin=stdin, stdout=stdout, stderr=stderr)
    return code, stdout.getvalue(), stderr.getvalue()


def run_module_bytes(input_bytes, argv):
    """Drive ``python -m csvlite`` over a real pipe with raw bytes.

    Returns ``(returncode, stdout_bytes, stderr_bytes)``. Using bytes (not
    ``text=True``) avoids the harness re-translating line endings, so the
    assertions see exactly what the tool wrote.
    """
    proc = subprocess.run(
        [sys.executable, "-m", "csvlite", *argv],
        input=input_bytes,
        capture_output=True,
        cwd=str(REPO_ROOT),
    )
    return proc.returncode, proc.stdout, proc.stderr


# --- in-memory parse + re-quote round-trips ---------------------------------


def test_embedded_comma_is_requoted():
    code, out, err = run_main('name,note\nAda,"hello, world"\n', ["note,name"])
    assert code == 0
    assert err == ""
    # The embedded comma forces csv to re-quote the field on output.
    assert out == 'note,name\n"hello, world",Ada\n'


def test_embedded_newline_is_preserved_and_requoted():
    code, out, err = run_main('name,note\nAda,"a\nb"\n', ["note"])
    assert code == 0
    assert out == 'note\n"a\nb"\n'


def test_escaped_doubled_quote_roundtrips():
    # ``""`` inside a quoted field is one literal quote; on output the writer
    # re-quotes the field and doubles the internal quote again.
    code, out, err = run_main(
        'name,note\nAda,"she said ""hi"""\n', ["note"]
    )
    assert code == 0
    assert out == 'note\n"she said ""hi"""\n'


def test_field_that_is_only_a_quoted_empty_string():
    code, out, err = run_main('a,b\n"",x\n', ["a,b"])
    assert code == 0
    # An empty cell needs no quoting on output.
    assert out == "a,b\n,x\n"


def test_leading_and_trailing_spaces_preserved():
    code, out, err = run_main('a,b\n"  pad  ",x\n', ["a"])
    assert code == 0
    # Surrounding spaces are data; csv keeps them but does not need quotes.
    assert out == "a\n  pad  \n"


def test_field_with_comma_quote_and_newline_together():
    code, out, err = run_main(
        'k,v\nrow,"a, ""b"" \nc"\n', ["v"]
    )
    assert code == 0
    assert out == 'v\n"a, ""b"" \nc"\n'


def test_embedded_newline_counts_as_one_record():
    # A quoted field spanning two physical lines is a single data row, so a
    # numeric --where over a sibling column still matches the whole record.
    code, out, err = run_main(
        'id,note\n1,"line1\nline2"\n2,"plain"\n',
        ["note", "--where", "id == 1"],
    )
    assert code == 0
    assert out == 'note\n"line1\nline2"\n'


def test_json_preserves_embedded_comma_and_newline_as_string():
    import json

    code, out, err = run_main(
        'name,note\nAda,"x, y\nz"\n', ["note,name", "--json"]
    )
    assert code == 0
    records = json.loads(out)
    assert records == [{"note": "x, y\nz", "name": "Ada"}]


# --- real-sys.stdin pipe: newline="" correctness ----------------------------


def test_crlf_input_embedded_crlf_roundtrips_over_real_pipe():
    raw = b'name,note\r\nAda,"a\r\nb"\r\nx,"p\nq"\r\n'
    code, out, err = run_module_bytes(raw, ["note,name"])
    assert code == 0
    assert err == b""
    # Row terminators are a clean \n (the writer's lineterminator); the embedded
    # \r\n and \n inside the quoted fields are preserved verbatim and re-quoted.
    # No spurious empty rows, no stray \r injected on the line terminators.
    assert out == b'note,name\n"a\r\nb",Ada\n"p\nq",x\n'


def test_crlf_input_embedded_comma_roundtrips_over_real_pipe():
    raw = b'name,note\r\nAda,"hello, world"\r\n'
    code, out, err = run_module_bytes(raw, ["note,name"])
    assert code == 0
    assert err == b""
    assert out == b'note,name\n"hello, world",Ada\n'


def test_lf_input_does_not_gain_carriage_returns_over_real_pipe():
    # A bare-\n quoted field must stay bare-\n on output (no \r injected).
    raw = b'a\n"p\nq"\n'
    code, out, err = run_module_bytes(raw, ["a"])
    assert code == 0
    assert err == b""
    assert out == b'a\n"p\nq"\n'
