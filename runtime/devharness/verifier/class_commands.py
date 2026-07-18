"""Per-class verifier commands the live driver must construct (C0f).

`bugfix_regression` runs `regression_command` (the named regression test; exit 0 iff it passes) and
`refactor_behavior_preserving` runs `pass_fail_command` (emits `<test_id> pass|fail` per test). The
verifiers read these from context; nothing built them, so bugfix/refactor could not run the LIVE
loop even though their verifier+reviewer logic is correct. These builders close that gap from the
task's existing fields.
"""

import json
import re
import shutil
from pathlib import Path

def language_for_test_command(test_command) -> str:
    """Infer the target language from the verifier's test command (the operator sets it on the build
    target; rev 0.3.98; moved here at rev 0.4.9 — the bugfix/refactor command builders dispatch on it
    too). Defaults to python — the historical behaviour for an unset/pytest command."""
    if not test_command:
        return "python"
    head = (test_command[0] if isinstance(test_command, (list, tuple)) else str(test_command)).lower()
    head = head.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    for ext in (".exe", ".cmd", ".bat", ".ps1"):  # a Windows shim: cargo.exe / npm.cmd → cargo / npm
        if head.endswith(ext):
            head = head[: -len(ext)]
            break
    if head == "cargo":
        return "rust"
    if head == "go":
        return "go"
    if head in ("npx", "npm", "yarn", "pnpm", "jest", "vitest", "node"):
        return "js"
    return "python"


# Emit one "<nodeid> pass|fail" line per test via pytest's built-in JUnit XML + stdlib parsing — a
# self-contained command needing no helper file in the worktree. A testcase with a failure/error
# child is `fail`; anything else (incl. skipped) is `pass`. The same command runs baseline and post,
# so the pass/fail-set comparison is internally consistent.
_PASS_FAIL_SRC = (
    "import subprocess,sys,tempfile,xml.etree.ElementTree as ET;"
    "f=tempfile.mktemp(suffix='.xml');"
    # capture_output so the inner pytest's progress text never leaks to stdout — only the
    # "<nodeid> pass|fail" lines below reach the caller (else _capture parses pytest noise as tests).
    "subprocess.run([sys.executable,'-m','pytest','-q','-p','no:cacheprovider','--junit-xml',f]+sys.argv[1:],capture_output=True);"
    "r=ET.parse(f).getroot();"
    "[print((tc.get('classname','') or '')+'::'+(tc.get('name','') or ''),"
    "'fail' if (tc.find('failure') is not None or tc.find('error') is not None) else 'pass') "
    "for tc in r.iter('testcase')]"
)

# Rust equivalents (rev 0.4.9): cargo has no per-test-file runner and no machine format on stable, so
# both wrappers parse the stable `test <name> ... ok|FAILED|ignored` lines. Self-contained python -c
# commands (no helper file in the worktree), mirroring the pytest wrapper's shape.
#
# Regression (argv[1] = the tests/<stem>.rs integration-test target): exit 0 iff cargo exits 0 AND at
# least one test actually ran with zero failures — `cargo test --test X` on a file with no matching
# tests prints "0 passed ... ok" and exits 0, which would VACUOUSLY PASS the post axis (the C0-class
# false-certification). A compile error exits nonzero → fail, which is the demonstrated-failure state
# the baseline axis expects when the regression test references the fix's new code.
_CARGO_REGRESSION_SRC = (
    "import re,subprocess,sys;"
    "r=subprocess.run(['cargo','test','--test',sys.argv[1],'--no-fail-fast'],capture_output=True,text=True);"
    "m=re.search(r'test result: \\w+\\. (\\d+) passed; (\\d+) failed',r.stdout);"
    "sys.exit(0 if (r.returncode==0 and m and int(m.group(1))>=1 and int(m.group(2))==0) else 1)"
)
# Per-test pass/fail across ALL targets (unit + integration + doc): one `<id> pass|fail` line each.
# Ids are whitespace-sanitized (doc-test names contain spaces — `src/lib.rs - add (line 5)` — and the
# refactor verifier's _capture splits on whitespace) and the doc-test `(line N)` suffix is STRIPPED —
# a behavior-preserving refactor shifts lines, and a line number inside the id would rename every
# doc-test below the change (guaranteed false-reject; review catch F1). Duplicate ids across targets
# (the same `mod tests` fn name in lib and bin) get a deterministic `#2` suffix so a fail in one
# target can't be masked by a same-named pass in a later one (review catch F3; cargo's target order
# is stable, so baseline/post suffixes agree). `ignored` maps to pass, matching skipped→pass on the
# pytest side. A baseline compile error yields no lines → an empty baseline set → the refactor
# verifier reports the divergence (fail closed).
_CARGO_PASS_FAIL_SRC = (
    "import re,subprocess\n"
    "r=subprocess.run(['cargo','test','--no-fail-fast'],capture_output=True,text=True)\n"
    "seen={}\n"
    "for m in re.finditer(r'^test (.+?) \\.\\.\\. (ok|FAILED|ignored)',r.stdout,re.M):\n"
    "    n='_'.join(re.sub(r'\\s*\\(line \\d+\\)$','',m.group(1)).split())\n"
    "    c=seen.get(n,0); seen[n]=c+1\n"
    "    print(n if c==0 else n+'#'+str(c+1),'fail' if m.group(2)=='FAILED' else 'pass')\n"
)


