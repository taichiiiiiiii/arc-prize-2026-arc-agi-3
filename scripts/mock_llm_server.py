"""Minimal OpenAI-compatible stand-in for the SGLang server (local smoke tests only).

- /health and /v1/* answer 503 until --ready-after seconds have passed (exercises the
  keepalive / first-request grace path like the real 15-50 min model load).
- /v1/chat/completions answers every request with one tool call. The tool and its arguments
  are picked from the request's `tools` schema (see `pick_call`), so the harness actually
  plays actions in the real game engine.
- Every request is appended to --log as one JSON line (messages trimmed) for inspection.

Usage: python scripts/mock_llm_server.py --port 8001 --ready-after 120 --log work/smoke/mock.jsonl
"""

from __future__ import annotations

import argparse
import itertools
import json
import random
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

START = time.time()
ARGS: argparse.Namespace
COUNTER = itertools.count()
RNG = random.Random(0)
ACTIONS = ["ACTION1", "ACTION2", "ACTION3", "ACTION4", "ACTION5"]


def sample(schema: dict, name: str = ""):
    t = schema.get("type")
    if "enum" in schema:
        return RNG.choice(schema["enum"])
    if t == "integer" or t == "number":
        lo, hi = schema.get("minimum", 0), schema.get("maximum", 63)
        return RNG.randint(int(lo), int(min(hi, 63)))
    if t == "boolean":
        return False
    if t == "array":
        return [sample(schema.get("items", {}), name)]
    if t == "object":
        props = schema.get("properties", {})
        req = schema.get("required", list(props))
        return {k: sample(props[k], k) for k in req if k in props}
    return RNG.choice(ACTIONS) if "action" in name.lower() else "x"


VALID = __import__("re").compile(r"valid_actions['\"]?:\s*\[([^\]]*)\]")


def valid_actions(messages: list[dict]) -> list[str]:
    """Action names the game currently accepts, read from the newest tool output that lists them."""
    for m in reversed(messages or []):
        hit = VALID.findall(str(m.get("content")))
        if hit:
            names = [x.strip().strip("'\"") for x in hit[-1].split(",") if x.strip()]
            names = [n for n in names if n and n not in ("RESET", "MOUSE", "CLICK")]
            if names:
                return names
    return ACTIONS


def pick_call(tools: list[dict], messages: list[dict] | None = None) -> tuple[str, dict]:
    """Prefer a python/code tool (send a few real actions), else any action-like tool."""
    acts_pool = valid_actions(messages or [])
    fns = [t.get("function", t) for t in tools or []]
    names = [f.get("name", "") for f in fns]
    for f in fns:
        props = (f.get("parameters") or {}).get("properties", {})
        code_key = next((k for k in props if k in ("code", "source", "python")), None)
        if code_key:
            acts = ", ".join(repr(RNG.choice(acts_pool)) for _ in range(3))
            return f["name"], {code_key: f"print(action([{acts}]))"}
    for f in fns:
        if "action" in f.get("name", "").lower():
            return f["name"], sample(f.get("parameters") or {"type": "object"})
    if fns:
        return fns[0]["name"], sample(fns[0].get("parameters") or {"type": "object"})
    raise ValueError(f"no tools in request: {names}")


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):  # quiet
        pass

    def ready(self) -> bool:
        return time.time() - START >= ARGS.ready_after

    def send(self, code: int, body: dict | str, ctype: str = "application/json") -> None:
        data = body if isinstance(body, str) else json.dumps(body)
        raw = data.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):  # noqa: N802
        if not self.ready():
            return self.send(503, {"error": "loading"})
        if self.path.startswith("/health"):
            return self.send(200, {"ok": True})
        if self.path.startswith("/v1/models"):
            return self.send(200, {"data": [{"id": ARGS.model, "object": "model"}]})
        return self.send(404, {"error": self.path})

    def do_POST(self):  # noqa: N802
        n = int(self.headers.get("Content-Length", 0))
        req = json.loads(self.rfile.read(n) or b"{}")
        if not self.ready():
            return self.send(503, {"error": "loading"})
        if not self.path.endswith("/chat/completions"):
            return self.send(404, {"error": self.path})
        i = next(COUNTER)
        try:
            name, args = pick_call(req.get("tools") or [], req.get("messages"))
            err = None
        except Exception as e:  # noqa: BLE001
            name, args, err = None, None, repr(e)
        with open(ARGS.log, "a") as f:
            f.write(json.dumps({
                "i": i, "t": round(time.time() - START, 1), "stream": req.get("stream"),
                "keys": sorted(req), "n_messages": len(req.get("messages") or []),
                "tool_names": [t.get("function", t).get("name") for t in req.get("tools") or []],
                "tools": req.get("tools") if i == 0 else None,
                "first_system": (req.get("messages") or [{}])[0].get("content") if i == 0 else None,
                "last_message": str((req.get("messages") or [{}])[-1].get("content"))[-1500:],
                "reply": [name, args], "error": err}, ensure_ascii=False) + "\n")
        msg = {"role": "assistant", "content": "", "reasoning_content": "mock: trying actions"}
        finish = "stop"
        if name:
            msg["tool_calls"] = [{"id": f"call_{i}", "type": "function",
                                  "function": {"name": name, "arguments": json.dumps(args)}}]
            finish = "tool_calls"
        usage = {"prompt_tokens": 1000, "completion_tokens": 50, "total_tokens": 1050,
                 "prompt_tokens_details": {"cached_tokens": 900}}
        if not req.get("stream"):
            return self.send(200, {"id": f"mock-{i}", "object": "chat.completion", "model": ARGS.model,
                                   "choices": [{"index": 0, "message": msg, "finish_reason": finish}],
                                   "usage": usage})
        delta = dict(msg)
        if "tool_calls" in delta:
            delta["tool_calls"] = [dict(tc, index=0) for tc in delta["tool_calls"]]
        chunks = [{"choices": [{"index": 0, "delta": delta, "finish_reason": None}]},
                  {"choices": [{"index": 0, "delta": {}, "finish_reason": finish}], "usage": usage}]
        body = "".join(f"data: {json.dumps(dict(c, id=f'mock-{i}', object='chat.completion.chunk'))}\n\n"
                       for c in chunks) + "data: [DONE]\n\n"
        return self.send(200, body, "text/event-stream")


def main() -> None:
    global ARGS
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8001)
    ap.add_argument("--ready-after", type=float, default=0.0)
    ap.add_argument("--log", default="mock.jsonl")
    ap.add_argument("--model", default="flashnext")
    ARGS = ap.parse_args()
    ThreadingHTTPServer(("127.0.0.1", ARGS.port), H).serve_forever()


if __name__ == "__main__":
    main()
