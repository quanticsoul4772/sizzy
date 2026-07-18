"""The panel server: a ``ThreadingHTTPServer`` + the per-session ``Panel`` container.

``Panel`` bundles the one writer (:class:`PanelWriter`), the target/project state
(:class:`PanelSession`), and the single build slot (:class:`BuildRunner`) for one active event store,
and owns store switching (rebuild the writer for a new store — refused mid-build). The server binds
loopback by default (``DEVHARNESS_PANEL_ADDR``); it has NO auth of its own — a write surface must sit
behind Caddy basic-auth + TLS in production (see ``deploy/vps``). Rev 0.4.15: every request passes a
Host/Origin gate (``PanelHandler._gate_refusal`` — loopback or ``DEVHARNESS_PANEL_PUBLIC_HOST``),
closing drive-by CSRF and DNS rebinding; a proxied deploy must set that env to its public domain.
"""

import os
import sqlite3
from http.server import ThreadingHTTPServer
from pathlib import Path

from devharness.migrate import is_event_store
from devharness.panel import state as pstate
from devharness.panel.routes import PanelHandler
from devharness.panel.session import PanelSession
from devharness.panel.worker import BuildRunner
from devharness.panel.writer import PanelWriter

DEFAULT_DB = "var/devharness.db"
DEFAULT_ADDR = "127.0.0.1:8090"


def _store_activity_millis(p: Path) -> int:
    """Ranking key for a store: when real work last happened in it.

    Event-derived (`pstate.last_activity_millis` over a mode=ro connection — never migrates or
    locks a sibling, the `discover_projects` pattern); file mtime only as fallback for an empty or
    unreadable store. mtime alone is WRONG here: opening/closing a WAL store checkpoints and bumps
    it with zero events written — the panel itself laundered the stale legacy store's age that way
    minutes after the mtime heuristic shipped (rev 0.4.5). Returns 0 when nothing is knowable."""
    act = None
    try:
        conn = sqlite3.connect(p.resolve().as_uri() + "?mode=ro", uri=True)
        try:
            act = pstate.last_activity_millis(conn)
        finally:
            conn.close()
    except sqlite3.Error:
        act = None
    if act:
        return act
    try:
        return int(p.stat().st_mtime * 1000)
    except OSError:
        return 0


def _default_db(root: Path | None = None) -> str:
    """No explicit store named: the store where real work most recently HAPPENED under the REPO's
    ``var/`` — never blindly the legacy fixed name. The old fixed default silently opened the
    June-era multi-project store and greeted the operator with a dead plan's red warning (the
    2026-07-14 defect). Anchored to the repo root like ``cli/_bus.py``, not the CWD — a
    CWD-relative scan would adopt any foreign ``var/*.db`` the panel happens to be launched beside
    (the same silent-wrong-store class). Ranked by last EVENT activity, not file mtime (see
    ``_store_activity_millis``). Falls back to the fixed name under the same root when it holds no
    store at all (first run — created loud, as before)."""
    root = root if root is not None else Path(__file__).resolve().parents[3] / "var"
    # rev 0.4.13: a foreign sqlite file (the parallax/reasoning MCP databases live in the same
    # var/ on the VPS) is never a candidate — its constantly-fresh mtime won the fallback ranking
    # and the notice named parallax.db live. True and None (transiently unreadable REAL store)
    # still rank; only positive not-a-store evidence excludes.
    candidates = [(m, str(p)) for p in root.glob("*.db")
                  if is_event_store(p) is not False and (m := _store_activity_millis(p)) > 0]
    if not candidates:
        return str(root / Path(DEFAULT_DB).name)
    return max(candidates)[1]


