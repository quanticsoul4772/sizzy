"""``python -m devharness.panel`` — launch the web control panel.

Binds ``DEVHARNESS_PANEL_ADDR`` (default ``127.0.0.1:8090``) against ``DEVHARNESS_DB``. Loopback-only
by design — put Caddy (TLS + basic auth) in front for remote/mobile access.
"""

from devharness.panel.server import serve

if __name__ == "__main__":
    serve()
