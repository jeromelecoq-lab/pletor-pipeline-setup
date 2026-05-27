#!/usr/bin/env python3
"""Multipart upload helper for Pletor: local file(s) → asset_id(s).

Idempotent: reads `--map` (a JSON file with shape `{"packshots": {rel-path: asset_id}}`),
uploads any file in `--inputs` not yet in the map, updates the map atomically, and
prints a final JSON summary on stdout for the calling skill to parse.

Why this script: the Pletor MCP server has no working op for `local file → asset_id`
without a human drag-drop. REST `POST /assets/upload/` is the only path.
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
import sys
from pathlib import Path

import requests

API_BASE = "https://api.pletor.ai/api/public/v1"
SUPPORTED_EXT = (".png", ".jpg", ".jpeg", ".webp")


def headers() -> dict[str, str]:
    api_key = os.environ.get("PLETOR_API_KEY", "").strip()
    if not api_key:
        sys.exit("error: PLETOR_API_KEY not set in environment")
    return {"X-Api-Key": api_key}


def upload_one(path: Path) -> str:
    mime, _ = mimetypes.guess_type(path.name)
    mime = mime or "application/octet-stream"
    with path.open("rb") as fh:
        r = requests.post(
            f"{API_BASE}/assets/upload/",
            headers=headers(),
            files={"file": (path.name, fh, mime)},
            timeout=120,
        )
    r.raise_for_status()
    body = r.json()
    asset_id = body.get("id") or body.get("asset_id")
    if not asset_id:
        raise RuntimeError(f"upload response missing id: {body!r}")
    return asset_id


def load_map(map_path: Path) -> dict:
    if map_path.exists():
        try:
            data = json.loads(map_path.read_text())
        except json.JSONDecodeError as e:
            sys.exit(f"error: {map_path} is not valid JSON: {e}")
        if not isinstance(data, dict):
            sys.exit(f"error: {map_path} root must be a JSON object, got {type(data).__name__}")
        if "packshots" not in data:
            data["packshots"] = {}
        elif not isinstance(data["packshots"], dict):
            sys.exit(f"error: {map_path} 'packshots' must be a JSON object")
        return data
    return {"packshots": {}}


def save_map(map_path: Path, data: dict) -> None:
    map_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = map_path.with_suffix(map_path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True))
    tmp.replace(map_path)


def discover_packshots(inputs_dir: Path) -> list[Path]:
    if not inputs_dir.is_dir():
        sys.exit(f"error: inputs dir not found: {inputs_dir}")
    return sorted(
        p for p in inputs_dir.iterdir()
        if p.is_file() and p.suffix.lower() in SUPPORTED_EXT and not p.name.startswith(".")
    )


def main() -> None:
    ap = argparse.ArgumentParser(description="Upload local packshots to Pletor; idempotent via local map.")
    ap.add_argument("--inputs", required=True, type=Path, help="Folder containing packshots.")
    ap.add_argument("--map", required=True, type=Path, help="Path to fashion_asset_map.json (created if missing).")
    ap.add_argument("--base", type=Path, default=None, help="Base dir used to compute relative paths (default: parent of --inputs).")
    args = ap.parse_args()

    inputs_dir: Path = args.inputs.resolve()
    map_path: Path = args.map.resolve()
    base_dir: Path = (args.base or inputs_dir.parent).resolve()

    try:
        inputs_dir.relative_to(base_dir)
    except ValueError:
        sys.exit(f"error: --inputs ({inputs_dir}) must be inside --base ({base_dir})")

    amap = load_map(map_path)
    packshots = discover_packshots(inputs_dir)

    summary = {"found": len(packshots), "uploaded": 0, "already_cached": 0, "errors": 0, "packshots": {}}

    for p in packshots:
        rel = str(p.relative_to(base_dir))
        existing = amap["packshots"].get(rel)
        if existing:
            summary["already_cached"] += 1
            summary["packshots"][rel] = existing
            continue
        try:
            asset_id = upload_one(p)
            amap["packshots"][rel] = asset_id
            save_map(map_path, amap)
            summary["uploaded"] += 1
            summary["packshots"][rel] = asset_id
            print(f"uploaded: {rel} -> {asset_id}", file=sys.stderr)
        except Exception as e:
            summary["errors"] += 1
            print(f"error uploading {rel}: {e}", file=sys.stderr)

    print(json.dumps(summary, indent=2))
    sys.exit(1 if summary["errors"] else 0)


if __name__ == "__main__":
    main()
