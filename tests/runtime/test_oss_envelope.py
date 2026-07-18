"""B4.0: OssEnvelope is a frozen kw-only struct; the four fields are required + typed."""

import sys
from pathlib import Path

import msgspec
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.artifacts.plan import OssEnvelope


def test_construct_and_fields():
    env = OssEnvelope(upstream_repo="octo/widget", license_spdx="Apache-2.0", requester_id="r1", target_branch="dev")
    assert env.upstream_repo == "octo/widget" and env.license_spdx == "Apache-2.0"
    assert env.requester_id == "r1" and env.target_branch == "dev"


def test_frozen():
    env = OssEnvelope(upstream_repo="a", license_spdx="MIT", requester_id="r", target_branch="main")
    with pytest.raises(AttributeError):
        env.upstream_repo = "b"


def test_missing_field_rejected():
    with pytest.raises(TypeError):
        OssEnvelope(upstream_repo="a", license_spdx="MIT", requester_id="r")  # target_branch missing


def test_msgspec_roundtrip_and_type_validation():
    env = OssEnvelope(upstream_repo="a", license_spdx="MIT", requester_id="r", target_branch="main")
    builtins = msgspec.to_builtins(env)
    assert msgspec.convert(builtins, OssEnvelope) == env
    with pytest.raises(msgspec.ValidationError):
        msgspec.convert({"upstream_repo": 5, "license_spdx": "MIT", "requester_id": "r", "target_branch": "main"}, OssEnvelope)
