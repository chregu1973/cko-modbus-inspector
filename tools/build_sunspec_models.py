"""Kompakte SunSpec-Modelldatei aus dem offiziellen Repository erzeugen.

Quelle: https://github.com/sunspec/models (Apache-2.0). Aufruf:
  python tools/build_sunspec_models.py <pfad-zu-sunspec-models/json> data/sunspec_models.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

KEEP = ("name", "type", "size", "sf", "units", "label", "count")


def compact_group(group: dict) -> dict:
    out = {"name": group.get("name"), "label": group.get("label"), "count": group.get("count", 1),
           "points": [{key: point[key] for key in KEEP if point.get(key) not in (None, "")} for point in group.get("points", [])]}
    if group.get("groups"):
        out["groups"] = [compact_group(child) for child in group["groups"]]
    return out


def main(source: str, target: str) -> None:
    models = {}
    for path in sorted(Path(source).glob("model_*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        models[str(data["id"])] = compact_group(data["group"])
    payload = {"source": "https://github.com/sunspec/models", "license": "Apache-2.0", "models": models}
    Path(target).write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"{len(models)} Modelle → {target}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
