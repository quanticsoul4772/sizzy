"""``python -m devharness.console`` — the operator console.

**Bare invocation** launches the interactive **TUI** (``console/tui.py``) — a live
loop-state panel plus keybindings that drive the immediate operator decisions. It
degrades to the read-only snapshot when a TUI can't run: a non-TTY context (CI /
piped output) or ``textual`` not installed.

``python -m devharness.console status [--follow]`` is the read-only **snapshot**:
connects to the runtime (``DEVHARNESS_DB``, default ``var/devharness.db``), prints
the current loop state, and exits — or, with ``--follow``, consumes the sidecar's
live SSE feed (the same surface the dashboard reads) and re-renders per event. No
writes on either path.
"""

import sys

from devharness.console.app import ConsoleApp


def _status(argv) -> int:
    """The read-only snapshot: render once, or follow the SSE stream with ``--follow``."""
    try:
        app = ConsoleApp().connect()
    except FileNotFoundError as exc:
        # A bad DEVHARNESS_DB fails closed with the resolved path named (rev 0.3.63).
        sys.stderr.write(f"{exc}\n")
        return 1
    if app.store_created:
        sys.stderr.write(f"note: created NEW EMPTY event store at {app.db_path}\n")
    sys.stdout.write(app.render() + "\n")
    if "--follow" in argv:
        app.follow(on_frame=lambda _frame, _state: sys.stdout.write(app.render() + "\n"))
    return 0


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "status":
        return _status(argv[1:])
    # bare invocation -> the interactive TUI, degrading to the snapshot where it can't run.
    if not sys.stdout.isatty():
        return _status(argv)  # CI / piped / non-TTY: keep the documented snapshot behavior
    try:
        from devharness.console.tui import run as run_tui
    except ImportError:
        sys.stderr.write(
            "textual is not installed; showing the read-only snapshot. "
            "Install the TUI with:  pip install 'devharness-runtime[tui]'\n"
        )
        return _status(argv)
    return run_tui()


if __name__ == "__main__":
    raise SystemExit(main())