def _startup_notice(db_path: str, *, from_env: bool) -> str | None:
    """A visible warning when DEVHARNESS_DB picked a store that is NOT the most recently active one.

    The env override is deliberate (the VPS pins its store with it) — but a LEFTOVER variable in a
    long-lived terminal silently reopens an old store while the operator's real work sits in a
    fresher one (live-hit 2026-07-14, minutes after the rev-0.4.4 default fix: the fix worked, the
    stale shell env overrode it). The operator can't distinguish 'deliberately chosen' from
    'forgotten leftover' unless the panel says so. Returns None when the env store IS the freshest
    (the VPS single-store case stays quiet)."""
    if not from_env:
        return None
    freshest = _default_db()
    chosen, best = Path(db_path).resolve(), Path(freshest).resolve()
    if chosen == best or _store_activity_millis(best) <= _store_activity_millis(chosen):
        return None
    return (f"⚠ store came from DEVHARNESS_DB ({Path(db_path).name}) but {best.name} has newer "
            f"activity — leftover env var? Switch in the Project card, or unset DEVHARNESS_DB")


def _resolve_db(db_path: str) -> tuple[str, bool]:
    """Store-path hygiene, mirroring ``ConsoleApp.connect`` (rev 0.3.63): resolve to absolute, fail
    closed on a missing parent dir, and report whether the file is being created new."""
    if db_path == ":memory:":
        return db_path, False
    resolved = Path(db_path).resolve()
    if not resolved.parent.is_dir():
        raise FileNotFoundError(
            f"event-store directory does not exist: {resolved.parent} "
            f"(resolved from {db_path}) — set DEVHARNESS_DB to an absolute path")
    # rev 0.4.13: content gate, not just path hygiene — every open runs migrate(), so adopting
    # an EXISTING file that is not a devharness store writes devharness schema into a foreign
    # database (live: parallax.db, the MCP server's own db in var/). FileNotFoundError on
    # purpose: Panel.switch and console __main__._status already catch exactly it.
    if resolved.exists():
        verdict = is_event_store(resolved)
        if verdict is False:
            raise FileNotFoundError(
                f"{resolved} exists but is not a devharness event store — refusing to migrate "
                "a foreign database (delete or rename the file if it should be a new store)")
        if verdict is None:
            raise FileNotFoundError(
                f"{resolved} exists but is unreadable right now — refusing to open a store "
                "that cannot even be probed (locked by another process?)")
    return str(resolved), not resolved.exists()


class Panel:
    """The active event store's writer + session + build slot; switchable to another store."""

    def __init__(self, db_path: str) -> None:
        self.db_path, self.store_created = _resolve_db(db_path)
        self.writer = PanelWriter(self.db_path)
        self.session = PanelSession(self.db_path)
        self.runner = BuildRunner(self.db_path, self.writer)
        self.messages: list[str] = []
        self.notice: str | None = None  # startup warning surfaced in /state (UI banner)
        if self.store_created:
            self.messages.append(f"⚠ created NEW EMPTY event store at {self.db_path}")
        self._restore_target()

    def _restore_target(self) -> None:
        conn = sqlite3.connect(self.db_path)
        try:
            self.messages += self.session.restore_target(conn)
        finally:
            conn.close()

    def switch(self, db_path: str) -> dict:
        """Reconnect to a different store — refused mid-build (a running worker reads ``db_path`` live)."""
        if self.runner.busy_label is not None:
            return {"ok": False, "error": f"can't switch while {self.runner.busy_label} is running"}
        if not db_path:
            return {"ok": False, "error": "db_path is required"}
        try:
            resolved, created = _resolve_db(db_path)
        except FileNotFoundError as exc:
            return {"ok": False, "error": str(exc)}
        old = self.writer
        self.db_path, self.store_created = resolved, created
        self.notice = None  # the operator acted on (or moved past) the startup warning
        self.writer = PanelWriter(self.db_path)
        self.session = PanelSession(self.db_path)
        self.runner = BuildRunner(self.db_path, self.writer)
        try:
            old.close()
        except Exception:
            pass
        msgs = []
        if created:
            msgs.append(f"⚠ created NEW EMPTY event store at {self.db_path}")
        self._restore_target()
        msgs += self.messages
        self.messages = []
        return {"ok": True, "db_path": self.db_path, "name": Path(self.db_path).stem, "messages": msgs}

    def new_project(self, name: str, repo: str, test_command: str = "") -> dict:
        """Create ``<name>.db`` beside the current store, switch to it, and set its target to ``repo``.
        (Research on the seed is started separately by the route.)

        ``test_command`` defaults to ``python -m pytest -q`` only when left blank — the hardcoded
        pytest default cost a rejected first task on the first non-Python panel project (a Node project:
        the verifier ran pytest against a Node repo, "no tests ran", exit 5 → rejected; rev 0.4.7)."""
        name, repo = name.strip(), repo.strip()
        if not name or not repo:
            return {"ok": False, "error": "name and repo are required"}
        cmd = (test_command or "").strip() or "python -m pytest -q"
        store = str(Path(self.db_path).parent / f"{name}.db")
        sw = self.switch(store)
        if not sw.get("ok"):
            return sw
        tgt = self.session.set_target(f"{repo} | {cmd}", self.writer)
        return {"ok": tgt.get("ok", False), "db_path": self.db_path, "name": name,
                "messages": sw.get("messages", []) + tgt.get("messages", []),
                "target_path": self.session.target_path}


class PanelServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, addr, panel: Panel) -> None:
        super().__init__(addr, PanelHandler)
        self.panel = panel


def _resolve_auth() -> None:
    """Auth for the SDK's ``claude`` subprocess. Three modes, in precedence order:

    - **systemd credential (the VPS):** ``LoadCredentialEncrypted=anthropic-key`` lands the decrypted
      key under ``$CREDENTIALS_DIRECTORY``; bridge it (and ``voyage-key``) into the process env — a
      headless box has no interactive ``claude`` login, so API-key auth is the only option there.
    - **explicit API-key opt-in (``DEVHARNESS_PANEL_APIKEY=1``):** keep whatever ``ANTHROPIC_API_KEY``
      the environment carries (a headless local deploy without systemd).
    - **otherwise (the operator's interactive box — the DEFAULT):** CLEAR a stray ``ANTHROPIC_API_KEY``
      so the ``claude`` CLI uses the logged-in subscription — matching the TUI + all seven ``run_*``
      drivers. This was previously opt-IN via ``DEVHARNESS_PANEL_SUBSCRIPTION=1``, so a fresh shell
      inheriting the machine-level stray key made research die with a bare ``exit code 1``
      (live-hit on a Node project drive, 2026-07-14); the repo's convention is clear-stray-keys, and
      the panel deviating from it was the defect. ``DEVHARNESS_PANEL_SUBSCRIPTION=1`` remains
      accepted (now redundant — it is the default).

    NOTE: the parallax + mcp-reasoning MCP servers always need a valid raw ``ANTHROPIC_API_KEY`` (they
    call the Anthropic API directly); they read it from ``~/.claude.json``'s per-server ``env``
    regardless of this — so a valid API key is required even in subscription mode. The rev-0.4.0
    overage fallback likewise injects its key per-call via ``options.env``, unaffected by this clear.
    """
    creds = os.environ.get("CREDENTIALS_DIRECTORY")
    bridged = False
    if creds:
        for fname, var in (("anthropic-key", "ANTHROPIC_API_KEY"), ("voyage-key", "VOYAGE_API_KEY")):
            p = Path(creds) / fname
            if p.is_file():
                os.environ[var] = p.read_text().strip()
                bridged = bridged or var == "ANTHROPIC_API_KEY"
    if not bridged and os.environ.get("DEVHARNESS_PANEL_APIKEY") != "1":
        os.environ.pop("ANTHROPIC_API_KEY", None)


def serve(db_path: str | None = None, addr: str | None = None) -> None:
    _resolve_auth()
    env_db = os.environ.get("DEVHARNESS_DB")
    from_env = not db_path and bool(env_db)
    db_path = db_path or env_db or _default_db()
    host, _, port = (addr or os.environ.get("DEVHARNESS_PANEL_ADDR", DEFAULT_ADDR)).partition(":")
    # Measure the notice BEFORE Panel() opens the store — the writer's own open (WAL + migrate)
    # can freshen an mtime-fallback store and wrongly suppress the warning (review catch F2).
    notice = _startup_notice(db_path, from_env=from_env)
    panel = Panel(db_path)
    panel.notice = notice
    server = PanelServer((host, int(port)), panel)
    if panel.notice:
        print(panel.notice)
    for m in panel.messages:
        print(m)
    print(f"devharness panel on http://{host}:{port}  (db={panel.db_path})")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        panel.writer.close()
