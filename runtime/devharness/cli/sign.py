"""`devharness sign <spec_id>` (B1.3) — the operator sign-off action.

Emits spec_signed with the operator identity (DEVHARNESS_OPERATOR, falling back to
`git config user.name`), sets signed=1 on the artifact, and refuses an unknown
spec_id. The drafted-spec dashboard tile (B1.6) surfaces a "ready to sign"
indicator naming this command.
"""

import os
import subprocess
import time

import msgspec

from devharness.events.registry import SpecSigned

USAGE = (
    "usage: devharness sign <spec_id>\n"
    "  Signs an operator-reviewed spec artifact (sets signed=1, emits spec_signed).\n"
    "  Operator identity: DEVHARNESS_OPERATOR env, else `git config user.name`.\n"
    "  Discoverability: the drafted-spec dashboard tile (B1.6) shows a 'ready to sign'\n"
    "  indicator naming this command.\n"
)


class UnknownSpec(RuntimeError):
    """Raised when signing a spec_id with no matching artifact."""


def operator_identity() -> str:
    operator = os.environ.get("DEVHARNESS_OPERATOR")
    if operator:
        return operator
    try:
        name = subprocess.check_output(["git", "config", "user.name"], text=True).strip()
    except Exception:
        name = ""
    return name or "unknown"


def _correlation_for_spec(conn, spec_id):
    row = conn.execute(
        "SELECT correlation_id FROM artifacts WHERE artifact_id = ? AND artifact_type = 'spec'",
        (spec_id,),
    ).fetchone()
    return row[0] if row else None


def sign_spec(conn, event_bus, spec_id, *, operator=None, now_millis=None) -> str:
    """Sign a spec artifact: set signed=1, emit spec_signed; raise UnknownSpec otherwise."""
    correlation_id = _correlation_for_spec(conn, spec_id)
    if correlation_id is None:
        raise UnknownSpec(f"no spec artifact with id {spec_id!r}")
    signer = operator or operator_identity()
    signed_at = (now_millis or (lambda: int(time.time() * 1000)))()
    conn.execute("UPDATE artifacts SET signed = 1 WHERE artifact_id = ?", (spec_id,))
    conn.commit()
    payload = msgspec.to_builtins(SpecSigned(spec_id=spec_id, signer=signer, signed_at_millis=signed_at))
    event_bus.emit_sync("spec_signed", payload, correlation_id=correlation_id)
    return spec_id


def main(argv=None) -> int:
    import sys

    from devharness.cli._bus import open_store, projected_bus

    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) != 1:
        sys.stderr.write(USAGE)
        return 2
    spec_id = argv[0]
    conn = open_store()
    try:
        sign_spec(conn, projected_bus(conn), spec_id)
    except UnknownSpec as exc:
        sys.stderr.write(f"refused: {exc}\n")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
