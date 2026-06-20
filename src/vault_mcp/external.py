"""Thin wrappers around optional external helper binaries (search / URL save).

Each wrapper degrades gracefully: if the binary is not configured, the tool
returns a clear message instead of crashing, so the server is useful even on a
machine that does not have the vault's companion CLIs installed.
"""

from __future__ import annotations

import json
import shlex
import subprocess

DEFAULT_TIMEOUT = 120


def run(argv: list[str], timeout: int = DEFAULT_TIMEOUT) -> tuple[int, str, str]:
    proc = subprocess.run(
        argv,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return proc.returncode, proc.stdout, proc.stderr


def semantic_search(qmd_bin: str | None, query: str, collection: str, limit: int) -> str:
    if not qmd_bin:
        return "Semantic search is disabled (QMD_BIN not configured)."
    code, out, err = run([qmd_bin, "query", query, "-c", collection, "-n", str(limit)])
    if code != 0:
        return f"Search failed ({code}): {err.strip() or out.strip()}"
    return out.strip() or "(no results)"


def title_search(wiki_query_bin: str | None, text: str, limit: int) -> str:
    if not wiki_query_bin:
        return "Title search is disabled (WIKI_QUERY_BIN not configured)."
    code, out, err = run([wiki_query_bin, "alias", text, "--limit", str(limit)])
    out_s, err_s = out.strip(), err.strip()
    # wiki-query prints "no rows" for an empty result; that is success, not failure.
    if out_s in ("", "no rows"):
        return "(no matches)"
    if code != 0:
        return f"Title search failed ({code}): {err_s or out_s}"
    return out_s


def save_url(save_link_bin: str | None, url: str, folder: str | None) -> dict:
    if not save_link_bin:
        return {"ok": False, "error": "URL save is disabled (SAVE_LINK_BIN not configured)."}
    argv = [save_link_bin, url]
    if folder:
        argv += ["--folder", folder]
    code, out, err = run(argv)
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        return {
            "ok": code == 0,
            "raw_stdout": out.strip(),
            "stderr": err.strip(),
            "returncode": code,
        }


def rebuild_index(cmd: str | None) -> str:
    if not cmd:
        return "Index rebuild skipped (INDEX_REBUILD_CMD not configured)."
    code, out, err = run(shlex.split(cmd), timeout=600)
    if code != 0:
        return f"Index rebuild failed ({code}): {err.strip() or out.strip()}"
    return "Index rebuilt."