# dependency_bump field derivation (rev 0.3.70): the director's decomposition classes the task
# correctly but cannot know the class fields (the concrete version is discovered by the WORKER at
# build time), and LLM-authored fields must never reach a subprocess (F4). So the driver derives
# them DETERMINISTICALLY from the realized diff — the C0 verify-what-happened philosophy — filling
# only the fields the plan left empty (an operator-injected task's explicit fields always win).

_MANIFEST_KINDS = ("requirements", "pyproject", "npm")  # + package.json, by basename (rev 0.4.8)
# keyed by ecosystem — a stray poetry.lock in an npm worktree must not become the npm bump's
# lockfile (first-hit-wins across ecosystems would false-reject the lockfile axis; review catch)
_LOCKFILE_NAMES = {"pip": ("poetry.lock", "uv.lock", "Pipfile.lock"),
                   "npm": ("package-lock.json", "npm-shrinkwrap.json")}
# name[extras]? (==|>=|~=|===) version — extras + range specifiers are legitimate bump shapes
# (jqlite's real bump was rich[color]==13.9.4); comments/markers are stripped before matching.
_DEP_RE = re.compile(
    r"([A-Za-z0-9][A-Za-z0-9._-]*)(?:\[[^\]]*\])?\s*(?:==|>=|~=|===)\s*([A-Za-z0-9][A-Za-z0-9.!+*_-]*)"
)
# a JSON object key on an added package.json line (optionally npm-scoped: @scope/name)
_NPM_KEY_RE = re.compile(r'"((?:@[A-Za-z0-9._-]+/)?[A-Za-z0-9._-]+)"\s*:')
_NPM_DEP_SECTIONS = ("dependencies", "devDependencies", "optionalDependencies", "peerDependencies")


def _manifest_kind(path: str) -> str | None:
    base = path.rsplit("/", 1)[-1].lower()
    if base == "pyproject.toml":
        return "pyproject"
    if base.startswith("requirements") and base.endswith(".txt"):
        return "requirements"
    if base == "package.json":
        return "npm"
    return None


