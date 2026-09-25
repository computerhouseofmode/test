import json
import threading
import urllib.error
import urllib.request

import pytest

from opteval.web import api
from opteval.web.server import make_server


@pytest.fixture(scope="module")
def base_url():
    httpd = make_server("127.0.0.1", 0)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()
    httpd.server_close()


def get(url):
    with urllib.request.urlopen(url) as r:
        return r.status, r.headers.get("Content-Type"), r.read()


def post(url, payload):
    req = urllib.request.Request(url, json.dumps(payload).encode(), {"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, r.headers.get("Content-Type"), r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.headers.get("Content-Type"), e.read()


def test_static_and_lists(base_url):
    st, ct, body = get(base_url + "/")
    assert st == 200 and ct.startswith("text/html") and b"opteval" in body
    for f in ("app.js", "style.css"):
        assert get(f"{base_url}/static/{f}")[0] == 200
    ids = [e["id"] for e in json.loads(get(base_url + "/api/examples")[2])]
    assert "cooke_triplet" in ids
    glasses = json.loads(get(base_url + "/api/glasses")[2])
    assert any(g["name"] == "N-BK7" and abs(g["nd"] - 1.5168) < 1e-4 for g in glasses)


def test_path_traversal_blocked(base_url):
    for path in ("/static/../server.py", "/static/%2e%2e/api.py", "/api/examples/..%2Fsetup"):
        with pytest.raises(urllib.error.HTTPError) as e:
            get(base_url + path)
        assert e.value.code in (400, 404)


def test_analyze_summary_and_figures(base_url):
    lens = api.example("cooke_triplet")
    st, _, body = post(base_url + "/api/analyze", {"lens": lens, "analysis": "summary"})
    s = json.loads(body)
    assert st == 200
    assert abs(s["efl"] - 50.0214) < 1e-3
    assert len(s["surfaces"]) == len(lens["surfaces"])
    for kind in api.FIGURES:
        st, _, body = post(base_url + "/api/analyze", {"lens": lens, "analysis": kind})
        assert st == 200, kind
        assert json.loads(body)["image"].startswith("iVBOR")   # PNG


def test_errors_are_400_with_message(base_url):
    lens = api.example("cooke_triplet")
    lens["surfaces"][1]["material"] = "NOPE"
    st, _, body = post(base_url + "/api/analyze", {"lens": lens})
    assert st == 400
    assert json.loads(body)["error"] == "計算できません: 未知の硝材です: NOPE"
    st, _, body = post(base_url + "/api/analyze", {"lens": {"surfaces": []}})
    assert st == 400
    st, _, _ = post(base_url + "/api/analyze", {"lens": api.example("cooke_triplet"), "analysis": "nope"})
    assert st == 400


def test_optimize_and_report(base_url):
    lens = api.example("doublet_start")
    st, _, body = post(base_url + "/api/optimize", {"lens": lens, "config": lens["optimization"]})
    r = json.loads(body)
    assert st == 200
    assert r["merit_history"][-1] < 1e-3 * r["merit_history"][0]
    assert r["lens"]["optimization"] == lens["optimization"]
    st, ct, body = post(base_url + "/api/report", {"lens": r["lens"]})
    assert st == 200 and ct.startswith("text/html") and b"data:image/png;base64" in body
