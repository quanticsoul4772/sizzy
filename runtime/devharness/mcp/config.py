"""MCP launch-spec configuration source (rev 0.4.25).

The parallax / mcp-reasoning launch specs are operator-local and machine-specific — never embedded
in the repo. Historically nine call sites each hand-rolled the same ``~/.claude.json`` read; this
module is the single source (a parity-guard test bans re-hardcoding it), and adds
``DEVHARNESS_MCP_CONFIG``: point it at any JSON file with a top-level ``mcpServers`` block to wire
servers per-repo/per-shell without touching the home file (the local-machine alternative to the VPS
bootstrap, which writes the home file — see docs/local-mcp-setup.md). An explicitly-set override is
never silently ignored: a missing/invalid file or absent server under the override FAILS CLOSED
(the rev-0.3.63 store-path-hygiene philosophy); the unset default reads ``~/.claude.json`` exactly
as before.

The error taxonomy is load-bearing (the diff's review): callers with SOFT contracts (run_promote —
absent config means "run without parallax", not "crash") must distinguish *unconfigured* from
*broken* without re-deriving the override state, so the subclasses below carry it. Every subclass
IS a RuntimeError — the console's advisory catches rely on that.
"""

import json
import os
import sys
from pathlib import Path

_ENV = "DEVHARNESS_MCP_CONFIG"
_HINT = f" (or set {_ENV} to point at a different mcpServers file)"


class MCPConfigError(RuntimeError):
    """Base: a named MCP server's launch spec could not be resolved (message names the source)."""

    is_override = False  # whether an explicit DEVHARNESS_MCP_CONFIG selected the failing source


class MCPConfigFileMissing(MCPConfigError):
    """The config file itself does not exist."""


class MCPConfigFileInvalid(MCPConfigError):
    """The config file exists but is unreadable / not JSON / not the mcpServers object shape."""


class MCPServerNotConfigured(MCPConfigError):
    """The file is fine; the named server just is not in it (the 'unconfigured' state)."""


def _err(cls, message: str, is_override: bool) -> MCPConfigError:
    exc = cls(message)
    exc.is_override = is_override
    return exc


def _config_path() -> tuple[Path, bool]:
    """(path, is_override) — the file to read, and whether an explicit override selected it."""
    override = os.environ.get(_ENV)
    if override:
        return Path(override), True
    return Path.home() / ".claude.json", False


def _load_servers(path: Path, is_override: bool, name: str) -> dict:
    if not path.exists():
        src = f"{_ENV}={path}" if is_override else f"{path}{_HINT}"
        raise _err(MCPConfigFileMissing,
                   f"no {path} — cannot find the {name} MCP server launch spec ({src})", is_override)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        raise _err(MCPConfigFileInvalid, f"cannot read {path}: {exc}", is_override) from exc
    # shape-validate rather than .get() blindly (review catch: a list/string top level, or a
    # non-object mcpServers value, raised AttributeError PAST every MCPConfigError catch —
    # including out of overage_api_key's never-raise contract, mid-quota-retry)
    servers = data.get("mcpServers", {}) if isinstance(data, dict) else None
    if not isinstance(servers, dict):
        raise _err(MCPConfigFileInvalid,
                   f"{path} is not an mcpServers config (expected a JSON object with an "
                   f"'mcpServers' object)", is_override)
    return servers


def server_cfg(name: str) -> dict:
    """The bare launch-spec dict for ``name``.

    Call sites keep their own wrapping (``{name: cfg}`` where a client wants the mapping form) —
    the historical readers returned different shapes, and unifying blindly would double-wrap.
    """
    path, is_override = _config_path()
    servers = _load_servers(path, is_override, name)
    server = servers.get(name)
    if not server:
        hint = "" if is_override else _HINT
        raise _err(MCPServerNotConfigured,
                   f"{name} not found under mcpServers in {path}{hint}", is_override)
    if not isinstance(server, dict):
        raise _err(MCPConfigFileInvalid,
                   f"mcpServers[{name!r}] in {path} is not an object", is_override)
    return server


def overage_api_key() -> str | None:
    """The rev-0.4.0 overage key, semantics preserved exactly: a **top-level** lookup of exactly
    ``("mcp-reasoning", "parallax")`` in that order — deliberately NOT a scan of all servers (the
    home file also holds duplicate blocks under ``projects.<path>.mcpServers`` with DIFFERENT keys;
    the top-level block is the one the harness launches from, so it is the deterministic source).

    Source order (review catch): the override file is consulted first, but a readable-yet-keyless
    override FALLS BACK to ``~/.claude.json`` — the override wires launch specs, while the home
    file is the key's historical rev-0.4.0 source, and a substitute-server file without keys must
    not silently disable the auth-fallback the operator still has configured at home.

    Never raises: file ABSENCE is the quiet ``None`` it always was; an unreadable/invalid source
    (override or home — the home file is rewritten frequently by the Claude Code CLI, so a torn
    read is realistic) degrades with one stderr line so a silently-disabled fallback is visible.
    ``run_query`` calls this mid-retry inside every SDK loop; a raise here would replace the
    credit-exhaustion error the operator needs to see with a new crash mode.
    """
    sources: list[tuple[Path, bool]] = []
    override = os.environ.get(_ENV)
    if override:
        sources.append((Path(override), True))
    sources.append((Path.home() / ".claude.json", False))
    for path, is_override in sources:
        try:
            servers = _load_servers(path, is_override, "overage-key")
        except MCPConfigFileMissing:
            continue  # absence stays the quiet None (rev-0.4.0 behavior)
        except MCPConfigError as exc:
            sys.stderr.write(f"⚠ overage key source unreadable, continuing without: {exc}\n")
            continue
        for name in ("mcp-reasoning", "parallax"):
            server = servers.get(name)
            env = server.get("env") if isinstance(server, dict) else None
            key = (env or {}).get("ANTHROPIC_API_KEY") if isinstance(env, dict) else None
            if key:
                return key
    return None
