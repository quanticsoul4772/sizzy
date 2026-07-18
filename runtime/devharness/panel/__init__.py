"""Web control panel — a browser front over the console's action layer.

The operator drives the whole devharness loop from a browser (buttons/forms) instead of the Textual
TUI. It reuses the console's UI-agnostic action layer (``devharness.console`` ``Console*`` classes,
which write only through ``EventBus.emit_sync``) and the Rust sidecar's read-only SSE for live state;
it adds an HTTP write/state endpoint and (built separately) a Svelte control UI.

The load-bearing constraint is the single writer: ``EventBus.emit_sync`` is a non-atomic
read-then-insert on the event hash chain, so — unlike the TUI, which funnels every worker emit to one
UI thread — the panel serializes every emit through one connection under one lock
(``panel.writer.PanelWriter``). Long LLM build steps run in a background worker with a process-wide
single-flight guard (``panel.worker.BuildRunner``), the web analog of the TUI's ``_busy`` flag.
"""
