"""persistvars: snippet variables survive between python tool calls (only safe, small JSON values).

Builds a patched harness the same way the notebook does (Franzen's patch from cell 2 applied to a
copy of data/bundle), applies the PERSISTVARS cell code and calls the real sandbox twice.
"""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "kernels" / "m2_robust"))
import build  # noqa: E402

BUNDLE = ROOT / "data" / "bundle"


@pytest.fixture(scope="module")
def sandbox(tmp_path_factory):
    if not (BUNDLE / "src").exists():
        pytest.skip("data/bundle missing")
    tmp = tmp_path_factory.mktemp("pv")
    shutil.copytree(BUNDLE / "src", tmp / "src")
    cell2 = "".join(json.loads(build.SRC_NB.read_text())["cells"][2]["source"])
    body = cell2.split("\n", 1)[1]
    (tmp / "harness.patch").write_text(body if body.endswith("\n") else body + "\n")
    env = dict(os.environ, GIT_CEILING_DIRECTORIES=str(tmp))
    subprocess.run(["git", "apply", "--include=ARC3-Inference/*", str(tmp / "harness.patch")],
                   cwd=tmp / "src", check=True, env=env)
    ns = {"BUNDLE_DIR": tmp, "os": os}
    exec(build.PERSISTVARS, ns)
    saved = {k: sys.modules.pop(k) for k in list(sys.modules) if k == "inference" or k.startswith("inference.")}
    sys.path[:0] = [str(tmp / "src" / "ARC3-Inference"), str(tmp / "src" / "tufa-arc-agi-framework" / "src")]
    from inference.agent.python_tool_sandbox import run_sandboxed_python
    yield run_sandboxed_python
    os.environ.pop("ARC3_PERSIST_VARS", None)
    for k in [k for k in sys.modules if k == "inference" or k.startswith("inference.")]:
        sys.modules.pop(k)
    sys.modules.update(saved)


def _run(fn, code, kept):
    return fn(code=code, timeout_seconds=10, initial_state={}, action_handler=lambda *a, **k: {},
              kept_functions=[], kept_variables=kept)


def test_variables_survive_and_unsafe_values_are_dropped(sandbox):
    code = ("x = 5\nplan = ['UP', 'LEFT']\nd = {1: 'a'}\nt = (1, 2)\n"
            "board = '\\n'.join(['....'] * 20)\nok = {'a': [1, 2.5, None, True]}\nimport math")
    r1 = _run(sandbox, code, {})
    assert sorted(r1["kept_variables"]) == ["ok", "plan", "x"]
    r2 = _run(sandbox, "print(x, plan, ok)", r1["kept_variables"])
    assert r2["stdout"].strip() == "5 ['UP', 'LEFT'] {'a': [1, 2.5, None, True]}" and not r2["error"]


def test_disabled_keeps_nothing(sandbox):
    r = _run(sandbox, "print(x)", None)
    assert "NameError" in r["error"]
