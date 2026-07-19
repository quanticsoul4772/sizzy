"""Context-injection scan (B4.1, §S5 intake hardening; repo-file scan rev 0.3.67 / F4).

Quarantine hostile instructions in an OSS request before they can reach a planning prompt. The
scan is conservative — it returns the names of the patterns it detected (empty list = clean).

`scan_repo_files` extends the same scan to the upstream target repo's standard agent-instruction
vectors (README / CONTRIBUTING / AGENTS.md / CLAUDE.md / `.github/` copilot-instructions) read from
a LOCAL clone. This closes the F4 gap where the module docstring previously CLAIMED these files were
"scanned in later sub-phases" with no such caller: the fork worktree is the untrusted upstream
checkout and the developer worker's built-in Read/Grep/Glob tools stay live (`setting_sources=[]`
only stops dotfile auto-ingest, not tool reads), so a hostile CONTRIBUTING.md could reach the
worker's reasoning. Intake now scans these files up front and fail-closes on a hit.
"""

import re
from pathlib import Path

# instruction-override phrases (case-insensitive)
_OVERRIDE_PHRASES = (
    "ignore previous instructions",
    "ignore all previous",
    "disregard the above",
    "disregard previous",
    "new instructions:",
    "override your instructions",
    "you are now",
    "system prompt:",
)

# >= 40 contiguous base64-ish chars, or >= 3 consecutive %XX url-encodings
_BASE64_RE = re.compile(r"[A-Za-z0-9+/]{40,}={0,2}")
_URLENC_RE = re.compile(r"(?:%[0-9A-Fa-f]{2}){3,}")
_HEX_RE = re.compile(r"\A[0-9a-fA-F]+\Z")  # a pure-hex run is a SHA/hash/id, not an encoded payload

# Subresource-integrity hashes (rev 0.4.24): "sha512-<base64>" etc. — npm package-lock.json integrity
# fields, CDN <script integrity=...> snippets. All three prefixes are exactly 7 chars, and each
# algorithm's base64 body has ONE exact length (incl. padding): sha256 -> 44, sha384 -> 64, sha512 -> 88.
_SRI_RUN_LENGTHS = {"sha256-": 44, "sha384-": 64, "sha512-": 88}


def _is_sri_hash(m: re.Match) -> bool:
    """True iff the matched base64 run is exactly an SRI hash body: preceded by a `shaN-` prefix AND
    exactly that algorithm's base64 length. The `-` sits outside _BASE64_RE's char class, so the match
    starts AFTER the prefix — hence the 7-char preceding-slice check (a fixed slice, since all three
    prefixes are 7 chars; a lookbehind couldn't pair the run length to the algorithm). The prefix
    compare is case-insensitive — SRI algorithm tokens are ASCII-case-insensitive per the spec, and an
    uppercase `SHA384-` snippet would otherwise re-open the false positive (review catch)."""
    expected = _SRI_RUN_LENGTHS.get(m.string[max(0, m.start() - 7):m.start()].lower())
    return expected is not None and len(m.group(0)) == expected


def _has_encoded_payload(text: str) -> bool:
    """True if text contains a base64-ish run (excluding pure-hex SHAs/hashes/ids and exact-length
    SRI integrity hashes) or url-encoding.

    A 40-char git commit SHA matches the base64-ish pattern, and the harness's OWN events are full of
    them (checkpoints, commits, ids) — so flagging pure-hex runs floods the retro antibody queue with
    false positives (every internal terminal looked 'hostile'). Only a long run that is NOT pure hex
    (real base64 has mixed case / +/= ) or a url-encoding is treated as an encoded payload.

    SRI hashes (rev 0.4.24) are the base64 analog of that fix: an npm package-lock.json integrity
    field (`"integrity": "sha512-<88-char base64>"`) quarantined a clean jsonflat retro terminal, and
    a legitimate repo README carrying a CDN `integrity="sha384-…"` snippet was rejected at OSS intake.
    The exclusion is tightly scoped — `shaN-` prefix AND the exact per-algorithm length — so a bare or
    wrong-length base64 run still flags. Documented residuals, weighed deliberately: an attacker CAN
    chain `sha512-<exactly 88 base64 chars>` chunks to carry an encoded payload past this detector —
    but the pre-existing pure-hex exclusion above is UNBOUNDED (an arbitrary-length hex-encoded
    payload already passes), so the length-anchored SRI carve-out adds no materially new smuggling
    channel; this detector is a tripwire for casual encoded blobs, not a cryptographic barrier —
    nothing downstream decodes these runs, and the instruction_override/markdown_comment detectors
    still see plaintext. A glued prefix (`xsha512-…`) is excluded too (still an exactly-SRI-shaped
    run). The alternative — keeping the flag on SRI runs — was a live false-reject of legitimate
    repos at the fail-closed intake gate and of clean terminals at retro quarantine.
    """
    for m in _BASE64_RE.finditer(text):
        if _HEX_RE.match(m.group(0)):
            continue
        if _is_sri_hash(m):
            continue
        return True
    return bool(_URLENC_RE.search(text))


def scan_for_injection(text: str) -> list[str]:
    """Return the names of injection patterns detected in ``text`` (empty list when clean)."""
    if not text:
        return []
    detected = []
    lower = text.lower()
    if "<!--" in text or "-->" in text:
        detected.append("markdown_comment")
    if any(phrase in lower for phrase in _OVERRIDE_PHRASES):
        detected.append("instruction_override")
    if _has_encoded_payload(text):
        detected.append("encoded_payload")
    return detected


def scan_texts(texts) -> list[str]:
    """Scan several text fields; return the de-duplicated, order-preserving pattern names detected."""
    seen, out = set(), []
    for text in texts:
        for name in scan_for_injection(text or ""):
            if name not in seen:
                seen.add(name)
                out.append(name)
    return out


# The upstream repo's standard agent-instruction files — the injection vectors a hostile fork could
# carry into the developer worker's reasoning (its cwd is the fork worktree, built-in reads live).
_REPO_INJECTION_FILES = (
    "README.md", "README", "README.rst", "README.txt",
    "CONTRIBUTING.md", "CONTRIBUTING", "CONTRIBUTING.rst",
    "AGENTS.md", "CLAUDE.md", ".cursorrules",
    ".github/copilot-instructions.md", ".github/CONTRIBUTING.md",
)
_MAX_REPO_FILE_BYTES = 512 * 1024  # cap per file — a scan is a substring/regex pass, not an ingest


def scan_repo_files(repo_path, *, files=_REPO_INJECTION_FILES, max_bytes=_MAX_REPO_FILE_BYTES) -> list[str]:
    """Scan the upstream repo's standard agent-instruction files (from a LOCAL clone at ``repo_path``)
    for the same injection patterns. Returns the de-duplicated pattern names detected (empty = clean or
    no such files). A missing/undecodable file is skipped (absence is not an injection); a path that
    escapes ``repo_path`` is ignored (defense against a crafted file entry)."""
    if not repo_path:
        return []
    root = Path(repo_path).resolve()
    texts = []
    for rel in files:
        fp = (root / rel).resolve()
        if root not in fp.parents and fp != root:  # never read outside the repo root
            continue
        try:
            if fp.is_file() and fp.stat().st_size <= max_bytes:
                texts.append(fp.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue  # unreadable file -> skip (absence is not a hit)
    return scan_texts(texts)
