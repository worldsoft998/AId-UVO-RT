# Optional FLI shim

`srie_fli.c` is a **reference implementation** of the lowest-latency SRIE
transport. It loads into QuestaSim as a foreign library and exposes the live
simulation over a TCP socket using the same line protocol as the Tcl transport,
so `aiduvo` treats it as just another transport:

```json
{ "transport": { "kind": "fli", "host": "127.0.0.1", "port": 7654 } }
```

## When to use it

| | Tcl pipe | Tcl socket | FLI shim |
|---|---|---|---|
| Setup | none | none | compile once |
| Steering latency | one round trip per quantum | same | same, lower overhead |
| Value-change events | `when` triggers | `when` triggers | per-transition callbacks |
| Coverage import | Tcl report | Tcl report | needs the Tcl path or `vcover` |

For most designs the Tcl transports are enough and are the supported path.
Use FLI when you need every transition of a fast signal, or when the
transcript/Tcl round trip dominates the steering budget.

## Build

```bat
cd scripts\questa\fli
build_fli.bat
```

## Run

```bat
vsim -foreign "srie_fli_init srie_fli.dll 7654" -c work.tb_top_opt
```

## Status

The code follows the documented `mti` API (`mti_FindRegion`,
`mti_GetSignalByName`, `mti_ScheduleDriver`, `mti_AddSignalEvent`,
`mti_ScheduleWakeup`). It has **not** been validated against every QuestaSim
release; expect to adjust signal-width handling (`mti_GetSignalValueHigh`) and
the driver scheduling flags for your version. Treat it as a starting point.
