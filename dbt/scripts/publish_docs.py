"""Publish the dbt docs as one static page for GitHub Pages: docs/dbt/index.html.

`dbt docs generate --static` writes dbt/target/static_index.html, which embeds the manifest and catalog. Those
carry machine details: root_path is the absolute project folder, and file paths use the build machine's
separators. This script rebuilds the same static page from dbt/target/index.html, manifest.json and
catalog.json with those details scrubbed:

  root_path                                   -> "" (absolute folder of the machine that built the docs)
  path, original_file_path, patch_path, ...   -> forward slashes, relative as dbt records them
  metadata.env, metadata.user_id              -> empty; usage statistics stay off (no tracking call)

The page is otherwise dbt's own; the one literal em dash in dbt's bundled JavaScript is written as \\u2014.

It then refuses to write the page if any absolute path, home folder or the current user's name is left.

Run from the project root after `dbt docs generate` (see README Path C):
    python dbt/scripts/publish_docs.py
"""
from __future__ import annotations

import getpass
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TARGET = ROOT / "dbt" / "target"
OUT = ROOT / "docs" / "dbt" / "index.html"
PATH_KEYS = {"path", "original_file_path", "patch_path", "compiled_path", "build_path"}
# absolute Windows paths (C:\ or C:/ as JSON text), home and volume folders (Windows, Linux, macOS), and any
# non-empty root_path
LEAKS = [re.compile(r"\b[A-Za-z]:(\\\\|/)(?!/)"), re.compile(r"[\\/](Users|home|Volumes)[\\/]", re.I),
         re.compile(r'"root_path":\s*"[^"]')]


def scrub(node):
    if isinstance(node, dict):
        out = {}
        for k, v in node.items():
            if k == "root_path":
                out[k] = ""
            elif k in PATH_KEYS and isinstance(v, str):
                out[k] = v.replace("\\", "/")
            else:
                out[k] = scrub(v)
        return out
    if isinstance(node, list):
        return [scrub(v) for v in node]
    return node


def embedded(path: Path) -> str:
    data = scrub(json.loads(path.read_text(encoding="utf-8")))
    data["metadata"]["env"] = {}
    if "user_id" in data["metadata"]:
        data["metadata"]["user_id"] = None
    if data["metadata"].get("send_anonymous_usage_stats"):
        raise SystemExit("manifest has usage statistics switched on; the page would send tracking events")
    # compact JSON; "</" is escaped so no string can close the page's <script> element
    return json.dumps(data, separators=(",", ":"), ensure_ascii=False).replace("</", "<\\/")


def leaks(text: str) -> list[str]:
    found = [m.group(0) for rx in LEAKS for m in rx.finditer(text)]
    user = getpass.getuser()
    if len(user) >= 3 and user.lower() in text.lower():
        found.append("the current user name")
    return found


def publish(target: Path = TARGET, out: Path = OUT) -> Path:
    """Write the scrubbed page to out; raise SystemExit with one instruction if anything is missing or left.
    The page is written to a temporary file first and then moved into place, so a refused or interrupted
    run never leaves a partial page and never replaces the previous one."""
    needed = [target / name for name in ("index.html", "manifest.json", "catalog.json")]
    missing = [p.name for p in needed if not p.is_file()]
    if missing:
        raise SystemExit(f"dbt docs have not been generated (missing {', '.join(missing)} in {target.name}/). "
                         "In the dbt folder run: dbt docs generate --profiles-dir . --static, then run this script again.")
    page = needed[0].read_text(encoding="utf-8")
    for marker in ('"MANIFEST.JSON INLINE DATA"', '"CATALOG.JSON INLINE DATA"'):
        if page.count(marker) != 1:
            raise SystemExit(f"{target.name}/index.html is not dbt's docs page ({marker} not found once). "
                             "Run dbt docs generate --profiles-dir . --static again.")
    try:
        manifest, catalog = embedded(needed[1]), embedded(needed[2])
    except (ValueError, KeyError) as err:
        raise SystemExit(f"{target.name}/manifest.json or catalog.json is incomplete ({err.__class__.__name__}). "
                         "Run dbt docs generate --profiles-dir . --static again.") from None
    found = leaks(manifest) + leaks(catalog)
    if found:
        raise SystemExit(f"not published, machine details left: {sorted(set(found))[:10]}")
    # dbt's bundled markdown library holds one em dash inside a JavaScript string; the escape is equivalent
    page = page.replace(chr(0x2014), "\\" + "u2014")
    page = page.replace('"MANIFEST.JSON INLINE DATA"', manifest).replace('"CATALOG.JSON INLINE DATA"', catalog)
    out.parent.mkdir(parents=True, exist_ok=True)
    partial = out.with_name(out.name + ".partial")
    partial.write_bytes(page.encode("utf-8"))
    os.replace(partial, out)
    return out


def main() -> int:
    out = publish()
    print(f"wrote {out.relative_to(ROOT).as_posix()} ({out.stat().st_size / 1e6:.1f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
