import pytest

from aiduvo.srie import tcl
from aiduvo.srie.protocol import parse_end_line, parse_event_line
from aiduvo.srie.tcl import parse_value
from aiduvo.srie.reflection import ReflectionController
from aiduvo.srie.session import SRIEConfig, SRIESession
from aiduvo.srie.transport import MockTransport
from aiduvo.srie.triggers import trigger_body


def test_protocol_helpers():
    assert parse_end_line("@@SRIE_END 7 rc=0@@") == (7, True)
    assert parse_end_line("@@SRIE_END 7 rc=1@@") == (7, False)
    assert parse_end_line("garbage") is None
    evt = parse_event_line('@@SRIE_EVT {"kind": "trigger", "label": "x"}@@')
    assert evt is not None and evt.kind == "trigger" and evt["label"] == "x"
    assert parse_value("'h1f")[0] == 31
    assert parse_value("'b1010")[0] == 10
    assert parse_value("42")[0] == 42
    assert parse_value("'bx1")[0] is None


def test_trigger_body_is_tcl_safe():
    body = trigger_body("trigger", label="L", t="[now]")
    assert body.startswith('srie_evt "')
    assert "[now]" in body          # left for Tcl to substitute
    assert '\\"' in body            # inner quotes escaped


def test_pipe_transport_describe():
    t = MockTransport(seed=3)
    t.start()
    try:
        res = t.execute(tcl.describe("/tb/top", 1))
        assert res.ok
        nodes = tcl.parse_describe(res.stdout, parent="/tb/top")
        assert any(n.path == "/tb/top/u_dut" for n in nodes)
        assert any(n.kind == "region" for n in nodes)
    finally:
        t.close()


def test_pipe_transport_force_examine_release():
    t = MockTransport(seed=3)
    t.start()
    try:
        assert t.execute(tcl.force("/tb/top/u_dut/in_00", "1")).ok
        res = t.execute(tcl.examine("/tb/top/u_dut/in_00"))
        pairs = dict(tcl.parse_examine(res.stdout))
        assert tcl.parse_value(pairs["/tb/top/u_dut/in_00"])[0] == 1
        assert t.execute(tcl.release("/tb/top/u_dut/in_00")).ok
    finally:
        t.close()


def test_unknown_command_reports_error():
    t = MockTransport()
    t.start()
    try:
        res = t.execute("frobnicate /x")
        assert not res.ok
        assert "invalid command" in res.error
    finally:
        t.close()


def test_when_trigger_pushes_event_during_run():
    t = MockTransport(seed=3)
    t.start()
    try:
        assert t.execute(tcl.when("w1", "/tb/top/u_dut/in_00 == 1",
                                  trigger_body("trigger", label="w1"))).ok
        t.execute(tcl.force("/tb/top/u_dut/in_00", "1"))
        t.execute(tcl.run("200 ns"))
        events = t.poll_events()
        assert any(e.kind == "trigger" and e["label"] == "w1" for e in events)
    finally:
        t.close()


def test_session_end_to_end():
    cfg = SRIEConfig.from_dict(
        {"transport": {"kind": "mock"}, "probe": True, "discover_depth": 4,
         "max_forced": 4, "quantum_cycles": 100}
    )
    with SRIESession(cfg) as session:
        assert session.hierarchy is not None
        assert session.hierarchy.inputs()
        snap = session.coverage()
        assert snap.total_bins == 96
        assert len(snap.group_names) == 4
        targets = session.reflection.candidates()
        assert targets, "inputs should be force-eligible"
        assert all("clk" not in t and "rst" not in t for t in targets)
        session.bias("high", paths=targets)
        session.run_quantum(200)
        after = session.coverage()
        assert after.hit_bins >= snap.hit_bins
        assert session.reflection.ledger, "forces must be tracked"
    # closing the session releases everything


def test_reflection_refuses_clock_and_unknown_paths():
    cfg = SRIEConfig.from_dict({"transport": {"kind": "mock"}, "discover_depth": 4})
    with SRIESession(cfg) as session:
        rc = session.reflection
        with pytest.raises(ValueError):
            rc.force("/tb/top/clk", 1)
        with pytest.raises(ValueError):
            rc.force("/tb/top/u_dut/nonexistent", 1)


def test_force_limit_is_enforced():
    t = MockTransport(seed=5)
    t.start()
    try:
        from aiduvo.srie.introspection import Hierarchy

        hier = Hierarchy()
        for i in range(4):
            hier.add(tcl.NodeInfo(path=f"/tb/top/u_dut/in_{i:02d}",
                                  name=f"in_{i:02d}", direction="input", width=1))
        rc = ReflectionController(t, hierarchy=hier, max_forced=2)
        assert len(rc.candidates()) == 4
        rc.apply_bias("high")
        assert len(rc.ledger) == 2
        rc.release_all()
        assert rc.ledger == []
    finally:
        t.close()
