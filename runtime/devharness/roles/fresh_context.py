"""Fresh-context spawn discipline (B2.5).

A role that must evaluate independently (the reviewer) runs in a fresh context: the
SDK worker is spawned with zero inherited history — no prior session_id, no prepended
messages — and ``setting_sources=[]``. ``require_fresh_context`` enforces it.
"""


class FreshContextRequired(RuntimeError):
    """Raised when a fresh-context role is spawned without fresh_context=True."""


def require_fresh_context(fresh_context: bool, role_name: str = "role") -> None:
    if not fresh_context:
        raise FreshContextRequired(
            f"{role_name} must spawn with fresh_context=True (zero inherited history)"
        )
