"""Build-step runner — the web analog of the TUI's thread workers + ``_busy`` single-flight guard.

The long LLM steps (research / director plan / developer dispatch / certify / OSS) take minutes and
must not block the HTTP server, and — exactly like the TUI (``console/tui.py`` ``_begin``) — only ONE
may run at a time (the developer takes the single write lock; two in flight would contend for it and
the worktrees). The TUI's guard is a per-instance flag on the UI thread; the panel's is a process-wide
guard here, since HTTP handlers have no shared UI thread.

A step runs on a daemon thread with its OWN read connection (never the writer's connection); it emits
through the shared :class:`~devharness.panel.writer.PanelWriter` (serialized). Progress reaches the
browser via those emits flowing out over the sidecar SSE, plus a job record polled at ``/job/{id}``.
Cancellation is cooperative/best-effort (an in-flight SDK run can't be force-killed, only abandoned —
the TUI's ``ctrl+x`` contract): the step closure is handed a ``threading.Event`` it checks at its poll
points (research's answer loop honours it; plan/dispatch check it where they can).
"""

import sqlite3
import threading


class BusyError(RuntimeError):
    """Raised by ``submit`` when a build step is already running (single-flight)."""


class BuildRunner:
    """Owns the single build slot + the job registry for one panel session."""

    def __init__(self, db_path: str, writer) -> None:
        self._db_path = db_path
        self._writer = writer
        self._guard = threading.Lock()
        self._busy_label: str | None = None
        self._busy_job: str | None = None
        self._seq = 0
        self._jobs: dict[str, dict] = {}
        self._cancels: dict[str, threading.Event] = {}

    @property
    def busy_label(self) -> str | None:
        return self._busy_label

    @property
    def busy_job(self) -> str | None:
        return self._busy_job

    def job(self, job_id: str) -> dict | None:
        return self._jobs.get(job_id)

    def jobs(self) -> list[dict]:
        """All jobs this session has run, in submission order — for the /diag bundle."""
        return list(self._jobs.values())

    def submit(self, label: str, target_fn) -> str:
        """Claim the single build slot and run ``target_fn(conn, bus, cancel_event)`` on a thread.

        Returns the job id. Raises :class:`BusyError` if a step is already running.
        """
        with self._guard:
            if self._busy_label is not None:
                raise BusyError(f"{self._busy_label} is running (only one build step at a time)")
            self._seq += 1
            job_id = f"job-{self._seq}"
            self._busy_label = label
            self._busy_job = job_id
        cancel = threading.Event()
        self._cancels[job_id] = cancel
        self._jobs[job_id] = {"id": job_id, "label": label, "status": "running",
                              "result": None, "error": None}
        threading.Thread(target=self._run, args=(job_id, label, target_fn, cancel),
                         daemon=True, name=f"panel-build-{job_id}").start()
        return job_id

    def _run(self, job_id, label, target_fn, cancel) -> None:
        conn = None
        job = self._jobs[job_id]
        try:
            conn = sqlite3.connect(self._db_path)
            conn.execute("PRAGMA busy_timeout=5000")
            result = target_fn(conn, self._writer, cancel)
            if cancel.is_set():
                job["status"] = "cancelled"
            else:
                job["status"] = "done"
                job["result"] = str(result)
        except _StepCancelled:
            job["status"] = "cancelled"
        except Exception as exc:  # noqa: BLE001 — surface, never crash the server
            job["status"] = "error"
            detail = f"{type(exc).__name__}: {exc}"
            # The SDK's ProcessError says "Check stderr output for details" — include that stderr
            # here or there is nowhere to check (live-hit: a bare 'exit code 1' research failure).
            stderr = getattr(exc, "stderr", None)
            if stderr:
                detail += f"\nstderr: {str(stderr).strip()[-2000:]}"
            job["error"] = detail
        finally:
            if conn is not None:
                conn.close()
            # Release the slot LAST — a stranded busy flag would block every future dispatch.
            with self._guard:
                self._busy_label = None
                self._busy_job = None
            self._cancels.pop(job_id, None)

    def cancel(self, job_id: str) -> bool:
        """Signal a running step to abandon (best-effort). True if it was running."""
        ev = self._cancels.get(job_id)
        if ev is None:
            return False
        ev.set()
        return True


class _StepCancelled(Exception):
    """Raised inside a step closure when it observes cancellation (abandon, don't error)."""
