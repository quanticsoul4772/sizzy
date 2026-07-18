"""requirements.txt dependency parser. Read-only."""

import re

_SPLIT = re.compile(r"[<>=!~\[\s;@]")


def parse(path: str) -> list[str]:
    names: list[str] = []
    with open(path, encoding="utf-8") as handle:
        for raw in handle:
            line = raw.strip()
            if not line or line.startswith("#") or line.startswith("-"):
                continue
            name = _SPLIT.split(line, 1)[0]
            if name:
                names.append(name)
    return names
