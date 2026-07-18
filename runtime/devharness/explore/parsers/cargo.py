"""Cargo.toml dependency parser. Read-only."""

import tomllib


def parse(path: str) -> list[str]:
    with open(path, "rb") as handle:
        data = tomllib.load(handle)
    names = list(data.get("dependencies", {}).keys())
    names += list(data.get("dev-dependencies", {}).keys())
    return names
