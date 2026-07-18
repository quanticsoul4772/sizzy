"""package.json dependency parser. Read-only."""

import json


def parse(path: str) -> list[str]:
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    names = list(data.get("dependencies", {}).keys())
    names += list(data.get("devDependencies", {}).keys())
    return names
