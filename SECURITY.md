# Security

devharness is a harness that **writes code, spends money, and can open external pull requests**
under operator control. This document is the security posture a reader should understand before
running it. It is not a hardened multi-tenant service — it is a single-operator tool whose trust
model is "the operator is on a machine they trust" (commitment 14).

## Reporting a vulnerability

Please report suspected vulnerabilities privately via GitHub's **Security → Report a vulnerability**
(private advisory) on this repository rather than opening a public issue. Include a reproduction and
the affected component (`runtime/`, `sidecar/`, panel, sandbox, OSS envelope).

## What this software can do (know before you run)

- **Spends real LLM money.** The drivers (`scripts/run_*`), the operator console, and the web panel
  dispatch Claude Agent SDK sessions billed to your Claude login or API key. A multi-task build can
  cost tens of dollars.
- **The overage fallback rebills your API key.** When a subscription's weekly quota is exhausted,
  `runtime/devharness/sdk_query.py` retries the call once with the `ANTHROPIC_API_KEY` from
  `~/.claude.json` — deliberate (so a drive doesn't die mid-loop), but it silently shifts spend to
  metered API billing when the quota runs out.
- **Opens real GitHub PRs.** `scripts/run_oss.py` (the §S5 OSS envelope) pushes a fork branch and
  opens a real PR when `GH_TOKEN` + `DEVHARNESS_OSS_PUSH_REPO` are set. It is **operator-only** by
  design; external intake is out of scope.

## Fail-closed boundaries

- **Host shell execution is fail-closed.** `runtime/devharness/aci/host_exec.py` refuses to run an
  unsandboxed host subprocess (`HostExecutionRefused`) unless the operator has **explicitly**
  authorized it with `DEVHARNESS_ALLOW_HOST_SHELL=1` ("I am on a trusted host") **or** a §S5
  `SandboxLauncher` is attached (`DeveloperRole(sandbox_launcher=…)`). A host subprocess is not
  contained — the developer worker's shell/tests run with your privileges — so this is an opt-in,
  never a default.
- **The multi-tier sandbox** (`runtime/devharness/sandbox/`) contains OSS/untrusted execution when
  attached: `pivot_root` into a worktree-only root, net/pid/uts isolation, unprivileged execution,
  and a seccomp syscall filter. CI runs the fail-closed `MockSandboxLauncher` (no real exec on
  non-Linux); the real WSL/VPS launchers are operator-driven. SC-3 (100% of OSS tasks run inside the
  sandbox; an out-of-sandbox launch *fails*, not warns) is structurally enforced by the `sandbox`
  gate.
- **Gates fail closed.** A gate denies a known-bad intent before any write and carries structured
  evidence; the four §S5 OSS gates plus the write-lock/spec-signed/verifier-attached gates are the
  seven **core gates** the learning loop can never weaken (Invariant 12).

## The web control panel

`runtime/devharness/panel/` is a **write surface with no authentication of its own.** It binds
loopback (`127.0.0.1`) by default and **must never face a network without an authenticating reverse
proxy** (TLS + basic auth — see `deploy/vps/`). Its request gate (rev 0.4.15) validates the `Host`
and `Origin` headers on every request — rejecting cross-site and DNS-rebound requests — but that is
CSRF/rebinding protection, **not** access control; authentication is the reverse proxy's job. The
proxy must forward the original `Host` header, and `DEVHARNESS_PANEL_PUBLIC_HOST` must name the
public domain or every proxied request is refused.

## Secrets

- No real API keys, private keys, tokens, IPs, or hostnames are committed to this repository.
- Credential-shaped string literals exist only as **synthetic test fixtures and regex patterns** in
  `runtime/devharness/gates/secret_guard.py` (the secret-scanner's own patterns), its tests, and the
  adversarial probes — none are real secrets. The secret_guard tests build JWT-shaped fixtures at
  runtime specifically so no scannable token literal sits in the source.
- `.gitignore` excludes `*.db`, `var/`, `.env*`, `*.pem`, and `.claude/settings.local.json` — the
  event stores, local env, keys, and operator-local settings never enter the tree.
- The Claude Agent SDK is always invoked with `setting_sources=[]` (no silent inheritance of
  `CLAUDE.md` or local settings into agent sessions).
