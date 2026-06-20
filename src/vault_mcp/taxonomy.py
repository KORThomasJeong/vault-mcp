"""Expose the vault's folder structure and PARA policy so the calling LLM can
choose the right destination folder itself — no classifier needed on the server.
"""

from __future__ import annotations

from pathlib import Path

import yaml

# Short, stable summary of the PARA policy the vault follows. Kept compact on
# purpose: it is guidance for the model, not a spec dump.
PARA_POLICY = """\
PARA buckets (pick the most specific fit):
- 01-Inbox/        new unsorted captures; Daily/ for journal, Web-Clippings/ for URLs
- 10-Projects/     active work with an end date (e.g. Development/, Github-*/)
- 20-Areas/        ongoing responsibilities (People/, Daily-Brain/, Journal/)
- 30-Resources/    reference material, organised by domain (AI/, Development/, Business/, Growth/, General/...)
- docs/            project/engineering docs

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


def _folder_tree(vault_root: Path, max_depth: int = 2) -> list[str]:
    """List visible folders (depth-limited) under the PARA buckets, relative."""
    roots = ["01-Inbox", "10-Projects", "20-Areas", "30-Resources", "docs"]
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
