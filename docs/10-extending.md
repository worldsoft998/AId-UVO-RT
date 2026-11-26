# Extending the framework

Four seams are designed for extension. None of them requires touching the
engine, the reward or the reporting.

## 1. A new simulator

Everything the runtime path does goes through `Transport` + the command
vocabulary in `aiduvo/srie/tcl.py`. Two options:

**(a) A different Tcl dialect** (ModelSim SE, Riviera, Cadence `ncsim -tcl`).
Subclass `Transport`, implement `start()`, `_send()`, `close()`, and make the
bootstrap define the same helper procs. Then register it in
`aiduvo/srie/transport.make_transport`.

**(b) A C-level API** (VPI, VHPI, FLI, DPI). Write a shim that speaks the same
line protocol — that is exactly what `scripts/questa/fli/srie_fli.c` does — and
reuse `QuestaTclSocketTransport` as the client. The framework cannot tell the
difference.

```python
class MyTransport(Transport):
    name = "mysim"
    def start(self, timeout=120.0): ...
    def _send(self, command: str, cid: int): ...
    def close(self): ...
```

Checklist for a new simulator:

* [ ] `@@SRIE_READY <version>@@` printed once at startup;
* [ ] `<cid>\t<cmd>` framing (socket) or `catch`-wrapped commands (pipe);
* [ ] `@@SRIE_END <cid> rc=<0|1>@@` after every command;
* [ ] `describe`, `examine`, `force`, `release`, `run`, `coverage` implemented;
* [ ] events pushed as `@@SRIE_EVT {json}@@`;
* [ ] `aiduvo srie probe` reports OK for the capabilities you support.

## 2. A new HDL / HVL

The framework never sees HDL, so "supporting VHDL" is mostly about the
simulator's coverage export:

* VHDL coverage usually comes out as UCIS XML too — nothing to do;
* if it comes out as text, extend `parse_text_report` in
  `aiduvo/coverage/ucis.py`;
* if it comes out as CSV, `parse_csv` already takes column names.

The only HDL-specific thing in the framework is the *optional* semantic layer
(`aiduvo/semantics/layer.py`), which classifies signal names into roles using
generic conventions. Add a rule for your naming style there if you want better
force-target ordering; nothing breaks without it.

## 3. A new learner

```python
from aiduvo.rl.base import Policy, register

@register
class MyPolicy(Policy):
    name = "mypolicy"
    learns = True

    def __init__(self, n_actions, state_dim, seed=0, **kwargs):
        super().__init__(n_actions, state_dim, seed, **kwargs)
        ...

    def select(self, state, mask=None, explore=True) -> int: ...
    def observe(self, state, action, reward, next_state=None, done=False) -> dict: ...
    def _npz_items(self): ...      # persistence (optional)
    def _load_npz(self, data): ... # persistence (optional)
```

Import it from `aiduvo/rl/__init__.py` so `@register` runs, add the name to
`ALGORITHMS`, and it is immediately selectable from the batch menu and the CLI.

Contract:

* `select` returns an index in `[0, n_actions)`;
* `observe` is called once per decision with the reward that decision produced;
* `end_episode` is called at the end of each simulation run;
* `state` is always a `float32` vector of length `state_dim`.

## 4. A new coverage importer

```python
from aiduvo.coverage.model import CoverageSnapshot, Bin

def parse_my_format(path: str) -> CoverageSnapshot:
    snap = CoverageSnapshot(source=path)
    for group, cp, name, hits in my_reader(path):
        snap.add_bin(group, cp, Bin(name=name, hits=hits))
    return snap
```

Then add the format to `load_coverage`'s dispatcher. The only requirements are a
group name, a coverpoint name, a bin name and a hit count per bin — the rest of
the framework derives everything else.

## 5. A new knob kind

`aiduvo/blackbox/knobs.py` renders knob values into simulator arguments. Add a
kind by extending `KNOB_KINDS` and `Knob.to_plusarg`:

```python
KNOB_KINDS = (..., "plusarg_real")

def to_plusarg(self, value):
    if self.kind == "plusarg_real":
        return f"+{self.name}={float(value):.4f}"
    ...
```

## Where NOT to extend

Resist the temptation to add a "read the constraint block" helper, a
"parse the covergroup" helper, or an "inject a probe into the testbench" helper.
Each of them would be genuinely useful and each of them would break the one
promise that makes this tool deployable. The linter will reject them (R2/R3/R5),
and that is by design.
