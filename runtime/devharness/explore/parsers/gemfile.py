"""Gemfile dependency parser. Read-only."""

import re

_GEM = re.compile(r"""\s*gem\s+["']([^"']+)["']""")


def parse(path: str) -> list[str]:
    names: list[str] = []
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            match = _GEM.match(line)
            if match:
                names.append(match.group(1))
    return names
