"""C0f: the driver-built per-class commands actually run and produce what the verifiers expect.

bugfix_regression's regression_command must exit 0 iff the named test passes; refactor's
pass_fail_command must emit one `<test_id> pass|fail` line per test (the format _capture parses).
"""

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.verifier.class_commands import pass_fail_command, regression_command


def test_regression_command_shape():
    cmd = regression_command("tests/specledger/test_x.py::test_bug")
    assert cmd[:3] == ["python", "-m", "pytest"]
    assert "tests/specledger/test_x.py::test_bug" in cmd


def test_pass_fail_command_emits_per_test_pass_and_fail(tmp_path):
    (tmp_path / "test_sample.py").write_text(
        "def test_ok():\n    assert True\n\ndef test_bad():\n    assert False\n"
    )
    cmd = pass_fail_command(".", python=sys.executable)
    out = subprocess.run(cmd, cwd=tmp_path, capture_output=True, text=True).stdout
    lines = [l for l in out.splitlines() if l.strip()]
    # one line per test, each ending in `pass` or `fail`, exactly one of each here
    verdicts = {l.rsplit(" ", 1)[0]: l.rsplit(" ", 1)[1] for l in lines if l.endswith((" pass", " fail"))}
    passes = [k for k, v in verdicts.items() if v == "pass"]
    fails = [k for k, v in verdicts.items() if v == "fail"]
    assert any("test_ok" in k for k in passes), out
    assert any("test_bad" in k for k in fails), out


def test_pass_fail_command_is_consistent_for_behavior_preservation(tmp_path):
    # the same command run twice yields the same pass/fail set (what the refactor verifier relies on)
    (tmp_path / "test_sample.py").write_text("def test_ok():\n    assert True\n")
    cmd = pass_fail_command(".", python=sys.executable)
    a = subprocess.run(cmd, cwd=tmp_path, capture_output=True, text=True).stdout
    b = subprocess.run(cmd, cwd=tmp_path, capture_output=True, text=True).stdout
    assert a == b and "pass" in a
