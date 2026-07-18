"""rev 0.4.9: Rust bugfix/refactor verifier commands — the deferred non-Python class gap.

The pytest-only `regression_command`/`pass_fail_command` (C0f) made a cargo bugfix/refactor
structurally uncompletable (a prior drive's lesson: every attempt fails closed). The builders now
dispatch on the operator's test command; cargo gets two self-contained python -c wrappers over the
stable `test <name> ... ok|FAILED|ignored` output (cargo has no per-test-file runner and no machine
format on stable). The regression wrapper refuses the vacuous zero-tests-ran "ok" (the C0-class
false-certification cargo would otherwise hand back for a mistyped target).
"""

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.verifier.class_commands import (
    derive_regression_test_ref,
    pass_fail_command,
    regression_command,
    regression_test_files,
)


def _diff(*paths):
    return "".join(f"diff --git a/{p} b/{p}\n--- a/{p}\n+++ b/{p}\n@@ -0,0 +1 @@\n+x\n"
                   for p in paths)


def test_rust_regression_test_detection_is_integration_targets_only():
    # a cargo integration target is a DIRECT child of tests/ — helper modules (tests/common/mod.rs)
    # are not runnable targets, and src unit #[test]s have no per-file runner (out of scope, the
    # derive returns "" and the verifier fails closed naming the gap)
    diff = _diff("tests/regress_stdin.rs", "tests/common/mod.rs", "src/main.rs")
    assert regression_test_files(diff, "rust") == ["tests/regress_stdin.rs"]
    assert derive_regression_test_ref(diff, "rust") == "tests/regress_stdin.rs"
    # two targets -> ambiguous -> fail closed
    assert derive_regression_test_ref(_diff("tests/a.rs", "tests/b.rs"), "rust") == ""
    # unsupported languages match nothing rather than guessing with the python rules
    assert regression_test_files(_diff("foo.test.js"), "js") == []
    # python behaviour unchanged
    assert regression_test_files(_diff("tests/test_x.py"), "python") == ["tests/test_x.py"]


def test_rust_command_shapes():
    cmd = regression_command("tests/regress_stdin.rs", language="rust")
    assert cmd[0] == "python" and cmd[1] == "-c" and cmd[-1] == "regress_stdin"  # target stem
    cmd = pass_fail_command("tests", language="rust")
    assert cmd[0] == "python" and cmd[1] == "-c" and "cargo" in cmd[2]
    # python callers unchanged
    assert regression_command("tests/test_x.py")[:3] == ["python", "-m", "pytest"]


_CARGO = shutil.which("cargo") is None


@pytest.mark.skipif(_CARGO, reason="cargo not installed")
def test_rust_wrappers_against_a_real_crate(tmp_path):
    (tmp_path / "Cargo.toml").write_text(
        '[package]\nname = "probe"\nversion = "0.1.0"\nedition = "2021"\n', encoding="utf-8")
    src = tmp_path / "src"
    src.mkdir()
    # a doc-test too: its printed name embeds `(line N)`, which the wrapper must STRIP or every
    # line-shifting (behavior-preserving!) refactor renames the id and false-rejects (F1); and a
    # bin target with the SAME unit-test path as the lib pins the duplicate-id suffixing (F3)
    buggy = ("/// ```\n/// assert_eq!(probe::add(2, 2), 4);\n/// ```\n"
             "pub fn add(a: i32, b: i32) -> i32 { a - b }\n"
             "#[cfg(test)]\nmod tests { #[test] fn unit_ok() { assert_eq!(1, 1); } }\n")
    src.joinpath("lib.rs").write_text(buggy, encoding="utf-8")
    src.joinpath("main.rs").write_text(
        "fn main() {}\n#[cfg(test)]\nmod tests { #[test] fn unit_ok() { assert_eq!(2, 2); } }\n",
        encoding="utf-8")
    tests = tmp_path / "tests"
    tests.mkdir()
    tests.joinpath("regress.rs").write_text(
        "#[test]\nfn add_works() { assert_eq!(probe::add(2, 2), 4); }\n", encoding="utf-8")

    regression = regression_command("tests/regress.rs", language="rust")
    assert subprocess.run(regression, cwd=tmp_path).returncode == 1  # bug present -> fails (baseline)
    src.joinpath("lib.rs").write_text(buggy.replace("a - b", "a + b"), encoding="utf-8")
    assert subprocess.run(regression, cwd=tmp_path).returncode == 0  # fixed -> passes (post)

    # the vacuous-zero-tests guard: a target with no tests prints "0 passed ... ok" + exit 0 from
    # cargo — the wrapper must still FAIL it
    tests.joinpath("empty.rs").write_text("// no tests here\n", encoding="utf-8")
    assert subprocess.run(regression_command("tests/empty.rs", language="rust"),
                          cwd=tmp_path).returncode == 1

    out = subprocess.run(pass_fail_command("tests", language="rust"), cwd=tmp_path,
                         capture_output=True, text=True).stdout
    verdicts = dict(line.rsplit(" ", 1) for line in out.strip().splitlines() if line)
    assert verdicts.get("add_works") == "pass"          # integration target
    assert verdicts.get("tests::unit_ok") == "pass"     # unit test (lib target)
    assert verdicts.get("tests::unit_ok#2") == "pass"   # SAME id in the bin target — suffixed (F3)
    doc_ids = [k for k in verdicts if "lib.rs" in k]    # the doc-test id
    assert doc_ids and all("(line" not in k and "line_" not in k for k in doc_ids), doc_ids  # F1
