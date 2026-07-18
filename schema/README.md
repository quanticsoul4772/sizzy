# schema/

Forward-only, numbered SQL migrations under `migrations/` (`0001`–`0028`). The runner
(`runtime/devharness/migrate.py`) applies them in order and fails closed on a gap, a misnumbered
file, or an applied set that is not a contiguous prefix. Migrations are never edited, renumbered,
or reversed. Projection tables avoid `AUTOINCREMENT` so a DELETE+replay rebuild reproduces rowids
(Invariant 8 parity). Conventions and the how-to are in `CONTRIBUTING.md`.
