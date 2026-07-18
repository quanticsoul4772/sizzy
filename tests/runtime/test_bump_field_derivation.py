"""rev 0.3.70: dependency_bump class fields derived from the realized diff.

The director's decomposition classes a bump correctly but leaves the class fields empty (only the
operator-injected script flow ever set them) — live on the first console-driven dependency_bump,
the empty bump_command crashed the dispatch (WinError 87, no terminal, W re-crashed forever).
The driver now derives the fields DETERMINISTICALLY from the realized diff (verify what happened;
no LLM text reaches a subprocess), and the verifier fails closed on anything underivable.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.verifier.class_commands import derive_bump_fields


def _diff(path, *added):
    lines = [f"diff --git a/{path} b/{path}", f"--- a/{path}", f"+++ b/{path}", "@@ -1 +1 @@"]
    lines += [f"+{a}" for a in added]
    return "\n".join(lines) + "\n"


def test_requirements_bump_derives_all_fields(tmp_path):
    fields = derive_bump_fields(_diff("requirements.txt", "packaging==25.0"), tmp_path)
    assert fields["dependency_name"] == "packaging"
    assert fields["target_version"] == "25.0"
    assert fields["manifest_path"] == "requirements.txt"
    assert fields["lockfile_path"] == ""  # no lockfile in the worktree
    assert fields["bump_command"] == ["python", "-m", "pip", "install", "--dry-run", "-r",
                                      "requirements.txt"]


def test_extras_and_range_specifiers_are_legitimate_bump_shapes(tmp_path):
    # jqlite's real bump was rich[color]==13.9.4; pyproject deps are typically "name>=x"
    fields = derive_bump_fields(_diff("requirements.txt", "rich[color]==13.9.4"), tmp_path)
    assert (fields["dependency_name"], fields["target_version"]) == ("rich", "13.9.4")
    fields = derive_bump_fields(_diff("pyproject.toml", '    "packaging>=25.0",'), tmp_path)
    assert (fields["dependency_name"], fields["target_version"]) == ("packaging", "25.0")
    assert fields["bump_command"] == ["python", "-m", "pip", "install", "--dry-run", "."]


def test_comments_and_markers_are_stripped(tmp_path):
    fields = derive_bump_fields(
        _diff("requirements.txt", 'packaging==25.0  # the bump ; python_version>="3.8"'), tmp_path)
    assert (fields["dependency_name"], fields["target_version"]) == ("packaging", "25.0")


def test_multiple_distinct_pairs_stay_empty(tmp_path):
    # a first-match guess could verify the WRONG dependency — ambiguity fails closed downstream
    fields = derive_bump_fields(
        _diff("requirements.txt", "packaging==25.0", "requests==2.31.0"), tmp_path)
    assert fields["dependency_name"] == "" and fields["target_version"] == ""
    assert fields["manifest_path"] == "requirements.txt"  # still known; the verifier names the gap


def test_no_manifest_change_derives_nothing(tmp_path):
    fields = derive_bump_fields(_diff("src/app.py", "x = 1"), tmp_path)
    assert all(not v for v in fields.values())


def test_lockfile_comes_from_the_worktree_not_the_diff(tmp_path):
    # a project WHOSE lockfile exists but was not regenerated must still face the lockfile axis —
    # deriving from the diff would silently skip it (the review's gate-weakening catch)
    (tmp_path / "uv.lock").write_text("stale\n")
    fields = derive_bump_fields(_diff("requirements.txt", "packaging==25.0"), tmp_path)
    assert fields["lockfile_path"] == "uv.lock"


def test_explicit_task_fields_win_is_the_callers_contract(tmp_path):
    # the drivers fill ONLY empty vctx fields — mirror that contract here as documentation
    fields = derive_bump_fields(_diff("requirements.txt", "packaging==25.0"), tmp_path)
    vctx = {"dependency_name": "rich", "target_version": "", "bump_command": "",
            "manifest_path": "", "lockfile_path": ""}
    for k, v in fields.items():
        if not vctx.get(k):
            vctx[k] = v
    assert vctx["dependency_name"] == "rich"  # operator-injected value survived
    assert vctx["target_version"] == "25.0"  # empty was filled

# --- npm (rev 0.4.8: the first npm dependency_bump — package.json manifest kind) ---


def _npm_manifest(tmp_path, dev_deps=None, deps=None):
    import json

    (tmp_path / "package.json").write_text(json.dumps({
        "name": "proj", "version": "0.1.0", "type": "module",
        "engines": {"node": ">=20"},
        "dependencies": deps or {}, "devDependencies": dev_deps or {},
    }, indent=2), encoding="utf-8")


def test_npm_dev_dependency_bump_derives_all_fields(tmp_path, monkeypatch):
    import devharness.verifier.class_commands as cc

    monkeypatch.setattr(cc.shutil, "which", lambda n: r"C:\nodejs\npm.cmd" if n == "npm" else None)
    _npm_manifest(tmp_path, dev_deps={"c8": "^10.1.3"})
    (tmp_path / "package-lock.json").write_text("{}", encoding="utf-8")
    fields = derive_bump_fields(_diff("package.json", '    "c8": "^10.1.3",'), tmp_path)
    assert (fields["dependency_name"], fields["target_version"]) == ("c8", "10.1.3")
    assert fields["manifest_path"] == "package.json"
    assert fields["lockfile_path"] == "package-lock.json"
    assert fields["bump_command"] == [r"C:\nodejs\npm.cmd", "install", "--dry-run"]


def test_npm_json_noise_on_added_lines_never_matches(tmp_path):
    # the diff also touches "version" / "engines" JSON keys — semver-shaped values that are NOT
    # dependencies; the manifest-section intersection must reject them, leaving the one real pair
    _npm_manifest(tmp_path, dev_deps={"@types/node": "~24.0.0"})
    diff = _diff("package.json", '  "version": "0.2.0",', '  "node": ">=20",',
                 '    "@types/node": "~24.0.0",')
    fields = derive_bump_fields(diff, tmp_path)
    assert (fields["dependency_name"], fields["target_version"]) == ("@types/node", "24.0.0")


def test_npm_underivable_shapes_fail_closed(tmp_path, monkeypatch):
    import devharness.verifier.class_commands as cc

    # two distinct dependency changes -> ambiguous -> empty (the verifier fails closed naming them)
    _npm_manifest(tmp_path, dev_deps={"c8": "^10.1.3", "eslint": "^9.0.0"})
    diff = _diff("package.json", '    "c8": "^10.1.3",', '    "eslint": "^9.0.0",')
    fields = derive_bump_fields(diff, tmp_path)
    assert fields["dependency_name"] == "" and fields["target_version"] == ""
    # an unpinnable spec ("*") yields no version -> empty
    _npm_manifest(tmp_path, dev_deps={"c8": "*"})
    fields = derive_bump_fields(_diff("package.json", '    "c8": "*",'), tmp_path)
    assert fields["dependency_name"] == ""
    # npm not installed -> bump_command stays "" (verifier fails closed NAMING it, no ghost exec)
    monkeypatch.setattr(cc.shutil, "which", lambda n: None)
    _npm_manifest(tmp_path, dev_deps={"c8": "^10.1.3"})
    fields = derive_bump_fields(_diff("package.json", '    "c8": "^10.1.3",'), tmp_path)
    assert fields["bump_command"] == ""


def test_npm_review_hardening_edges(tmp_path):
    import json

    # (a) one name in TWO sections with DIFFERENT specs -> ambiguous -> fail closed (a dict-merge
    # would silently prefer the later section and certify the wrong version)
    (tmp_path / "package.json").write_text(json.dumps({
        "dependencies": {"c8": "^9.1.0"}, "devDependencies": {"c8": "^10.1.3"}}), encoding="utf-8")
    fields = derive_bump_fields(_diff("package.json", '    "c8": "^10.1.3",'), tmp_path)
    assert fields["dependency_name"] == ""
    # (b) compound range specs are unpinnable -> no pair -> fail closed
    _npm_manifest(tmp_path, dev_deps={"c8": ">=10 <11"})
    fields = derive_bump_fields(_diff("package.json", '    "c8": ">=10 <11",'), tmp_path)
    assert fields["dependency_name"] == ""
    # (c) a stray Python lockfile never becomes the npm bump's lockfile
    _npm_manifest(tmp_path, dev_deps={"c8": "^10.1.3"})
    (tmp_path / "poetry.lock").write_text("", encoding="utf-8")
    fields = derive_bump_fields(_diff("package.json", '    "c8": "^10.1.3",'), tmp_path)
    assert fields["lockfile_path"] == ""
    # (d) a mixed-ecosystem diff (npm + pip manifests changed together) is ambiguous -> fail closed
    mixed = (_diff("package.json", '    "c8": "^10.1.3",')
             + _diff("requirements.txt", "packaging==25.0"))
    fields = derive_bump_fields(mixed, tmp_path)
    assert fields["dependency_name"] == ""
