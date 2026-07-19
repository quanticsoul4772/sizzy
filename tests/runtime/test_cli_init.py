"""rev 0.4.29: `devharness init` — the advisory-lite bootstrap command."""

import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.__main__ import main as dispatch_main
from devharness.cli.init import main as init_main


def test_writes_both_advisory_entries_with_absolute_interpreter(tmp_path, capsys, monkeypatch):
    monkeypatch.delenv("DEVHARNESS_MCP_CONFIG", raising=False)
    target = tmp_path / "mcp.local.json"
    assert init_main(["--path", str(target)]) == 0
    cfg = json.load(open(target, encoding="utf-8"))  # json.dump output — parseable by definition
    for name in ("parallax", "mcp-reasoning"):
        entry = cfg["mcpServers"][name]
        assert entry["command"] == sys.executable and Path(entry["command"]).is_absolute()
        assert entry["args"][:2] == ["-m", "devharness.advisory"]
    out = capsys.readouterr().out
    assert "$env:DEVHARNESS_MCP_CONFIG" in out and "export DEVHARNESS_MCP_CONFIG" in out
    assert "docs/first-build.md" in out


def test_refuses_existing_file_exit_1_then_force_overwrites(tmp_path, capsys, monkeypatch):
    monkeypatch.delenv("DEVHARNESS_MCP_CONFIG", raising=False)
    target = tmp_path / "mcp.local.json"
    target.write_text("{}", encoding="utf-8")
    assert init_main(["--path", str(target)]) == 1
    assert "refused:" in capsys.readouterr().err
    assert target.read_text(encoding="utf-8") == "{}"  # untouched
    assert init_main(["--path", str(target), "--force"]) == 0
    assert "mcpServers" in target.read_text(encoding="utf-8")


def test_missing_parent_fails_closed_naming_it(tmp_path, capsys, monkeypatch):
    monkeypatch.delenv("DEVHARNESS_MCP_CONFIG", raising=False)
    target = tmp_path / "nope" / "mcp.local.json"
    assert init_main(["--path", str(target)]) == 1
    err = capsys.readouterr().err
    assert "refused:" in err and "nope" in err
    assert not target.exists()


def test_env_var_unchanged_after_run(tmp_path, monkeypatch):
    # review MAJOR: the self-validation sets DEVHARNESS_MCP_CONFIG in-process — an unrestored set
    # would poison every later config test in this pytest process
    monkeypatch.delenv("DEVHARNESS_MCP_CONFIG", raising=False)
    assert init_main(["--path", str(tmp_path / "a.json")]) == 0
    assert "DEVHARNESS_MCP_CONFIG" not in os.environ  # prior-unset case restored to unset

    monkeypatch.setenv("DEVHARNESS_MCP_CONFIG", "somewhere/else.json")
    assert init_main(["--path", str(tmp_path / "b.json")]) == 0
    assert os.environ["DEVHARNESS_MCP_CONFIG"] == "somewhere/else.json"  # prior-set case restored


def test_preset_env_pointing_elsewhere_is_called_out(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("DEVHARNESS_MCP_CONFIG", str(tmp_path / "other.json"))
    assert init_main(["--path", str(tmp_path / "new.json")]) == 0
    out = capsys.readouterr().out
    assert "currently set to" in out and "takes effect only when you re-point it" in out


def test_not_gitignored_warning_outside_any_repo(tmp_path, capsys, monkeypatch):
    # a tmp dir is outside any git repo -> check-ignore fails -> the warning must print
    monkeypatch.delenv("DEVHARNESS_MCP_CONFIG", raising=False)
    assert init_main(["--path", str(tmp_path / "mcp.local.json")]) == 0
    assert "not gitignored here" in capsys.readouterr().out


def test_repo_root_write_is_gitignored_no_warning(capsys, monkeypatch, tmp_path):
    # inside THIS repo the bare .gitignore pattern matches at any depth — no false warning.
    # write to a scratch subdir of the repo so the real mcp.local.json is untouched.
    repo = Path(__file__).resolve().parents[2]
    scratch = repo / "var"
    if not scratch.is_dir():  # var/ is gitignored and may be absent on a fresh clone
        import pytest

        pytest.skip("var/ absent — repo-depth gitignore case needs an in-repo dir")
    monkeypatch.delenv("DEVHARNESS_MCP_CONFIG", raising=False)
    target = scratch / "_init_test_mcp.local.json"
    try:
        assert init_main(["--path", str(target), "--force"]) == 0
        out = capsys.readouterr().out
        # var/ itself is ignored, so check-ignore says ignored -> no warning
        assert "not gitignored here" not in out
    finally:
        target.unlink(missing_ok=True)


def test_dispatchable_through_devharness_main(tmp_path, capsys, monkeypatch):
    monkeypatch.delenv("DEVHARNESS_MCP_CONFIG", raising=False)
    assert dispatch_main(["init", "--path", str(tmp_path / "m.json")]) == 0
    assert "wrote" in capsys.readouterr().out


def test_written_config_actually_resolves(tmp_path, monkeypatch):
    # the self-validation is real: the written file resolves through the single config source
    from devharness.mcp.config import server_cfg

    monkeypatch.delenv("DEVHARNESS_MCP_CONFIG", raising=False)
    target = tmp_path / "m.json"
    assert init_main(["--path", str(target)]) == 0
    monkeypatch.setenv("DEVHARNESS_MCP_CONFIG", str(target))
    assert server_cfg("parallax")["args"][-1] == "parallax"
    assert server_cfg("mcp-reasoning")["args"][-1] == "reasoning"
