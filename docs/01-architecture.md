# Architecture

![AId-UVO-RT layered architecture](diagrams/architecture.svg)

## Layers

```
┌──────────────────────────────────────────────────────────────────────────────┐
│  entry points                                                                │
│    scripts/windows/*.bat     scripts/linux/*.sh     python -m aiduvo ...      │
├──────────────────────────────────────────────────────────────────────────────┤
│  orchestration            aiduvo/core/engine.py   (Campaign)                 │
│    budget · reward · state encoder · action space · policy · history store    │
├──────────────────────────────────────────────────────────────────────────────┤
│  backends                 aiduvo/srie/optimizer.py     (live, SRIE)          │
│                           aiduvo/blackbox/backend.py   (closed box)          │
│                           aiduvo/blackbox/backend.py   (mock, synthetic)     │
├──────────────────────────────────────────────────────────────────────────────┤
│  simulator access         aiduvo/srie/                                       │
│    transport   pipe · Tcl socket · FLI · mock                                │
│    tcl         command builders + tolerant parsers                           │
│    introspection  describe / examine / coverage      (read)                  │
│    reflection     force / release / when / run        (write, guarded)       │
├──────────────────────────────────────────────────────────────────────────────┤
│  shared services                                                            │
│    coverage/  model · UCIS/CSV/text importers · metrics · SQLite store        │
│    rl/        bandits · tabular Q · DQN · PPO · ANN surrogate · numpy MLP     │
│    reporting/ comparison · SVG charts · markdown · HTML                      │
│    discovery/ hierarchical discovery -> generated config                     │
│    semantics/ optional role annotation                                       │
│    lint/      non-intrusiveness compliance checker                           │
└──────────────────────────────────────────────────────────────────────────────┘
```

## Data flow of one campaign

```mermaid
flowchart TB
    subgraph cfg [Configuration]
        C1[campaign.json]
        C2[knobs.json]
    end

    subgraph engine [Campaign engine]
        E1[prepare backend]
        E2[build action space]
        E3[choose action]
        E4[run episode]
        E5[merge coverage]
        E6[compute reward]
        E7[update policy]
        E8[store + report]
    end

    subgraph backend [Backend]
        B1[SRIE session]
        B2[SimRunner + UCDB]
    end

    subgraph sim [QuestaSim]
        S1[vsim process]
        S2[coverage database]
        S3[transcript]
    end

    C1 --> E1
    C2 --> E1
    E1 --> E2 --> E3 --> E4
    E4 --> B1
    E4 --> B2
    B1 --> S1
    B2 --> S1
    S1 --> S2
    S1 --> S3
    S2 --> E5
    S3 --> E5
    E5 --> E6 --> E7 --> E3
    E5 --> E8
```

## The runtime loop in detail

```mermaid
sequenceDiagram
    participant P as Python (agent)
    participant T as Transport
    participant V as vsim
    P->>T: start(vsim -c -do bootstrap)
    T->>V: launch
    V-->>T: @@SRIE_READY <version>@@
    P->>T: version -short / describe / coverage query
    Note over P: capability probe
    P->>T: describe -depth 1 /
    T->>V: describe
    V-->>T: regions, ports, widths
    P->>T: coverage report -xml -output f
    V-->>P: UCIS XML (bin tree)
    Note over P: build observation + action space
    loop every quantum
        P->>T: examine <ports>  (or cached)
        T->>V: examine
        V-->>P: values
        P->>T: force -freeze <port> <value>
        V-->>T: ok
        P->>T: run <N ns>
        V-->>T: @@SRIE_EVT {"kind":"trigger",...}@@  (during the run)
        V-->>T: @@SRIE_END <cid> rc=0@@
        P->>T: coverage report -xml -output f
        V-->>P: new snapshot
        Note over P: reward, learn, decide
    end
    P->>T: release all / nowhen all / quit -f
```

## Cooperative quanta

A simulator's command interpreter is single-threaded: while `run 1000 ns` is
executing, it is not reading commands. AId-UVO-RT therefore drives the simulator
in **quanta** — `run <quantum_cycles * period>` — and makes a decision between
quanta. This is the standard way to get deterministic, reproducible runtime
steering, and it has two useful properties:

* the agent can act at any cycle boundary, so "instantaneous" is bounded by one
  quantum, not by the end of the run;
* value-change triggers installed with `when` still fire *inside* a quantum and
  push events immediately, so the agent can also react to specific events by
  shortening the next quantum.

`quantum_cycles` is the main latency/overhead knob: 100–500 cycles is a good
starting point for a small block; a large SoC wants 1 000–10 000.

## Files produced by a campaign

```
runs/<mode>_<algo>_<timestamp>/
├── campaign_config.json      the exact config used (reproducible)
├── campaign_result.json      curve, episodes, metadata, final metrics
├── history.sqlite            per-run snapshots, per-bin hits, actions
├── policy.npz / policy.json  the learned model (AI modes)
├── _artifacts/run_0000/      transcript.log, coverage.ucdb, run.do  (blackbox)
└── _srie_work/               generated bootstrap, per-run vsim logs  (runtime)
```

## Why the reward and the state encoder live in `core`

Both backends must be measured the same way, so the reward function and the state
encoder are backend-agnostic and are applied by the campaign engine, not by the
backend. The backend's only job is to turn an `Action` into an `EpisodeResult`
plus a coverage snapshot.
