"""Deterministic diff-text scan for the test_coverage axis (feature_spec_claim's 4th axis).

No LLM, no file I/O — text-scans the realized unified diff for at least one NEW test-defining line
added inside a test file. Mirrors the scope_guard/secret_guard line-scan convention (decision rule is
code, not a model verdict). Gaming caveat (documented, not solved, same class as scope_guard/
secret_guard): a test-defining token inside a comment or string literal spoofs the regex. Acceptable
because this verifier's typical input is the harness's own trusted developer LLM's diff, not an
adversarial actor's; OSS diffs get separate, already-documented trust-model caveats (F1/F4/F7).

Language-aware (rev 0.3.98): the loop is no longer Python-only. The scan dispatches on the target
language — inferred from the verifier's ``test_command`` — because each ecosystem writes and locates
tests differently, and the Python-only patterns yield an empty result (→ a false axis failure) on a
Rust/JS/Go feature that DID add real tests. Rust is the sharpest case: idiomatic unit tests live in
``#[cfg(test)] mod tests`` inside any ``src/*.rs``, so the "is this path a test file" gate that works
for Python does not apply — Rust keys on the ``#[test]`` attribute line in any ``.rs`` file instead.
"""

import re

_DIFF_GIT_RE = re.compile(r'^diff --git a/.+? b/(?P<path>.+)$')
_PLUS_HEADER_RE = re.compile(r'^\+\+\+ b/(?P<path>.+)$')
_TEST_BASENAME_RE = re.compile(r'^(test_\w+\.py|\w+_test\.py)$')
# optional `async` before `def` — a live pattern in this repo's own tests (e.g. test_console_tui.py's
# `async def test_...`).
_PY_TEST_DEF_RE = re.compile(r'^\+\s*(?:(?:async\s+)?def\s+(?P<fn>test_\w*)\s*\(|class\s+(?P<cls>\w*Test\w*)\b)')
# Rust: the test ATTRIBUTE line — #[test], #[tokio::test], #[rstest]. The optional `(?:\w+::)?` cannot
# consume `cfg(` (it needs `::`, sees `(`), so `#[cfg(test)]` does NOT match — a cfg(test) module marker
# is not itself an added test. The fn name is on the following line, so the identifier is the attribute.
_RUST_TEST_DEF_RE = re.compile(r'^\+\s*#\[(?:\w+::)?test\w*\]')
# JS/TS: an `it(...)` / `test(...)` call (jest/vitest), including the chained `it.only(` / `test.each(`
# forms (the `(?:\.\w+)?` — without it those chains false-negative).
_JS_TEST_DEF_RE = re.compile(r'^\+.*\b(?P<fn>it|test)(?:\.\w+)?\s*\(')
# Go: a `func TestXxx(` declaration in a _test.go file.
_GO_TEST_DEF_RE = re.compile(r'^\+\s*func\s+(?P<fn>Test\w*)\s*\(')


def is_test_path(path: str) -> bool:
    """A path counts as a Python test file if it lives under a tests/ directory (any depth) or its
    basename follows the test_*.py / *_test.py convention."""
    p = (path or "").replace("\\", "/")
    if "/tests/" in f"/{p}":
        return True
    return bool(_TEST_BASENAME_RE.match(p.rsplit("/", 1)[-1]))


def _is_js_test_path(path: str) -> bool:
    p = (path or "").replace("\\", "/").rsplit("/", 1)[-1].lower()
    return (".test." in p or ".spec." in p) and p.endswith((".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"))


# language -> (path predicate, added-test-line regex). Rust deliberately has NO test-path gate: unit
# tests live in any src/*.rs, so the .rs extension + the #[test] attribute is the whole signal.
_LANG_RULES = {
    "python": (is_test_path, _PY_TEST_DEF_RE),
    "rust": (lambda p: (p or "").replace("\\", "/").endswith(".rs"), _RUST_TEST_DEF_RE),
    "js": (_is_js_test_path, _JS_TEST_DEF_RE),
    "go": (lambda p: (p or "").replace("\\", "/").endswith("_test.go"), _GO_TEST_DEF_RE),
}


# moved to class_commands (rev 0.4.9) — the bugfix/refactor command builders need it too, and the
# builtin package imports class_commands, so the import direction only works this way around.
# Re-exported here for the existing importers (feature_spec_claim + tests).
from devharness.verifier.class_commands import language_for_test_command  # noqa: F401


def added_test_functions(diff_content: str, language: str = "python") -> list[str]:
    """path::name identifiers for every NEW test-defining line ADDED inside a test file, for the given
    language. Empty list = the diff adds no qualifying test coverage. Modifying an EXISTING test's body
    (no new def/attribute line) does not count — deliberately, to block trivial-touch gaming."""
    path_ok, def_re = _LANG_RULES.get(language, _LANG_RULES["python"])
    current_path = None
    found: list[str] = []
    for line in (diff_content or "").splitlines():
        m = _DIFF_GIT_RE.match(line) or _PLUS_HEADER_RE.match(line)
        if m:
            current_path = m.group("path")
            continue
        if line.startswith(("+++", "---", "@@", "diff ")):
            continue
        if current_path is None or not path_ok(current_path) or not line.startswith("+"):
            continue
        m = def_re.match(line)
        if m:
            gd = m.groupdict()
            name = gd.get("fn") or gd.get("cls") or line[1:].strip()
            found.append(f"{current_path}::{name}")
    return found
