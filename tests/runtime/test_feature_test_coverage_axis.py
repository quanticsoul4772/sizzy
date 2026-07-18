"""feature_spec_claim's test_coverage axis (deterministic, no LLM): the realized diff must add at
least one NEW test-defining line inside a test file. Runs on EVERY feature task — NOT final-task-gated
(contrast with spec_criteria) — every task's own diff should carry its own test."""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.verifier.base import VerifierFailed, VerifierOk
from devharness.verifier.builtin.feature_spec_claim import FeatureSpecClaimVerifier


class _OkSuite:
    async def verify(self, ctx):
        return VerifierOk(name="test_suite", evidence={})


class _OkParallax:
    async def verify(self, ctx):
        return VerifierOk(name="parallax_verify", evidence={})


def _verify(diff_content, **extra):
    v = FeatureSpecClaimVerifier(test_suite=_OkSuite(), parallax_verify=_OkParallax())
    return asyncio.run(v.verify({"spec_claim": "add X", "diff_content": diff_content, **extra}))


def test_no_test_file_touched_fails():
    r = _verify("diff --git a/src/foo.py b/src/foo.py\n+++ b/src/foo.py\n+def foo(): return 1\n")
    assert isinstance(r, VerifierFailed) and "test_coverage axis" in r.reason


def test_test_file_touched_but_no_new_test_def_fails():
    # only a fixture/import changed — no new def test_/class ...Test... line
    r = _verify(
        "diff --git a/tests/test_foo.py b/tests/test_foo.py\n+++ b/tests/test_foo.py\n"
        "+import pytest\n+@pytest.fixture\n+def client():\n+    return object()\n"
    )
    assert isinstance(r, VerifierFailed) and "test_coverage axis" in r.reason


def test_new_test_function_passes():
    r = _verify(
        "diff --git a/tests/test_foo.py b/tests/test_foo.py\n+++ b/tests/test_foo.py\n"
        "+def test_foo():\n+    assert foo() == 1\n"
    )
    assert isinstance(r, VerifierOk)
    assert r.evidence["test_coverage"]["added_test_functions"] == ["tests/test_foo.py::test_foo"]


def test_new_async_test_function_passes():
    # a live pattern in this repo's own tests (e.g. test_console_tui.py's `async def test_...`)
    r = _verify(
        "diff --git a/tests/test_foo.py b/tests/test_foo.py\n+++ b/tests/test_foo.py\n"
        "+async def test_foo():\n+    assert await foo() == 1\n"
    )
    assert isinstance(r, VerifierOk)
    assert r.evidence["test_coverage"]["added_test_functions"] == ["tests/test_foo.py::test_foo"]


def test_modifying_an_existing_test_body_without_a_new_def_fails():
    # only the assertion inside an EXISTING test changed — no NEW def test_/class line added
    r = _verify(
        "diff --git a/tests/test_foo.py b/tests/test_foo.py\n+++ b/tests/test_foo.py\n"
        "-    assert foo() == 1\n+    assert foo() == 2\n"
    )
    assert isinstance(r, VerifierFailed) and "test_coverage axis" in r.reason


def test_new_test_class_passes():
    r = _verify(
        "diff --git a/tests/test_bar.py b/tests/test_bar.py\n+++ b/tests/test_bar.py\n"
        "+class FooTest:\n+    def test_x(self):\n+        assert True\n"
    )
    assert isinstance(r, VerifierOk)


def test_axis_runs_on_intermediate_task_too():
    # NOT final-task-gated, unlike spec_criteria — an intermediate task with no new test still fails
    r = _verify("diff --git a/src/foo.py b/src/foo.py\n+++ b/src/foo.py\n+def foo(): return 1\n",
                is_final_task=False)
    assert isinstance(r, VerifierFailed) and "test_coverage axis" in r.reason


# --- language-aware axis (rev 0.3.98): the language is inferred from test_command ---

