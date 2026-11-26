# Overview

## The problem

Functional coverage closes slowly. Under uniform constrained-random stimulus the
distribution of hits over the bin space is extremely uneven: a handful of easy
bins absorb most of the cycles, while the bins that encode the interesting
behaviour — `full` while writing, a simultaneous read+write at the boundary, an
error path taken twice in a row — stay at zero.

The manual fix is a loop: read the coverage report, guess a constraint or a seed,
re-run, look again. It is effective and it is exactly what a learning agent can
automate, provided it is allowed to observe the coverage and act on the stimulus.

## Why the constraint "do not touch the source" is the hard part

A tool that reads the testbench can be clever very cheaply: it can find the
constraint block, the covergroup, the sequence, and rewrite them. That is also
what makes such tools unusable: they break on the next refactor, they cannot be
applied to a third-party VIP, they need a per-project integration, and nobody
lets them write into a repository.

AId-UVO-RT takes the opposite bet: **the simulator is the interface.** Everything
it knows it learned at run time from the simulator; everything it does it does
through the simulator's own control commands. That makes it project-agnostic by
construction and makes the integration a config file instead of a code change.

## Design goals

| Goal | How it is met |
|---|---|
| project-agnostic | no source access; hierarchy, coverage and knobs are discovered at run time |
| universal (weak) | every layer talks in abstractions: transport, command vocabulary, coverage tree, action heads |
| real-time | SRIE drives the simulator in cooperative quanta and reacts to pushed events mid-run |
| local-only | numpy only; all training and inference on the machine |
| comparable | one reward, one coverage model, one accounting, one report for all three modes |
| safe | forces are restricted to discovered input ports, capped, ledgered and always released |
| auditable | a linter enforces the non-intrusiveness rules; every decision is logged |

## What "universal" can and cannot mean

Complete universality is not achievable — the requirement says so itself. What is
achieved here:

* **No HDL/HVL knowledge in the framework.** It never knows that a signal is
  called `wr_en` or that a covergroup is called `cg_ops`.
* **Simulator-agnostic core.** The runtime path talks to a `Transport` with a
  small command vocabulary (`describe`, `examine`, `force`, `release`, `run`,
  `coverage`). QuestaSim's Tcl happens to implement all of it; a VPI-based or
  FLI-based shim implements the same vocabulary.
* **Coverage-format-agnostic importer.** UCIS XML is the primary format, with CSV
  and text fallbacks, so any tool that can export coverage can feed the agent.

What it does not claim: a different simulator or a VHDL flow works out of the box
today. The seams exist (documented in [10-extending.md](10-extending.md)) but the
only validated target is QuestaSim + SystemVerilog/UVM.

## The three experiments

```
                    actions                          observations
baseline   seeds 1..N, nothing else                  nothing
blackbox   seed, plusarg profile, run length,        transcript, UCDB
           early abort
runtime    + force on input ports, triggers,         + live hierarchy, values,
           run quantum                              coverage, events
```

The three are deliberately nested: every blackbox action is available to the
runtime mode, and the baseline is the blackbox runner with the agent switched
off. That nesting is what makes the comparison meaningful — the only variable is
how much the agent is allowed to see and do.
