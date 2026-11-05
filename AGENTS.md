# MRIL agent notes

## Commands

- Install: `pip install -e ".[dev]"` (venv at `.venv/`)
- Test: `.venv/bin/python -m pytest`
- Example: `.venv/bin/python examples/basic_routing.py`
- CLI: `.venv/bin/mril --db <db> explain|task|tasks`

## Conventions

- `mril.core` must stay I/O-free and framework-neutral. Adapters own all
  framework imports, and they import lazily — every module must be importable
  with zero optional dependencies installed.
- Events are immutable and append-only; fix forward, never edit the ledger.
- New event fields: add with defaults, bump `SCHEMA_VERSION` only on breaking
  changes. `event_from_dict` must tolerate unknown keys.
- Policies are pure functions of (context, constraints, candidates, state,
  seeded rng). Any nondeterminism goes through the injected RNG so decisions
  stay replayable.
- Cost math uses price snapshots recorded in `RouteDecided`, never live
  registry prices.
- When in doubt about an outcome, it's `inconclusive` — never upgrade to
  success without explicit verifier evidence.
