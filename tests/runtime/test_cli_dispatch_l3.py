"""#L3: `python -m devharness <subcommand>` dispatches to the cli.<subcommand> modules.

The docstrings reference a `devharness <subcmd>` UX that did not exist — only `python -m
devharness.cli.<subcmd>`. __main__.main routes a subcommand to its module's main(argv).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.__main__ import main


def test_no_args_prints_usage_and_returns_2():
    assert main([]) == 2


def test_help_returns_0():
    assert main(["--help"]) == 0


def test_unknown_subcommand_returns_2():
    assert main(["bogus-subcommand"]) == 2


def test_dispatches_to_the_subcommand_main(monkeypatch):
    import devharness.cli.answer as answer_mod
    seen = {}

    def _rec(argv):
        seen["argv"] = argv
        return 0

    monkeypatch.setattr(answer_mod, "main", _rec)
    assert main(["answer", "q0", "hello"]) == 0
    assert seen["argv"] == ["q0", "hello"]  # the subcommand's args are forwarded verbatim
