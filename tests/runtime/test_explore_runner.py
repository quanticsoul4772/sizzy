"""B1.5: run() builds a bounded tree, skips noise, detects manifests + signatures."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.explore.runner import run


def _build_repo(root: Path):
    (root / "pyproject.toml").write_text(
        '[project]\nname = "x"\ndependencies = ["fastapi>=0.1", "uvicorn[standard]>=0.2"]\n'
        '[project.optional-dependencies]\ntest = ["pytest>=8"]\n'
    )
    (root / "package.json").write_text('{"dependencies": {"react": "^18"}, "devDependencies": {"vitest": "^1"}}')
    (root / "requirements.txt").write_text("flask==3.0\n# comment\n")
    (root / "Cargo.toml").write_text('[dependencies]\naxum = "0.8"\ntokio = "1"\n')
    (root / "Gemfile").write_text('gem "rails"\ngem "rspec"\n')
    (root / "go.mod").write_text("module example.com/x\ngo 1.21\nrequire github.com/gin-gonic/gin v1.9.0\n")
    (root / "pytest.ini").write_text("[pytest]\n")
    (root / "Jenkinsfile").write_text("pipeline {}\n")

    (root / "src").mkdir()
    (root / "src" / "main.py").write_text("print('hi')\n")
    (root / "tests").mkdir()
    (root / "tests" / "test_x.py").write_text("def test_x(): assert True\n")
    (root / ".github" / "workflows").mkdir(parents=True)
    (root / ".github" / "workflows" / "ci.yml").write_text("name: CI\n")

    # noise dirs that must be skipped
    (root / "node_modules").mkdir()
    (root / "node_modules" / "junk.js").write_text("// junk\n")
    (root / ".git").mkdir()
    (root / ".git" / "config").write_text("[core]\n")

    # depth beyond default max_depth=5
    deep = root / "a" / "b" / "c" / "d" / "e" / "f"
    deep.mkdir(parents=True)
    (deep / "deep.txt").write_text("too deep\n")


def test_run_against_fixture(tmp_path):
    _build_repo(tmp_path)
    artifact = run(str(tmp_path), "corr-1")

    paths = {e.path for e in artifact.file_tree}
    # noise skipped
    assert not any(p.startswith("node_modules") for p in paths)
    assert not any(p.startswith(".git/") or p == ".git" for p in paths)
    # depth bounded to 5
    assert all(e.depth <= 5 for e in artifact.file_tree)
    assert "a/b/c/d/e" in paths  # depth 5 kept
    assert not any(p.startswith("a/b/c/d/e/f") for p in paths)  # depth 6+ dropped
    # ordinary content present
    assert "src/main.py" in paths
    assert "pyproject.toml" in paths


def test_all_manifests_detected(tmp_path):
    _build_repo(tmp_path)
    artifact = run(str(tmp_path), "corr-1")
    kinds = {m.manifest_kind for m in artifact.dependency_manifests}
    assert kinds == {"pyproject", "package_json", "cargo", "requirements", "gemfile", "go_mod"}
    by_kind = {m.manifest_kind: m for m in artifact.dependency_manifests}
    assert "fastapi" in by_kind["pyproject"].detected_frameworks
    assert "react" in by_kind["package_json"].detected_frameworks
    assert "axum" in by_kind["cargo"].detected_frameworks


def test_test_and_ci_signatures(tmp_path):
    _build_repo(tmp_path)
    artifact = run(str(tmp_path), "corr-1")
    frameworks = {s.test_framework for s in artifact.test_signatures}
    assert "pytest" in frameworks  # pytest.ini + tests/
    assert "cargo_test" in frameworks
    assert "go_test" in frameworks
    ci_kinds = {c.ci_kind for c in artifact.ci_configs}
    assert "github_actions" in ci_kinds
    assert "jenkins" in ci_kinds
