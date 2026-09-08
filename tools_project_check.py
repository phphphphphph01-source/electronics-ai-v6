"""Static project smoke check.

Run from the project root:
    python tools_project_check.py

This check intentionally does not start Flask or load AI weights.
"""
from pathlib import Path
import ast
import json
import shutil
import subprocess
import sys

BASE = Path(__file__).resolve().parent
REQUIRED = [
    "app.py", "dataset.yaml", "details.json", "requirements.txt",
    "templates/index.html", "static/app.js", "static/app.css",
    "custom_dataset/images/train", "custom_dataset/images/val",
    "custom_dataset/labels/train", "custom_dataset/labels/val",
]


def main():
    failures = []
    for rel in REQUIRED:
        if not (BASE / rel).exists():
            failures.append(f"missing: {rel}")

    for path in BASE.rglob("*.py"):
        try:
            ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError as exc:
            failures.append(f"python syntax: {path.relative_to(BASE)}: {exc}")

    node = shutil.which("node")
    if node:
        for rel in ["static/app.js", "static/sw.js"]:
            proc = subprocess.run([node, "--check", str(BASE / rel)], capture_output=True, text=True)
            if proc.returncode:
                failures.append(f"javascript syntax: {rel}: {proc.stderr.strip()}")

    try:
        import yaml
        cfg = yaml.safe_load((BASE / "dataset.yaml").read_text(encoding="utf-8")) or {}
        names = cfg.get("names", {}) or {}
        if len(names) != 62:
            failures.append(f"dataset class count is {len(names)}, expected 62 for the current model")
    except Exception as exc:
        failures.append(f"dataset yaml check: {exc}")

    try:
        json.loads((BASE / "details.json").read_text(encoding="utf-8"))
    except Exception as exc:
        failures.append(f"details.json invalid: {exc}")

    if failures:
        print("\n".join(f"[FAIL] {x}" for x in failures))
        return 1
    print("[PASS] Project static smoke checks completed.")
    print("[INFO] AI inference was not executed; install requirements and run the app for integration testing.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