def _npm_pairs(added_keys, worktree_path, manifest_rel) -> set:
    """(name, bare_version) for each diff-added key that is a REAL dependency entry in the
    worktree's package.json. The manifest is parsed as JSON (deterministic — the verified artifact,
    not the diff's text) and intersected with the added-line keys, so JSON noise on added lines
    (`"version"`, `"name"`, an `"engines"` entry) can never match: those keys don't appear in a
    dependency section. The version is the manifest spec with its range prefix stripped
    (``^10.1.3`` → ``10.1.3``); an unpinnable spec (``*``, ``latest``) yields no pair → fail closed."""
    try:
        data = json.loads((Path(worktree_path) / manifest_rel).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set()
    specs: dict = {}  # name -> {spec per section}: a name in TWO sections with DIFFERENT specs
    for section in _NPM_DEP_SECTIONS:  # yields 2+ pairs -> the ambiguity rule fails closed (a
        entries = data.get(section)    # dict would silently prefer the later section; review catch)
        if isinstance(entries, dict):
            for name, spec in entries.items():
                if isinstance(spec, str):
                    specs.setdefault(name, set()).add(spec)
    pairs = set()
    for name in added_keys:
        for spec in specs.get(name, ()):
            if any(ch.isspace() for ch in spec) or "||" in spec:
                continue  # compound range (">=10 <11", "a || b") — unpinnable, no pair (fail closed)
            version = re.sub(r"^[^0-9]*", "", spec)
            if version:
                pairs.add((name, version))
    return pairs


def derive_bump_fields(diff_content: str, worktree_path, python="python") -> dict:
    """Derive dependency_bump verifier fields from the realized diff (unified, `git diff --cached
    HEAD` shape) + the worktree. Returns {} values for anything underivable — the verifier fails
    closed naming them. Exactly ONE distinct (name, version) pair must appear in the manifest's
    added lines; multiple distinct pairs stay empty (a first-match guess could verify the wrong
    dependency). lockfile_path comes from the WORKTREE (not the diff): a project whose lockfile
    exists but was not regenerated must still face the lockfile axis, not skip it.

    Manifest ecosystems: requirements*.txt / pyproject.toml (pip) and package.json (npm, rev
    0.4.8 — the first npm bump; the pair comes from parsing the worktree manifest as JSON
    intersected with diff-added keys, see ``_npm_pairs``; resolution via ``npm install --dry-run``)."""
    fields = {"dependency_name": "", "target_version": "", "manifest_path": "",
              "lockfile_path": "", "bump_command": ""}
    manifest, kind, pairs, npm_keys = None, None, set(), set()
    current, current_kind = None, None
    for line in (diff_content or "").splitlines():
        if line.startswith("+++ b/"):
            current = line[6:].strip()
            current_kind = _manifest_kind(current)
            if current_kind and manifest is None:
                manifest, kind = current, current_kind
            continue
        if current_kind and line.startswith("+") and not line.startswith("+++"):
            if current_kind == "npm":
                m = _NPM_KEY_RE.search(line[1:])
                if m:
                    npm_keys.add(m.group(1))
            else:
                body = line[1:].split("#", 1)[0].split(";", 1)[0]  # strip comments + env markers
                m = _DEP_RE.search(body)
                if m:
                    pairs.add((m.group(1), m.group(2)))
    if manifest is None:
        return fields
    fields["manifest_path"] = manifest
    if kind == "npm":
        # UNION with any pip pairs from the same diff — a mixed-ecosystem bump must hit the
        # ambiguity rule below, not silently derive from npm alone (review catch)
        pairs |= _npm_pairs(npm_keys, worktree_path, manifest)
    if len(pairs) == 1:
        fields["dependency_name"], fields["target_version"] = next(iter(pairs))
    for name in _LOCKFILE_NAMES["npm" if kind == "npm" else "pip"]:
        if (Path(worktree_path) / name).exists():
            fields["lockfile_path"] = name
            break
    if kind == "npm":
        # npm is npm.cmd on Windows — subprocess needs the resolved path; absent npm stays "" and
        # the verifier fails closed NAMING bump_command rather than crashing on a ghost executable.
        npm = shutil.which("npm")
        fields["bump_command"] = [npm, "install", "--dry-run"] if npm else ""
    elif kind == "requirements":
        fields["bump_command"] = [python, "-m", "pip", "install", "--dry-run", "-r", manifest]
    else:
        fields["bump_command"] = [python, "-m", "pip", "install", "--dry-run", "."]
    return fields


_TEST_FILE_RE = re.compile(r"(?:^|/)(?:test_[^/]*\.py|[^/]*_test\.py)$")
# a cargo INTEGRATION-test target: a direct child of tests/ (subdirs are helper modules, not
# targets, and unit #[test]s inside src/ have no per-file runner — out of scope, fails closed)
_RUST_TEST_FILE_RE = re.compile(r"^tests/[^/]+\.rs$")


def _is_test_file(path: str) -> bool:
    """A python test file, by pytest's default discovery names or a tests/ location."""
    if not path.endswith(".py"):
        return False
    return bool(_TEST_FILE_RE.search(path)) or "tests/" in path or path.startswith("tests/")


def regression_test_files(diff_content: str, language: str = "python") -> list[str]:
    """The test files added or modified in the realized diff (unified, `+++ b/<path>` headers).

    A `bugfix` task's worker writes its regression test into the diff; this recovers which file(s).
    Deletes (`+++ /dev/null`) are skipped. ``language`` picks the detection rule (rev 0.4.9):
    Rust = a cargo integration-test target (`tests/*.rs`); js/go have no bugfix support yet and
    intentionally match nothing → the verifier fails closed naming the gap, not a wrong guess."""
    if language == "rust":
        predicate = lambda p: bool(_RUST_TEST_FILE_RE.match(p))  # noqa: E731
    elif language == "python":
        predicate = _is_test_file
    else:
        predicate = lambda p: False  # noqa: E731
    out: list[str] = []
    for line in (diff_content or "").splitlines():
        if line.startswith("+++ b/"):
            path = line[6:].strip()
            if predicate(path) and path not in out:
                out.append(path)
    return out


def derive_regression_test_ref(diff_content: str, language: str = "python") -> str:
    """The single regression-test file to run for a director-planned bugfix whose `regression_test_ref`
    the director left empty (it can't know the path before the worker writes it). Exactly ONE test file
    in the diff → that path; zero or multiple → "" (the verifier then fails closed naming the gap, since
    a first-match guess could run the wrong test). No LLM text reaches a subprocess — the path is a
    realized diff header (rev 0.3.73), the C0 verify-what-happened philosophy."""
    files = regression_test_files(diff_content, language)
    return files[0] if len(files) == 1 else ""


def regression_command(regression_test_ref, python="python", language="python"):
    """The command `bugfix_regression` runs: the named regression test, exit 0 iff it passes.

    Rust (rev 0.4.9): runs the ``tests/<stem>.rs`` integration target via the wrapper — exit 0
    requires ≥1 test ran with 0 failures (a no-match run prints "0 passed … ok" and exits 0, which
    would vacuously pass the post axis)."""
    if language == "rust":
        stem = Path(str(regression_test_ref)).stem
        return [python, "-c", _CARGO_REGRESSION_SRC, stem]
    return [python, "-m", "pytest", str(regression_test_ref), "-q", "-p", "no:cacheprovider"]


def pass_fail_command(test_target, python="python", language="python"):
    """The command `refactor_behavior_preserving` runs: emits `<nodeid> pass|fail` per test.

    Rust (rev 0.4.9): all targets via ``cargo test --no-fail-fast``, ids whitespace-sanitized;
    ``test_target`` is not meaningful to cargo and is ignored."""
    if language == "rust":
        return [python, "-c", _CARGO_PASS_FAIL_SRC]
    return [python, "-c", _PASS_FAIL_SRC, str(test_target)]
