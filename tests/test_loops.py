"""Tests for the loop scripts (no network, no GPU)."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import bench_loop  # noqa: E402
import final_select as fs  # noqa: E402
import mock_llm_server as mock  # noqa: E402

HDR = "ref,fileName,date,description,status,publicScore,privateScore\n"


def subs(rows):
    return fs.parse(HDR + "".join(f"{r},f,{d},{desc},SubmissionStatus.COMPLETE,{p},\n" for r, d, desc, p in rows))


def test_final_select_newest_healthy_not_max():
    s = subs([("1", "2026-10-24", "E1 m2-robust v1", 25.67), ("2", "2026-10-25", "E2 m2-robust-dprime v1", 25.66),
              ("3", "2026-10-26", "E3 A=robust-v2", 27.31), ("4", "2026-10-27", "E4 B=robust-v2+D'", 28.96),
              ("5", "2026-10-28", "E5 A=robust-v2", 24.0)])
    r = fs.select(s)
    assert r["configs"]["A"]["representative"] == "5"  # newest, although E3 has the higher Public
    assert r["picks"] == ["4", "5"]  # B first, then A
    assert r["compare"]["verdict"] == "差なし"


def test_final_select_drops_broken_runs():
    s = subs([("1", "2026-10-24", "A=robust", 26.0), ("2", "2026-10-25", "A=robust", 27.0),
              ("3", "2026-10-26", "A=robust", 0.0), ("4", "2026-10-27", "A=robust", 12.0),
              ("5", "2026-10-27", "B=robust+D'", 26.0)])
    r = fs.select(s)
    assert {x.ref for x in r["excluded"]} == {"3", "4"}
    assert r["configs"]["A"]["representative"] == "2"


def _bench(name, dec, ready, levels, metric="base", opts=(), games=10, tokens=1):
    return {"name": name, "metric": metric, "opts": list(opts),
            "metrics": {"decode_tok_s_ge8": dec, "ready_after_s": ready, "levels": levels, "games": games,
                        "harness_tokens": tokens}}


def test_bench_decide_rules_and_broken_runs():
    st = {"benches": [_bench("base1", 756.1, 975, 51), _bench("base2", 754.7, 825, 56),
                      _bench("c_precache8", 755.1, 523, 53, "ready", ["precache8"]),
                      _bench("c_spec4", None, None, 0, "decode", ["spec4"], tokens=0)]}
    msgs = bench_loop.decide(st)
    assert st["adopted"] == ["precache8"]
    assert any("実行不良" in m for m in msgs)


def test_bench_decide_rejects_small_gain():
    st = {"benches": [_bench("base1", 600, 1000, 50), _bench("base2", 610, 1000, 50),
                      _bench("c_x", 615, 1000, 50, "decode", ["x"])]}
    bench_loop.decide(st)
    assert st["adopted"] == []


def test_mock_uses_valid_actions():
    tools = [{"type": "function", "function": {"name": "python", "parameters": {
        "type": "object", "properties": {"code": {"type": "string"}}}}}]
    name, args = mock.pick_call(tools, [{"content": "{'valid_actions': ['UP', 'RESET']}"}])
    assert name == "python" and "UP" in args["code"] and "ACTION" not in args["code"]


def test_watchdog_only_in_bench():
    sys.path.insert(0, str(ROOT / "kernels" / "m2_robust"))
    import json
    import build
    for v, want in (("bench10", True), ("robust", False), ("dprime", False)):
        nb = json.loads(build.build(v).read_text())
        has = any("[bench watchdog]" in "".join(c["source"]) for c in nb["cells"])
        assert has == want, v
