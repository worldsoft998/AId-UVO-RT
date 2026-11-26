# Contributing

## Ground rules

1. **Never read, parse or generate HDL/TB/UVM source.** That is the whole point
   of the project. `python -m aiduvo lint` must pass before a PR is mergeable.
2. **No network calls, no hosted AI.** All learning and inference is local.
3. **No new hard dependencies.** numpy is the only one; matplotlib is optional.
4. **Every new behaviour needs a test that runs without a simulator.** The mock
   backend exists for exactly this.

## Development setup

```bash
python -m pip install -e ".[dev]"
python -m aiduvo selftest          # end-to-end, no simulator needed
python -m pytest -q                # unit tests
python -m pytest -q -m "not slow"  # fast subset
python -m aiduvo lint
```

## Style

* Python 3.9+ compatible (no `match`, no `X | Y` type unions at runtime).
* Type hints on public functions.
* Docstrings explain *why*, not *what*; comments only for non-obvious invariants.
* Keep modules small and single-purpose; the layer boundaries in
  `docs/01-architecture.md` are load-bearing.

## Adding an algorithm

See `docs/10-extending.md` §3. A new learner needs: `select`, `observe`,
`end_episode`, optional persistence, and a test that shows it learns a toy
preference.

## Adding a transport

See `docs/10-extending.md` §1. The checklist at the end of that section is the
acceptance criterion.

## Commit messages

```
area: imperative summary

Why the change was needed, what it does, and anything a reviewer would
otherwise have to reverse-engineer.
```

`area` is one of `core`, `srie`, `blackbox`, `coverage`, `rl`, `reporting`,
`discovery`, `lint`, `scripts`, `docs`, `examples`, `tests`.
