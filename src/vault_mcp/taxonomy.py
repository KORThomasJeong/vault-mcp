"""Expose the vault's folder structure and PARA policy so the calling LLM can
choose the right destination folder itself — no classifier needed on the server.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

# Top-level folders that are never classification targets even if present.
# 90-Archive is excluded on purpose: it is a terminal store (종료·폐기), not a
# destination for new notes.
_ROOT_EXCLUDE = {"attachments", "Wiki", "90-Archive"}
# PARA buckets follow an ``NN-`` numeric prefix (00-, 01-, 10-, 40-, 90- ...).
_PARA_ROOT = re.compile(r"^\d{2}-")

# Short, stable summary of the PARA policy the vault follows. Kept compact on
# purpose: it is guidance for the model, not a spec dump.
PARA_POLICY = """\
PARA buckets (pick the most specific fit):
- 01-Inbox/        new unsorted captures; Daily/ for journal, Web-Clippings/ for URLs
- 10-Projects/     active work with an end date (e.g. Development/, Github-*/)
- 20-Areas/        ongoing responsibilities (People/, Daily-Brain/, Journal/)
- 30-Resources/    reference material, organised by domain (AI/, Development/, Business/, Growth/, General/...)
- 40-프롬프트/      reusable prompts / prompt engineering assets
- 00-System/, 02-Todo/, 03-Staging/  system, dashboards, HIL staging (rarely a save target)
- docs/            project/engineering docs

The full folder list below is scanned live from disk: every top-level NN-* bucket
is discovered automatically, so new buckets appear without a code change. Prefer a
folder from that list. (90-Archive/, attachments/, Wiki/ are intentionally excluded
as destinations.)

Rules:
- Never write a .md file to the vault root.
- 30-Resources/AI/ and 30-Resources/Development/ have subcategory whitelists (below);
  prefer an existing subcategory, fall back to its General/.
- If unsure, put it in 01-Inbox/ and the nightly classifier will sort it.
"""


def _load_whitelist(vault_root: Path, rel: str) -> dict | None:
    path = vault_root / rel
    if not path.is_file():
        return None
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    cats = data.get("categories", {})
    simplified = {
        name: (meta or {}).get("description", "")
        for name, meta in cats.items()
        if isinstance(cats, dict)
    }
    return {"categories": simplified, "fallback": data.get("fallback")}


def _discover_roots(vault_root: Path) -> list[str]:
    """Discover PARA bucket folders from disk: any top-level ``NN-*`` dir plus
    ``docs``. Beats a hardcoded list — new buckets (e.g. 40-프롬프트, 50-*) are
    picked up automatically."""
    roots: list[str] = []
    for child in sorted(vault_root.iterdir()):
        if not child.is_dir():
            continue
        name = child.name
        if name.startswith(".") or name in _ROOT_EXCLUDE:
            continue
        if _PARA_ROOT.match(name) or name == "docs":
            roots.append(name)
    return roots


def _folder_tree(vault_root: Path, max_depth: int = 2) -> list[str]:
    """List visible folders (depth-limited) under the PARA buckets, relative."""
    roots = _discover_roots(vault_root)
    out: list[str] = []
    for root in roots:
        base = vault_root / root
        if not base.is_dir():
            continue
        out.append(root + "/")
        for child in sorted(base.rglob("*")):
            if not child.is_dir():
                continue
            rel = child.relative_to(vault_root)
            if any(part.startswith(".") for part in rel.parts):
                continue
            if len(rel.parts) > max_depth:
                continue
            out.append(str(rel) + "/")
    return out


def build_taxonomy(vault_root: Path) -> dict:
    return {
        "policy": PARA_POLICY,
        "folders": _folder_tree(vault_root),
        "whitelists": {
            "30-Resources/AI": _load_whitelist(
                vault_root, "30-Resources/AI/_whitelist.yaml"
            ),
            "30-Resources/Development": _load_whitelist(
                vault_root, "30-Resources/Development/_whitelist.yaml"
            ),
        },
    }
