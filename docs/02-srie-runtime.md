# SRIE — the runtime engine

**S**imulator **R**untime **I**ntrospection **E**ngine: the part of the optimizer
that treats a running simulator as a dynamic white box without touching a line of
HDL, testbench or UVM code.

## The wire protocol

Every interaction is one Tcl command per line, answered by free-form text
terminated by a sentinel. Events the simulator pushes arrive on the same channel,
asynchronously.

```
python ->  <command>\n
sim    ->  ... output lines ...
sim    ->  @@SRIE_END <id> rc=<0|1>@@
sim    ->  @@SRIE_EVT {"kind":"trigger","label":"...","t":"[now]"}@@   (any time)
sim    ->  @@SRIE_READY <version>@@                                     (once)
sim    ->  @@SRIE_FATAL <message>@@
```

* **pipe transport** wraps each command in
  `if {[catch {<cmd>} out]} {...}; puts $out; puts "@@SRIE_END <id> rc=...@@"`.
* **socket transport** sends `<id>\t<cmd>`; the Tcl server does the same wrapping
  and can also push events to the channel.
* **FLI transport** speaks the same lines from a C shim.

## The command vocabulary

| Verb | Tcl form | Purpose |
|---|---|---|
| describe | `describe -depth 1 {/path}` | regions, ports, widths, directions |
| find | `find nets -in {/path}` | fallback enumeration |
| examine | `examine -value {/path}` | read a value (batched with `;`) |
| force | `force -freeze {/path} 1` | drive an input |
| release | `release {/path}` | stop driving |
| when | `when -label L {expr} {srie_evt "..."}` | value-change trigger |
| nowhen | `nowhen {L}` | remove a trigger |
| run | `run 500 ns` | advance by a quantum |
| stop | `stop` | halt |
| coverage | `coverage report -detail -xml -output f` | coverage snapshot |
| time | `examine -time` | simulator clock |

Every builder lives in `aiduvo/srie/tcl.py`, so if your QuestaSim release spells
something differently there is exactly one place to change.

## Capability probing

`SRIESession.open()` probes the surface once and stores a matrix:

```
transport: questa-pipe
version  : 2024.1
  coverage   OK   1024 bins
  describe   OK   38 lines
  examine    OK   requires a readable signal path
  find       NO   invalid command name "find"
  force      OK   requires a writable signal path
  when       OK   trigger install/remove
  version    OK   2024.1
```

If `describe` is not usable, discovery falls back to `find nets`, then to a
hierarchy dump you provide. If coverage is not compiled in, the session still
runs — it just reports zero bins, and the campaign says so loudly.

```bat
python -m aiduvo srie probe --config config\campaign_runtime.json
python -m aiduvo srie selftest --config config\campaign_runtime.json
```

## Discovery

`Introspector.discover(root, depth)` is a breadth-first walk:

1. `describe -depth 1 <root>` → children (regions and signals);
2. for each child that is a region, recurse until `depth` path segments;
3. classify direction (`input` / `output` / `internal`) and width;
4. if the simulator does not label regions at all, probe one extra level per node
   as a fallback.

The result is a `Hierarchy`: `inputs()`, `outputs()`, `regions()`, `paths()`.
Nothing is cached to disk by default — the hierarchy is learned fresh each
session, which is what makes it survive a refactor.

## Reflection (writing to the simulation)

`ReflectionController` is the only writer. It offers:

* `force(path, value, freeze)` / `release(path)` / `release_all()`
* `apply_bias(mode, paths, current)` with modes
  `hold | low | high | toggle | random_walk | release`
* `pattern_bias("1010")` for an explicit bit pattern
* `install_trigger(label, expr, **fields)` / `remove_trigger(label)`
* `run_for(spec)` / `run_quantum(cycles, period_ns)` / `stop()` / `quit()`
* `restore()` — releases every force and removes every trigger

Safety rails are described in [06-nonintrusiveness.md](06-nonintrusiveness.md).

## The two nested loops

```
for run_index in 0..max_runs:                       # OUTER (inter-run)
    action = outer_policy.select(state)             # seed mode, focus, profile
    open session with (seed, plusargs)
    prev = coverage()
    for step in 0..intra_steps:                     # INNER (intra-run)
        state = encoder(prev, signals, elapsed)
        a = inner_policy.select(state)              # force_bias x quantum
        bias(a, targets); run_quantum(a.quantum)
        snap = coverage()
        reward = f(prev, snap, dt_wall, dt_cycles)
        inner_policy.observe(...)
        prev = snap
        if closure >= target: break
    merge(final); outer_policy.observe(...)
```

Two policies, two scopes, one reward function and one history store. The outer
loop is where bandits shine (few decisions, noisy reward); the inner loop is
where PPO/DQN shine (many decisions per run, sequential state).

### Which signals get driven

`_bias_targets()` takes the discovered input ports, removes clock/reset via the
deny list, caps at `srie.max_forced`, and — when the outer policy chooses a
specific coverage group as `focus` — rotates the window over the candidate list
using a CRC32 of the group name (stable across processes, unlike `hash()`).
This is how a group-specific focus becomes a stimulus choice without any
knowledge of what the group means.

### Optional triggers

```json
"srie": {
  "trigger_specs": [
    { "label": "out_rise", "expr": "{out0} == 1", "kind": "trigger" },
    { "label": "in_fall",  "expr": "{in0} == 0",  "kind": "trigger" }
  ]
}
```

`{in0}`, `{in1}`, ... and `{out0}`, `{out1}`, ... are substituted with the
discovered paths at session start, so the spec stays project-agnostic. The
trigger body is `srie_evt "<json>"`, which writes to the socket (or stdout) the
instant the condition holds — that is the "instantaneous" path.

## Cost model

Per quantum the agent pays: one `examine` batch, one `force` batch, one `run`,
one coverage report. On a small block that is a few milliseconds of wall clock
for 100–500 simulated cycles. Tuning:

| Knob | Effect |
|---|---|
| `quantum_cycles` | smaller = finer steering, more overhead |
| `intra_steps` | decisions per run |
| `coverage_every` | take a coverage snapshot every N steps instead of every step |
| `max_forced` | more driven signals = stronger stimulus, more overhead |
| `discover_depth` | deeper = more of the hierarchy, slower start |

## Failure modes and what happens

| Symptom | Behaviour |
|---|---|
| simulator dies mid-run | `TransportError`, the run is recorded with `error`, the campaign continues |
| command rejected | `CommandError` from `require_ok()`, or `ok=False` where the caller tolerates it |
| no coverage compiled in | zero bins, a loud note, the campaign still records the run |
| trigger not supported | probe reports `when: NO`, the agent falls back to quantum-only decisions |
| force refused | logged, the force is not added to the ledger, the bias degrades to the remaining ports |
