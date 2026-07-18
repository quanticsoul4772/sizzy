"""go.mod dependency parser (require directives). Read-only."""

import re

_REQUIRE_LINE = re.compile(r"([^\s]+)\s+v[0-9]")


def parse(path: str) -> list[str]:
    names: list[str] = []
    in_block = False
    with open(path, encoding="utf-8") as handle:
        for raw in handle:
            line = raw.strip()
            if line.startswith("require ("):
                in_block = True
                continue
            if in_block:
                if line == ")":
                    in_block = False
                    continue
                match = _REQUIRE_LINE.match(line)
                if match:
                    names.append(match.group(1))
            elif line.startswith("require "):
                match = _REQUIRE_LINE.match(line[len("require "):])
                if match:
                    names.append(match.group(1))
    return names
