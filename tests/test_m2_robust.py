"""Tests for kernels/m2_robust/build.py.

The harness-anchor test needs Franzen's patched bundle; point ARC3_BUNDLE_SRC at a checkout of
dfranzen/taaf-kaggle-source-bundle-copy/src with third_party/dfranzen_m2's patch applied
(skipped otherwise).
"""

from __future__ import annotations

import http.server
import importlib.util
import json
import logging
import os
import threading
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("m2_build", ROOT / "kernels" / "m2_robust" / "build.py")
build = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build)


def test_build_edits_and_metadata():
    nb_path = build.build()
    nb = json.loads(nb_path.read_text())
    code = ["".join(c["source"]) for c in nb["cells"]]
    assert "ARC3_KEEPALIVE_SECONDS'] = '240'" in code[4]
    assert "ARC3_HTTP_RETRY_INITIAL_SECONDS'] = '7200'" in code[4]
    assert "m2-robust: keepalive patch applied" in code[4]
    assert "SERVER_STARTUP_TIMEOUT = 90" in code[4]
    assert "timeout_s=1800.0" in code[20]
    # scored-rerun overrides in cell 16 must be untouched
    orig = json.loads(build.SRC_NB.read_text())
    o16 = "".join(orig["cells"][16]["source"])
    rerun_block = o16[o16.index("if TRUE_SUBMISSION:"):o16.index("else:")]
    assert rerun_block in code[16]
    # every other cell byte-identical to the source
    for i, (a, b) in enumerate(zip(orig["cells"], nb["cells"])):
        if i not in (4, 16, 20):
            assert "".join(a["source"]) == "".join(b["source"]), i
    meta = json.loads((nb_path.parent / "kernel-metadata.json").read_text())
    assert meta["is_private"] is True
    assert meta["enable_internet"] is False
    assert meta["machine_shape"] == "NvidiaRtxPro6000"
    assert meta["model_sources"] and meta["dataset_sources"]


@pytest.mark.skipif(not os.environ.get("ARC3_BUNDLE_SRC"), reason="needs patched bundle")
def test_keepalive_anchor_in_patched_solver():
    solver = Path(os.environ["ARC3_BUNDLE_SRC"]) / "ARC3-Inference/inference/framework/solver.py"
    s = solver.read_text()
    assert s.count(build.KEEPALIVE_CALL_ANCHOR) == 1
    new = s.replace(build.KEEPALIVE_CALL_ANCHOR, build.KEEPALIVE_CALL_NEW) + build.KEEPALIVE_FUNC
    compile(new, str(solver), "exec")


class _Health(http.server.BaseHTTPRequestHandler):
    ready_at = 0.0

    def do_GET(self):  # noqa: N802
        self.send_response(200 if time.monotonic() >= _Health.ready_at else 503)
        self.end_headers()

    def log_message(self, *a):
        pass


class _Session:
    def __init__(self):
        self.resets = 0

    def should_stop(self):
        return False

    def _execute_auto_reset(self):
        self.resets += 1


class _Run:
    game_id = "test-game"


def _keepalive_fn():
    ns = {"os": os, "time": time, "log": logging.getLogger("t")}
    exec(build.KEEPALIVE_FUNC, ns)
    return ns["_arc3_keepalive_until_ready"]


def test_keepalive_sends_resets_until_server_healthy(monkeypatch):
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Health)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    _Health.ready_at = time.monotonic() + 1.2
    monkeypatch.setenv("OPENAI_BASE_URL", f"http://127.0.0.1:{srv.server_port}/v1")
    monkeypatch.setenv("ARC3_KEEPALIVE_SECONDS", "0.3")
    monkeypatch.setenv("ARC3_KEEPALIVE_POLL_SECONDS", "0.1")
    sess = _Session()
    t0 = time.monotonic()
    _keepalive_fn()(sess, _Run())
    dt = time.monotonic() - t0
    srv.shutdown()
    assert 1.1 < dt < 3.0
    assert 2 <= sess.resets <= 5


def test_keepalive_returns_immediately_when_ready_or_disabled(monkeypatch):
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Health)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    _Health.ready_at = 0.0
    monkeypatch.setenv("OPENAI_BASE_URL", f"http://127.0.0.1:{srv.server_port}/v1")
    monkeypatch.setenv("ARC3_KEEPALIVE_SECONDS", "0.3")
    sess = _Session()
    _keepalive_fn()(sess, _Run())
    assert sess.resets == 0
    monkeypatch.setenv("ARC3_KEEPALIVE_SECONDS", "0")
    _keepalive_fn()(sess, _Run())
    srv.shutdown()
    assert sess.resets == 0


def test_keepalive_respects_cap_when_server_never_comes(monkeypatch):
    monkeypatch.setenv("OPENAI_BASE_URL", "http://127.0.0.1:9/v1")  # nothing listens
    monkeypatch.setenv("ARC3_KEEPALIVE_SECONDS", "0.2")
    monkeypatch.setenv("ARC3_KEEPALIVE_MAX_SECONDS", "0.7")
    monkeypatch.setenv("ARC3_KEEPALIVE_POLL_SECONDS", "0.1")
    sess = _Session()
    t0 = time.monotonic()
    _keepalive_fn()(sess, _Run())
    assert time.monotonic() - t0 < 2.0
    assert sess.resets >= 2
