"""rev 0.4.25: the single MCP launch-spec config source (DEVHARNESS_MCP_CONFIG, else ~/.claude.json).

An explicitly-set override never silently falls through (fail-closed, the rev-0.3.63 philosophy);
the unset default reads the home file exactly as the nine historical readers did. The overage-key
path (rev 0.4.0) preserves its exact semantics: ordered two-name top-level lookup, absent → None,
and a malformed OVERRIDE degrades to None with a stderr line — never a raise mid-retry.
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.mcp.config import (
    MCPConfigError,
    MCPConfigFileInvalid,
    MCPConfigFileMissing,
    MCPServerNotConfigured,
    overage_api_key,
    server_cfg,
)


def _write(path, obj):
    path.write_text(json.dumps(obj), encoding="utf-8")
    return path


def test_override_resolves_from_pointed_file(tmp_path, monkeypatch):
    cfg = _write(tmp_path / "mcp.json", {"mcpServers": {"parallax": {"command": "px", "args": ["--stdio"]}}})
    monkeypatch.setenv("DEVHARNESS_MCP_CONFIG", str(cfg))
    assert server_cfg("parallax") == {"command": "px", "args": ["--stdio"]}  # bare dict, no wrapping


def test_override_missing_file_fails_closed_naming_path(tmp_path, monkeypatch):
    missing = tmp_path / "nope.json"
    monkeypatch.setenv("DEVHARNESS_MCP_CONFIG", str(missing))
    with pytest.raises(MCPConfigError) as e:
        server_cfg("parallax")
    assert str(missing) in str(e.value) and "DEVHARNESS_MCP_CONFIG" in str(e.value)


def test_override_missing_server_fails_closed(tmp_path, monkeypatch):
    cfg = _write(tmp_path / "mcp.json", {"mcpServers": {"other": {"command": "x"}}})
    monkeypatch.setenv("DEVHARNESS_MCP_CONFIG", str(cfg))
    with pytest.raises(MCPConfigError):
        server_cfg("parallax")


def test_override_invalid_json_fails_closed(tmp_path, monkeypatch):
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    monkeypatch.setenv("DEVHARNESS_MCP_CONFIG", str(bad))
    with pytest.raises(MCPConfigError):
        server_cfg("parallax")


def test_unset_falls_back_to_home_file(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    _write(home / ".claude.json", {"mcpServers": {"mcp-reasoning": {"command": "mr"}}})
    monkeypatch.delenv("DEVHARNESS_MCP_CONFIG", raising=False)
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))
    assert server_cfg("mcp-reasoning") == {"command": "mr"}
    with pytest.raises(MCPConfigError) as e:
        server_cfg("parallax")
    assert "DEVHARNESS_MCP_CONFIG" in str(e.value)  # the unset-default error teaches the override


def test_mcp_config_error_is_runtime_error():
    # the console's advisory catches (e.g. the post-build auto-retro guard) rely on RuntimeError
    assert issubclass(MCPConfigError, RuntimeError)
    # the taxonomy is load-bearing for soft-contract callers (run_promote): unconfigured vs broken,
    # and the failing source's override-ness, without re-deriving the env var at call sites
    for sub in (MCPConfigFileMissing, MCPConfigFileInvalid, MCPServerNotConfigured):
        assert issubclass(sub, MCPConfigError)


def test_error_subclasses_and_is_override(tmp_path, monkeypatch):
    missing = tmp_path / "nope.json"
    monkeypatch.setenv("DEVHARNESS_MCP_CONFIG", str(missing))
    with pytest.raises(MCPConfigFileMissing) as e:
        server_cfg("parallax")
    assert e.value.is_override is True

    home = tmp_path / "home"
    home.mkdir()
    _write(home / ".claude.json", {"mcpServers": {}})
    monkeypatch.delenv("DEVHARNESS_MCP_CONFIG", raising=False)
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))
    with pytest.raises(MCPServerNotConfigured) as e2:
        server_cfg("parallax")
    assert e2.value.is_override is False


def test_shape_invalid_files_fail_closed_not_attributeerror(tmp_path, monkeypatch):
    # review catch: a list/string top level or a non-object mcpServers/server value raised
    # AttributeError PAST every MCPConfigError catch — incl. out of overage_api_key mid-retry
    home = tmp_path / "home"
    home.mkdir()  # hermetic: the overage path falls back to home, which must not be the real one
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))
    for bad in (["a", "list"], "a string", {"mcpServers": ["not", "a", "dict"]}):
        cfg = _write(tmp_path / "shape.json", bad)
        monkeypatch.setenv("DEVHARNESS_MCP_CONFIG", str(cfg))
        with pytest.raises(MCPConfigFileInvalid):
            server_cfg("parallax")
    cfg = _write(tmp_path / "shape.json", {"mcpServers": {"parallax": "not-a-dict"}})
    monkeypatch.setenv("DEVHARNESS_MCP_CONFIG", str(cfg))
    with pytest.raises(MCPConfigFileInvalid):
        server_cfg("parallax")
    # and the never-raise overage path shrugs all of these off
    assert overage_api_key() is None


def test_missing_home_file_error_teaches_the_override(tmp_path, monkeypatch):
    # review catch: the fresh-clone first-run failure (no ~/.claude.json at all) must mention
    # DEVHARNESS_MCP_CONFIG — it is the branch the install-easing pass's audience hits first
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.delenv("DEVHARNESS_MCP_CONFIG", raising=False)
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))
    with pytest.raises(MCPConfigFileMissing) as e:
        server_cfg("parallax")
    assert "DEVHARNESS_MCP_CONFIG" in str(e.value)


def test_overage_key_ordered_two_name_lookup(tmp_path, monkeypatch):
    # rev-0.4.0 semantics: top-level only, mcp-reasoning FIRST, parallax fallback — never a scan
    home = tmp_path / "home"
    home.mkdir()
    _write(home / ".claude.json", {"mcpServers": {
        "parallax": {"env": {"ANTHROPIC_API_KEY": "px-key"}},
        "mcp-reasoning": {"env": {"ANTHROPIC_API_KEY": "mr-key"}},
        "other": {"env": {"ANTHROPIC_API_KEY": "never-this"}},
    }})
    monkeypatch.delenv("DEVHARNESS_MCP_CONFIG", raising=False)
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))
    assert overage_api_key() == "mr-key"


def test_overage_key_absent_is_none_never_raises(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()  # no .claude.json at all
    monkeypatch.delenv("DEVHARNESS_MCP_CONFIG", raising=False)
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))
    assert overage_api_key() is None


def test_overage_key_malformed_override_degrades_with_stderr(tmp_path, monkeypatch, capsys):
    # a raise here would replace the credit-exhaustion error mid-retry with a new crash mode
    home = tmp_path / "home"
    home.mkdir()  # hermetic: no real home file behind the fallback
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    monkeypatch.setenv("DEVHARNESS_MCP_CONFIG", str(bad))
    assert overage_api_key() is None
    assert "overage key source unreadable" in capsys.readouterr().err


def test_overage_key_keyless_override_falls_back_to_home(tmp_path, monkeypatch):
    # review catch: the override wires launch specs; a readable-yet-keyless override (a substitute-
    # server file without env keys) must NOT silently disable the rev-0.4.0 auth-fallback the
    # operator still has configured in the home file
    home = tmp_path / "home"
    home.mkdir()
    _write(home / ".claude.json", {"mcpServers": {"mcp-reasoning": {"env": {"ANTHROPIC_API_KEY": "home-key"}}}})
    override = _write(tmp_path / "local.json", {"mcpServers": {"parallax": {"command": "px"}}})
    monkeypatch.setenv("DEVHARNESS_MCP_CONFIG", str(override))
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))
    assert overage_api_key() == "home-key"


def test_overage_key_malformed_home_degrades_with_stderr(tmp_path, monkeypatch, capsys):
    # review catch: the home file is rewritten frequently by the Claude Code CLI (a torn read is
    # realistic) — a silently-disabled fallback must be visible, not just for override sources
    home = tmp_path / "home"
    home.mkdir()
    (home / ".claude.json").write_text("{not json", encoding="utf-8")
    monkeypatch.delenv("DEVHARNESS_MCP_CONFIG", raising=False)
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))
    assert overage_api_key() is None
    assert "overage key source unreadable" in capsys.readouterr().err


def test_single_source_parity_guard():
    """No site outside mcp/config.py re-hardcodes the home-file read (the scratch_commit_subject
    source-reading convention). Matches CODE patterns — any home-dir spelling on a line that also
    names the file — not the bare string: '.claude.json' legitimately appears in docstrings and
    comments that stay."""
    import re

    repo = Path(__file__).resolve().parents[2]
    # any spelling of a home-dir resolution co-occurring with the filename on one code line
    pat = re.compile(r"(Path\.home\s*\(\)|expanduser|USERPROFILE|HOME\b).*\.claude\.json"
                     r"|\.claude\.json.*(Path\.home\s*\(\)|expanduser|USERPROFILE)")
    offenders = []
    for base in (repo / "runtime" / "devharness", repo / "scripts"):
        for py in base.rglob("*.py"):
            if py.name == "config.py" and py.parent.name == "mcp":
                continue
            for i, line in enumerate(py.read_text(encoding="utf-8").splitlines(), 1):
                if pat.search(line) and not line.strip().startswith("#") and '"""' not in line:
                    offenders.append(f"{py.relative_to(repo)}:{i}")
    assert offenders == [], f"hand-rolled ~/.claude.json reads outside mcp/config.py: {offenders}"
