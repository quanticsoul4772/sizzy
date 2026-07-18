"""Report assembly: turn a list of violations into the JSON report shape."""

from specledger.model import Violation


def build_report(violations: list[Violation]) -> dict:
    """Build the report object: ``{ok, violations:[{check, severity, detail}]}``.

    ``ok`` is True iff there are no violations.
    """
    return {
        "ok": len(violations) == 0,
        "violations": [v.as_dict() for v in violations],
    }
