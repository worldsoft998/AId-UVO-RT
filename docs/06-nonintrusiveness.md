# Non-intrusiveness: the rules and the linter

## The rule

The optimizer may not, at any point in the project, read / parse / mirror /
modify / add RTL, testbench, UVM or coverage-model source — not in Python code,
not in configuration files, not in scripts.

"Not in configuration files" is the subtle one. It rules out shipping a config
that names your signals. The framework therefore resolves everything at run time:

| Thing | Where it comes from |
|---|---|
| hierarchy, ports, widths | `describe` / `find` at session start |
| coverage groups, coverpoints, bins | the coverage database (`coverage report -xml`) |
| which ports may be driven | the discovered **input** ports, minus clock/reset names |
| knob names and values | *your* `knobs.json` inventory (user data, not framework code) |
| plusarg/profile mapping | derived from your inventory by `KnobSpace` |

`examples/demo_fifo/cfg/*.json` does name the demo's plusargs. That is user space:
it describes a testbench that ships with the repo, and the framework never reads
it. The linter enforces the boundary by failing if framework code so much as
mentions `examples/`.

## The linter

```bat
python -m aiduvo lint
```

| Rule | Fails when |
|---|---|
| **R1** | an HDL source file (`.sv .svh .v .vh .vhd .vhdl .svp .sva`) exists inside `aiduvo/` |
| **R2** | framework code imports an HDL parser/elaborator or a network/hosted-AI client (`pyverilog`, `hdlparse`, `pyslang`, `tree_sitter*`, `cocotb`, `openai`, `anthropic`, `google.generativeai`, `transformers`, `langchain`, `requests`, `httpx`) |
| **R3** | framework code contains a string literal ending in an HDL extension (`"dut.sv"`) |
| **R4** | framework code references the example design directory |
| **R5** | framework code opens or reads an HDL file at run time |
| **R6** | framework code imports a hosted-AI or network client library |
| **R7** | framework code *executes* a simulator/compiler binary (constructing a command line is fine; the exempt files do that) |

Exempt files (they legitimately build or supervise simulator command lines):
`aiduvo/srie/launcher.py`, `aiduvo/srie/transport.py`, `aiduvo/srie/optimizer.py`,
`aiduvo/blackbox/runner.py`, `aiduvo/blackbox/backend.py`,
`aiduvo/srie/fli_bridge.py`, and the linter itself.

Run it in CI:

```yaml
- run: python -m aiduvo lint
```

## Runtime safety rails

The linter covers the *static* promise. The runtime has its own guarantees:

1. **Only input ports may be driven.** `ReflectionController.check_path` rejects
   anything not discovered as an input.
2. **Clock and reset are never driven.** A generic deny list (`clk`, `clock`,
   `rst`, `reset`, `reset_n`, `scan_en`, `test_mode`, ...) is applied on top; it
   is configurable and case-insensitive.
3. **A hard cap** (`srie.max_forced`, default 8) limits how many signals can be
   forced at once.
4. **A ledger** records every force, and `restore()` releases everything — on
   normal exit, on exception, and on simulator death (the `finally` path).
5. **Dry-run mode** (`srie.dry_run`) prints the Tcl instead of executing it, so
   you can review exactly what the agent would do.

```bat
python -m aiduvo run --config my.json --print-config
REM with "dry_run": true you get a full transcript of intended commands
```

## What about "instrumented optimization"?

The optional instrumentation supported here is **simulator-side**: coverage is
enabled with `vopt +cover=bcestfx`, assertion/FSM/toggle coverage come from the
simulator, and value-change events come from `when` triggers. None of that edits
a source file. If you *want* extra probes in your own testbench, add them
yourself — the framework will happily observe the signals they create, but it
will never add them.
