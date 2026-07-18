"""Sandbox env substrate (B4.2.5, §S5).

A `SandboxLauncher` interface with three concrete bindings selected by environment —
MockSandboxLauncher (CI + non-Linux, fail-closed), WSLSandboxLauncher (real namespace isolation
on the Windows dev box via WSL), VPSSandboxLauncher (a remote Ubuntu VPS over SSH). The B4.3
`sandbox` gate consumes this substrate to enforce SC-3. CI runs mock-only.
"""
