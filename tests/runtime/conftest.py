"""Runtime test-suite config.

The runtime tests exercise the ACI shell / test-runner on the host path (the worker is mocked, so the
commands are test-controlled, not agent-controlled). The L4-1 fail-closed guard refuses unsandboxed host
execution unless authorized, so authorize it for the whole runtime suite — this is a trusted, controlled
test host. A test that specifically exercises the REFUSAL unsets this via monkeypatch.
"""

import os

os.environ.setdefault("DEVHARNESS_ALLOW_HOST_SHELL", "1")