def test_rust_test_attribute_in_src_rs_passes():
    # idiomatic Rust unit test: #[test] inside src/*.rs (NOT under tests/, NOT a test_*.py name)
    r = _verify(
        "diff --git a/src/lib.rs b/src/lib.rs\n+++ b/src/lib.rs\n"
        "+#[cfg(test)]\n+mod tests {\n+    #[test]\n+    fn adds_two() { assert_eq!(2, 1 + 1); }\n+}\n",
        test_command=["cargo", "test"],
    )
    assert isinstance(r, VerifierOk)
    assert r.evidence["test_coverage"]["added_test_functions"] == ["src/lib.rs::#[test]"]


def test_rust_tokio_test_attribute_passes():
    r = _verify(
        "diff --git a/src/lib.rs b/src/lib.rs\n+++ b/src/lib.rs\n"
        "+    #[tokio::test]\n+    async fn runs() { assert!(true); }\n",
        test_command=["cargo", "test"],
    )
    assert isinstance(r, VerifierOk)


def test_rust_cfg_test_module_alone_does_not_count():
    # a #[cfg(test)] module marker with NO #[test] inside adds no real test coverage — must fail
    r = _verify(
        "diff --git a/src/lib.rs b/src/lib.rs\n+++ b/src/lib.rs\n"
        "+#[cfg(test)]\n+mod tests {\n+    use super::*;\n+}\n",
        test_command=["cargo", "test"],
    )
    assert isinstance(r, VerifierFailed) and "test_coverage axis failed (rust)" in r.reason


def test_rust_command_but_python_test_line_does_not_count():
    # under a cargo command, a Python-style `def test_` in a .py file is not the Rust signal
    r = _verify(
        "diff --git a/tests/test_foo.py b/tests/test_foo.py\n+++ b/tests/test_foo.py\n"
        "+def test_foo():\n+    assert True\n",
        test_command=["cargo", "test"],
    )
    assert isinstance(r, VerifierFailed)


def test_js_it_call_in_spec_file_passes():
    r = _verify(
        "diff --git a/src/foo.test.ts b/src/foo.test.ts\n+++ b/src/foo.test.ts\n"
        "+it('adds', () => { expect(1 + 1).toBe(2); });\n",
        test_command=["npx", "jest"],
    )
    assert isinstance(r, VerifierOk)


def test_go_test_func_in_test_go_passes():
    r = _verify(
        "diff --git a/foo_test.go b/foo_test.go\n+++ b/foo_test.go\n"
        "+func TestAdds(t *testing.T) { if 1+1 != 2 { t.Fail() } }\n",
        test_command=["go", "test", "./..."],
    )
    assert isinstance(r, VerifierOk)


def test_windows_shim_extensions_map_to_the_right_language():
    # reviewer F1: cargo.exe / npm.cmd / a full path must not silently fall to python on Windows
    from devharness.verifier.builtin._test_coverage import language_for_test_command
    assert language_for_test_command(["cargo.exe", "test"]) == "rust"
    assert language_for_test_command(["C:\\Users\\me\\.cargo\\bin\\cargo.exe", "test"]) == "rust"
    assert language_for_test_command(["npm.cmd", "test"]) == "js"
    assert language_for_test_command(["go", "test", "./..."]) == "go"
    assert language_for_test_command(["python", "-m", "pytest"]) == "python"
    assert language_for_test_command(None) == "python"


def test_js_chained_it_only_and_test_each_pass():
    # reviewer F2: it.only( / test.each( chained forms must count, not just bare it( / test(
    r = _verify(
        "diff --git a/src/foo.spec.ts b/src/foo.spec.ts\n+++ b/src/foo.spec.ts\n"
        "+it.only('adds', () => { expect(1).toBe(1); });\n",
        test_command=["npx", "vitest", "run"],
    )
    assert isinstance(r, VerifierOk)


def test_python_default_unchanged_when_no_test_command():
    # the historical single-arg behaviour: no test_command → python detection, exactly as before
    r = _verify(
        "diff --git a/tests/test_foo.py b/tests/test_foo.py\n+++ b/tests/test_foo.py\n"
        "+def test_foo():\n+    assert True\n"
    )
    assert isinstance(r, VerifierOk)
    assert r.evidence["test_coverage"]["added_test_functions"] == ["tests/test_foo.py::test_foo"]
