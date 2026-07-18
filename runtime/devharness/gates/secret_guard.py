"""secret_guard gate (§S5 OSS fear-map; real body B4.2, defense-in-depth B4.2-reconciliation).

Two independent axes — a contributor must evade BOTH to slip a secret past:
  - PATH axis: refuses writes to secret-named files (.env, *.pem, id_rsa, credentials.*, ...).
  - CONTENT axis: scans the diff for secret-like patterns (API keys, private keys, high-entropy).
Either axis triggering denies the gate. Each axis has its own override (secret_guard_path_override /
secret_guard_content_override) so an operator can selectively allow one vector without disabling the
other; both override marks are audited via gate_fired. Evidence records matched PATTERN NAMES + paths
+ a line count — never the matched secret text (so the event log never carries the secret).
"""

import math
import os
import re
from fnmatch import fnmatch

from devharness.gates.base import Gate, GateDeny, GateOk
from devharness.gates.registry import register_gate

# --- PATH axis ---
DEFAULT_SECRET_PATH_PATTERNS = (
    ".env", ".env.*", "secrets.*", "*.pem", "*.key", "id_rsa", "id_dsa", "id_ecdsa", "id_ed25519",
    "*.p12", "*.pfx", "*.keystore", "credentials.*", ".npmrc", ".pypirc", "*.kdbx",
)


def secret_path_patterns() -> tuple:
    """The default secret-path globs plus any appended via DEVHARNESS_SECRET_PATH_PATTERNS."""
    extra = os.environ.get("DEVHARNESS_SECRET_PATH_PATTERNS", "")
    appended = tuple(part.strip() for part in extra.split(",") if part.strip())
    return DEFAULT_SECRET_PATH_PATTERNS + appended


def _matches_secret_path(path: str) -> bool:
    base = path.replace("\\", "/").split("/")[-1]
    return any(fnmatch(base, pat) for pat in secret_path_patterns())


# --- CONTENT axis ---
# Broadened for modern token shapes (audit F5): the old list missed gh[ousr]_ tokens, fine-grained PATs,
# GitLab/Slack/Google keys, and JWTs. The entropy backstop now includes the URL-safe base64 chars (-_) so a
# JWT / fine-grained PAT no longer splits into sub-32 runs that evade it.
SECRET_PATTERNS = [
    ("aws_access_key", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("github_token", re.compile(r"gh[poursa]_[0-9A-Za-z]{36,}")),       # ghp_/gho_/ghu_/ghs_/ghr_/gha_
    ("github_fine_grained_pat", re.compile(r"github_pat_[0-9A-Za-z_]{60,}")),
    ("gitlab_pat", re.compile(r"glpat-[0-9A-Za-z\-_]{20,}")),
    ("slack_token", re.compile(r"xox[baprs]-[0-9A-Za-z\-]{10,}")),
    ("google_api_key", re.compile(r"AIza[0-9A-Za-z\-_]{35}")),
    ("openai_key", re.compile(r"sk-[A-Za-z0-9\-_]{32,}")),
    ("jwt", re.compile(r"eyJ[A-Za-z0-9\-_]{8,}\.[A-Za-z0-9\-_]{8,}\.[A-Za-z0-9\-_]{8,}")),
    ("private_key_header", re.compile(r"-----BEGIN [A-Z ]+PRIVATE KEY-----")),
]
_HIGH_ENTROPY_RE = re.compile(r"[A-Za-z0-9+/=\-_]{32,}")
_ENTROPY_THRESHOLD = 4.0  # bits/char; random base64 ~6, English text ~3-4


def _shannon_entropy(s: str) -> float:
    if not s:
        return 0.0
    counts = {c: s.count(c) for c in set(s)}
    n = len(s)
    return -sum((c / n) * math.log2(c / n) for c in counts.values())


def _detect(line: str) -> set[str]:
    found = {name for name, rx in SECRET_PATTERNS if rx.search(line)}
    for run in _HIGH_ENTROPY_RE.findall(line):
        if _shannon_entropy(run) >= _ENTROPY_THRESHOLD:
            found.add("high_entropy_string")
            break
    return found


def _scan_content(diff: str):
    matched_patterns: set[str] = set()
    matched_lines = 0
    for line in (diff or "").splitlines():
        hits = _detect(line)
        if hits:
            matched_patterns |= hits
            matched_lines += 1
    return matched_patterns, matched_lines


class SecretGuard(Gate):
    name = "secret_guard"

    def check(self, context: dict):
        path_matches = [p for p in context.get("touched_paths", []) if _matches_secret_path(p)]
        matched_patterns, matched_lines = _scan_content(context.get("diff_content", "") or "")

        path_override = context.get("secret_guard_path_override") is True
        content_override = context.get("secret_guard_content_override") is True

        axes_triggered = []
        if path_matches and not path_override:
            axes_triggered.append("path")
        if matched_patterns and not content_override:
            axes_triggered.append("content")

        if axes_triggered:
            return GateDeny(
                reason=f"secret_detected: axes {','.join(axes_triggered)}",
                purpose="OSS contributions must never leak credentials/keys/secrets — by file name OR by content (§S5 secret_guard, defense in depth)",
                fix="Remove the secret-named file and/or the secret content; never commit credentials",
                evidence={
                    "axes_triggered": axes_triggered,
                    "matched_paths": path_matches,
                    "matched_patterns": sorted(matched_patterns),
                    "matched_line_count": matched_lines,
                },
            )
        # nothing triggered: either genuinely clean, or every match was overridden
        if (path_matches and path_override) or (matched_patterns and content_override):
            return GateOk(reason="secret_detected_with_override")
        return GateOk(reason="secret_clean")


register_gate("secret_guard", SecretGuard())
