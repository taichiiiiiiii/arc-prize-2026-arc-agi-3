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


def test_final_select_top2_public_among_healthy():
    s = subs([("1", "2026-10-24", "E1 m2-robust v1", 25.67), ("2", "2026-10-25", "E2 m2-robust-dprime v1", 25.66),
              ("3", "2026-10-26", "E3 A=robust-v2", 27.31), ("4", "2026-10-27", "E4 B=robust-v2+D'", 28.96),
              ("5", "2026-10-28", "E5 A=robust-v2", 24.0)])
    r = fs.select(s)
    assert r["picks"] == ["4", "3"]  # top-2 Public (rules 2/5 revised 2026-10-28)
    assert r["compare"]["verdict"] == "差なし"


def test_final_select_drops_broken_runs():
    s = subs([("1", "2026-10-24", "A=robust", 26.0), ("2", "2026-10-25", "A=robust", 27.0),
              ("3", "2026-10-26", "A=robust", 0.0), ("4", "2026-10-27", "A=robust", 12.0),
              ("5", "2026-10-27", "B=robust+D'", 26.0)])
    r = fs.select(s)
    assert {x.ref for x in r["excluded"]} == {"3", "4"}
    assert r["picks"] == ["2", "1"] or r["picks"] == ["2", "5"]


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


def test_bench_decide_fp8ple_ready_or_decode():
    st = {"benches": [_bench("base1", 756.1, 975, 51), _bench("base2", 754.7, 825, 56),
                      _bench("c_precache8", 755.1, 523, 53, "ready", ["precache8"]),
                      dict(_bench("c_fp8ple", 756.0, 150, 54, "decode_or_ready", ["precache8", "fp8ple"]), ref="c_precache8")]}
    bench_loop.decide(st)
    assert st["adopted"] == ["fp8ple", "precache8"]
    st["benches"][3]["metrics"]["ready_after_s"] = 500
    bench_loop.decide(st)
    assert st["adopted"] == ["precache8"]


def test_build_fp8ple_swaps_model():
    sys.path.insert(0, str(ROOT / "kernels" / "m2_robust"))
    import json
    import build
    out = build.build("robust", ("precache8", "fp8ple"), "smoke-test-fp8")
    meta = json.loads((out.parent / "kernel-metadata.json").read_text())
    assert any("fp8ple" in m for m in meta["model_sources"]) and not any("autoround" in m for m in meta["model_sources"])
    src = "".join("".join(c["source"]) for c in json.loads(out.read_text())["cells"])
    assert "albucino-qwen3.8-flash-next-w4a16-fp8ple/transformers/default/1" in src and "'threads': 8}" in src


def test_swap_queue_by_tag(tmp_path):
    import json
    q = {"queue": [{"tag": "E9", "config": "A=robust-v2", "kernel": "k/a", "version": 2, "markers": ["m"]},
                   {"tag": "E10", "config": "B=robust-v2+D'", "kernel": "k/b", "version": 1, "markers": ["m", "d"], "verify": "ok"}]}
    f = tmp_path / "q.json"
    f.write_text(json.dumps(q))
    old = bench_loop.QUEUE
    bench_loop.QUEUE = f
    try:
        assert bench_loop.swap_queue("A=", "arc3-m2-robust-opt", 1, []) == 1  # promotion order: A-opt first
        assert bench_loop.swap_queue("E10", "arc3-m2-robust-pv", 3, ["persistvars patch applied"]) == 1
    finally:
        bench_loop.QUEUE = old
    r = json.loads(f.read_text())["queue"]
    assert r[0]["kernel"] == "taichiiiii/arc3-m2-robust-opt"
    assert r[1]["kernel"] == "taichiiiii/arc3-m2-robust-pv" and r[1]["config"].startswith("A=") and "verify" not in r[1]
    assert "persistvars patch applied" in r[1]["markers"] and "PRIORITY_FORM installed: form=dprime" not in r[1]["markers"]


def test_auth_blip_does_not_fail_bench_or_promotion(tmp_path, monkeypatch):
    import json
    st = {"benches": [{"name": "base1", "status": "running", "slug": "b", "opts": [], "metric": "base"}],
          "adopted": ["precache8"], "decided": True,
          "promote": [{"variant": "robust", "slug": "arc3-m2-robust-pv", "config": "E10", "status": "pending",
                       "extra_opts": ["persistvars"], "markers": []}]}
    sf, qf = tmp_path / "s.json", tmp_path / "q.json"
    sf.write_text(json.dumps(st))
    qf.write_text(json.dumps({"queue": []}))
    monkeypatch.setattr(bench_loop, "STATE", sf)
    monkeypatch.setattr(bench_loop, "QUEUE", qf)
    smoke = tmp_path / "smoke"
    smoke.mkdir()
    (smoke / "robust-persistvars-precache8.json").write_text(json.dumps({"ok": True, "opts": ["persistvars", "precache8"]}))
    monkeypatch.setattr(bench_loop, "ROOT", tmp_path.parent / tmp_path.name)
    (tmp_path / "analysis").mkdir()
    (tmp_path / "analysis" / "smoke").symlink_to(smoke)
    auth = "401 Client Error: Unauthorized. Authentication failed"
    monkeypatch.setattr(bench_loop.loop_tick, "kaggle", lambda *a, **k: "ok" if a[0] == "competitions" else auth)
    monkeypatch.setattr(bench_loop, "push", lambda *a, **k: auth)
    bench_loop.main()
    r = json.loads(sf.read_text())
    assert r["benches"][0]["status"] == "running"
    assert r["promote"][0]["status"] == "pending" and r["promote"][0].get("push_tries", 0) == 0


def test_paired_eval_detects_shift():
    import paired_eval as pe
    base = [{g: v for g, v in zip("abcdefgh", [10, 20, 30, 40, 50, 60, 70, 80])},
            {g: v + 1 for g, v in zip("abcdefgh", [10, 20, 30, 40, 50, 60, 70, 80])}]
    cand = [{g: v + 10 + (i % 2) for i, (g, v) in enumerate(zip("abcdefgh", [10, 20, 30, 40, 50, 60, 70, 80]))}]
    r = pe.compare(base, cand)
    assert r["verdict"] == "改善" and 9 < r["diff"] < 11
    assert pe.runs_needed(10.0, 10, 3.0) == 5
