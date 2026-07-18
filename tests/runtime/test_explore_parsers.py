"""B1.5: per-manifest parsers extract declared dependencies."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.explore.parsers import cargo, gemfile, go_mod, package_json, pyproject, requirements


def test_pyproject(tmp_path):
    p = tmp_path / "pyproject.toml"
    p.write_text(
        '[project]\nname="x"\ndependencies = ["fastapi>=0.1", "uvicorn[standard]>=0.2"]\n'
        '[project.optional-dependencies]\ntest = ["pytest>=8"]\n'
    )
    assert set(pyproject.parse(str(p))) == {"fastapi", "uvicorn", "pytest"}


def test_package_json(tmp_path):
    p = tmp_path / "package.json"
    p.write_text('{"dependencies": {"react": "^18"}, "devDependencies": {"vitest": "^1"}}')
    assert set(package_json.parse(str(p))) == {"react", "vitest"}


def test_cargo(tmp_path):
    p = tmp_path / "Cargo.toml"
    p.write_text('[dependencies]\naxum = "0.8"\n[dev-dependencies]\ninsta = "1"\n')
    assert set(cargo.parse(str(p))) == {"axum", "insta"}


def test_requirements(tmp_path):
    p = tmp_path / "requirements.txt"
    p.write_text("flask==3.0\n# comment\n-e .\nrequests>=2\n")
    assert set(requirements.parse(str(p))) == {"flask", "requests"}


def test_gemfile(tmp_path):
    p = tmp_path / "Gemfile"
    p.write_text('source "https://rubygems.org"\ngem "rails", "~> 7"\ngem "rspec"\n')
    assert set(gemfile.parse(str(p))) == {"rails", "rspec"}


def test_go_mod(tmp_path):
    p = tmp_path / "go.mod"
    p.write_text(
        "module example.com/x\ngo 1.21\nrequire (\n    github.com/gin-gonic/gin v1.9.0\n    github.com/stretchr/testify v1.8.0\n)\n"
    )
    assert set(go_mod.parse(str(p))) == {"github.com/gin-gonic/gin", "github.com/stretchr/testify"}
