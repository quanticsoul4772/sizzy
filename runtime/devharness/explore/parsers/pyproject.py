"""pyproject.toml dependency parser (PEP 621 + poetry). Read-only."""

import re
import tomllib

_SPLIT = re.compile(r"[<>=!~\[\s;@]")


def _name(spec: str) -> str:
    return _SPLIT.split(spec.strip(), 1)[0]


def parse(path: str) -> list[str]:
    with open(path, "rb") as handle:
        data = tomllib.load(handle)
    names: list[str] = []
    project = data.get("project", {})
    for dep in project.get("dependencies", []):
        names.append(_name(dep))
    for group in project.get("optional-dependencies", {}).values():
        for dep in group:
            names.append(_name(dep))
    poetry = data.get("tool", {}).get("poetry", {})
    for name in poetry.get("dependencies", {}):
        if name.lower() != "python":
            names.append(name)
    seen, out = set(), []
    for name in names:
        if name and name not in seen:
            seen.add(name)
            out.append(name)
    return out
