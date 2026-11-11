"""Street context for several cities: builder merges cities, loader picks the right one."""

import gzip
import json
import sys
from pathlib import Path

from app.environment import EnvironmentLayer, MultiCityLayer

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import build_environment as be  # noqa: E402


def _park(lat, lng, name):
    d = 0.003
    ring = [[lat, lng], [lat + d, lng], [lat + d, lng + d], [lat, lng + d], [lat, lng]]
    return {"kind": "green", "name": name, "area_m2": 100000, "rings": [ring]}


def test_builder_keeps_existing_and_adds_missing(tmp_path, monkeypatch):
    out = tmp_path / "env.json.gz"
    # an old version-1 Delhi file
    with gzip.open(out, "wt") as f:
        json.dump({"version": 1, "bbox": [28.2, 76.8, 28.95, 77.75], "areas": [_park(28.6, 77.2, "Lodhi Garden")], "roads": []}, f)
    calls = []

    def fake_build(s, w, n, e, T, ua):
        calls.append((s, w))
        return {"bbox": [s, w, n, e], "areas": [_park(s + 0.1, w + 0.1, "Test Park")], "roads": []}

    monkeypatch.setattr(be, "build_city", fake_build)
    monkeypatch.setattr(sys, "argv", ["x", "--out", str(out), "--cities", "Delhi-NCR,Mumbai"])
    be.main()
    assert calls == [(18.88, 72.77)]  # Delhi reused, only Mumbai fetched
    layer = EnvironmentLayer.load(out)
    assert isinstance(layer, MultiCityLayer) and layer.cities == ["Delhi-NCR", "Mumbai"]
    assert not layer.at((19.0, 72.9)).empty and not layer.at((28.6, 77.2)).empty
    assert layer.at((22.5, 88.3)).empty  # Kolkata not built here
    assert layer.at((28.6, 77.2)).areas[0].name == "Lodhi Garden"
