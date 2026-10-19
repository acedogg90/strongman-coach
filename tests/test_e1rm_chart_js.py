"""Runs the real JavaScript tests for frontend/static/js/e1rm-chart.js with Node's built-in runner."""
import pathlib
import shutil
import subprocess

JS_TEST = pathlib.Path(__file__).parent / "js" / "e1rm-chart.test.js"


def test_e1rm_chart_js_suite():
    node = shutil.which("node")
    assert node, "Node.js >= 18 is required to run the frontend tests (it is not on PATH)"
    r = subprocess.run([node, "--test", str(JS_TEST)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, (r.stdout[-3000:] + r.stderr[-1500:])
