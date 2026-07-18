# dashboard/ — the Svelte 5 dashboard

26 live tiles rendering the harness state, each subscribed to the sidecar's `/events/all` SSE stream. See
the [project README](../README.md) for the big picture.

## What it does

- Renders strictly from the event stream — the dashboard **never queries projection tables**; a tile can
  only show what its feeding event's payload carries.
- Opens one shared `EventSource` (`src/events.js`) and demuxes by `event_type` to per-tile subscribers.
- The dispatch list (`src/events.generated.js`) is **derived** from the Python `EVENT_TYPES` registry, so
  there is no hand-kept list to drift; regenerate with `npm run generate-events`.

## Install & run

```bash
npm install
npm run dev          # vite dev server (expects the sidecar on its SSE port)
npm run build        # production build (prebuild regenerates events.generated.js)
npm run check        # svelte-check — must be 0 errors
```

## Tile registry

Every tile is listed in `src/tiles/registry.js` (`TILE_MANIFEST`) and must match the spec's §S9 tile
manifest exactly — the C7 boot-check (`check_dashboard_tile_coverage`) fails closed on any divergence.
To add a tile: create the `*Tile.svelte` component, register it in `App.svelte`, add its name to
`TILE_MANIFEST` **and** to the spec §S9 manifest, and ensure its event types are in the registry (the
derived dispatch list picks them up). Tiles are intentionally unstyled (skeleton posture).
