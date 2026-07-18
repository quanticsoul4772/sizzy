"""B4.2: secret_guard — detects secret patterns in the diff; evidence omits the matched text."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.gates.base import GateDeny, GateOk
from devharness.gates.secret_guard import SecretGuard

AWS = "AKIA" + "ABCDEFGHIJKLMNOP"
GH = "ghp_" + "a" * 36
OPENAI = "sk-" + "B" * 40
PEM = "-----BEGIN RSA PRIVATE KEY-----"
ENTROPY = "Zm9vYmFyYmF6cXV4MTIzNDU2Nzg5MEFCQ0RFRg"  # 38-char high-entropy base64


def _deny(diff):
    return SecretGuard().check({"diff_content": diff})


def test_each_pattern_detected():
    for secret, name in ((AWS, "aws_access_key"), (GH, "github_token"), (OPENAI, "openai_key"), (PEM, "private_key_header")):
        r = _deny(f"+config = {secret}")
        assert isinstance(r, GateDeny)
        assert name in r.evidence["matched_patterns"]


def test_high_entropy_detected():
    r = _deny(f"+key = {ENTROPY}")
    assert isinstance(r, GateDeny) and "high_entropy_string" in r.evidence["matched_patterns"]


def test_matched_text_not_in_evidence():
    r = _deny(f"+token = {GH}")
    assert isinstance(r, GateDeny)
    # the secret itself must never appear in the evidence (no leak into the event log)
    assert GH not in str(r.evidence)
    assert r.evidence["matched_patterns"] == ["github_token"] and r.evidence["matched_line_count"] == 1


def test_multiple_patterns_aggregate():
    r = _deny(f"+a = {AWS}\n+b = {GH}")
    assert isinstance(r, GateDeny)
    assert {"aws_access_key", "github_token"} <= set(r.evidence["matched_patterns"])
    assert r.evidence["matched_line_count"] == 2


def test_clean_diff_passes():
    assert isinstance(SecretGuard().check({"diff_content": "+def foo():\n+    return 42"}), GateOk)
    assert isinstance(SecretGuard().check({"diff_content": ""}), GateOk)


def test_content_override_allows():
    # the content axis is overridden via secret_guard_content_override (B4.2-reconciliation rename)
    r = SecretGuard().check({"diff_content": f"+token = {GH}", "secret_guard_content_override": True})
    assert isinstance(r, GateOk) and r.reason == "secret_detected_with_override"


def test_content_deny_reason_names_axis():
    r = _deny(f"+token = {GH}")
    assert isinstance(r, GateDeny) and r.evidence["axes_triggered"] == ["content"]


def _fake_jwt():
    # Build a JWT-shaped FIXTURE at runtime from plaintext, so no scannable token literal sits in the source
    # (a literal eyJ… trips secret scanners). This is a fake — base64url of trivial JSON, signature 'notreal'.
    import base64
    seg = lambda d: base64.urlsafe_b64encode(d).decode().rstrip("=")
    return f"{seg(b'{\"alg\":\"HS256\"}')}.{seg(b'{\"sub\":\"x\"}')}.{seg(b'notrealsignature')}"


def test_modern_token_shapes_detected():
    # F5: broadened patterns catch modern token shapes the old list missed
    cases = [
        ("gho_" + "a" * 36, "github_token"),
        ("github_pat_" + "A" * 60, "github_fine_grained_pat"),
        ("glpat-" + "x" * 20, "gitlab_pat"),
        ("xoxb-" + "1234567890abc", "slack_token"),
        ("AIza" + "B" * 35, "google_api_key"),
        (_fake_jwt(), "jwt"),
    ]
    for secret, name in cases:
        r = SecretGuard().check({"diff_content": f"+config = {secret}"})
        assert isinstance(r, GateDeny), f"{name} not denied"
        assert name in r.evidence["matched_patterns"], f"{name} not in {r.evidence['matched_patterns']}"


def test_url_safe_token_caught_by_entropy_axis():
    # a URL-safe-base64 token (contains - and _) used to split into sub-32 runs and evade the entropy axis
    tok = "AbCd-EfGh_IjKl-MnOp_QrSt-UvWx_YzAb-Cd12"  # 39 chars with - and _
    r = SecretGuard().check({"diff_content": f"+secret = {tok}"})
    assert isinstance(r, GateDeny)
