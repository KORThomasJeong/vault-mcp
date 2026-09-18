"""Thin wrappers around optional external helper binaries (search / URL save).

Each wrapper degrades gracefully: if the binary is not configured, the tool
returns a clear message instead of crashing, so the server is useful even on a
machine that does not have the vault's companion CLIs installed.
"""

from __future__ import annotations

import json
import shlex
import subprocess
from pathlib import Path

DEFAULT_TIMEOUT = 120


def run(argv: list[str], timeout: int = DEFAULT_TIMEOUT) -> tuple[int, str, str]:
    proc = subprocess.run(
        argv,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return proc.returncode, proc.stdout, proc.stderr


def semantic_search(
    jikji_bin: str | None,
    vault_root: Path,
    fast_search_bin: str | None,
    qmd_bin: str | None,
    query: str,
    collection: str,
    limit: int,
    include_wiki: bool = False,
    jikji_auto_prepare: bool = False,
) -> str:
    jikji_error: str | None = None
    if jikji_bin:
        jikji_result, jikji_error = _run_jikji_find(
            jikji_bin, vault_root, query, limit, jikji_auto_prepare
        )
        if jikji_result is not None:
            return jikji_result
    # Prefer a warm fast-search front-end (e.g. a qa-search daemon) if configured;
    # it answers in milliseconds without loading a model per call.
    if fast_search_bin:
        argv = [fast_search_bin, query, "-n", str(limit)]
        # By default, exclude auto-generated Wiki/ synthesis nodes (topic/entity/
        # concept seeds) so results are real content notes rather than second-order
        # summaries. The caller opts back in with include_wiki=True.
        if include_wiki:
            argv.append("--include-wiki")
        code, out, err = run(argv)
        if code != 0:
            return f"Search failed ({code}): {err.strip() or out.strip()}"
        return out.strip() or "(no results)"
    if qmd_bin:
        code, out, err = run([qmd_bin, "query", query, "-c", collection, "-n", str(limit)])
        if code != 0:
            return f"Search failed ({code}): {err.strip() or out.strip()}"
        return out.strip() or "(no results)"
    if jikji_error:
        return jikji_error
    return (
        "Semantic search is disabled (none of JIKJI_BIN, FAST_SEARCH_BIN, or QMD_BIN "
        "configured)."
    )


def _run_jikji_find(
    jikji_bin: str,
    vault_root: Path,
    query: str,
    limit: int,
    auto_prepare: bool,
) -> tuple[str | None, str | None]:
    argv = [
        jikji_bin,
        "find",
        str(vault_root),
        query,
        "--json",
        "--top-k",
        str(limit),
    ]
    if auto_prepare:
        argv.append("--auto-prepare")
    code, out, err = run(argv, timeout=300 if auto_prepare else DEFAULT_TIMEOUT)
    out_s, err_s = out.strip(), err.strip()
    if code == 0:
        try:
            payload = json.loads(out_s)
        except json.JSONDecodeError:
            return out_s or "(no results)", None
        return _format_jikji_find(payload), None

    detail = err_s or out_s or "unknown error"
    missing_index = "No Jikji search index found under" in detail
    if missing_index and not auto_prepare:
        return None, f"Jikji index missing for {vault_root}. Run: jikji prepare {vault_root}"
    return None, f"Jikji search failed ({code}): {detail}"


def _format_jikji_find(payload: dict) -> str:
    lines: list[str] = ["Search backend: Jikji find"]

    index_status = payload.get("index_status")
    if index_status:
        lines.append(f"Index: {index_status}")

    handoff_action = payload.get("handoff_action")
    if handoff_action:
        lines.append(f"Handoff: {handoff_action}")

    answer_paths = payload.get("answer_paths") or payload.get("paths") or []
    if answer_paths:
        lines.append("Answer paths:")
        lines.extend(f"{idx}. {path}" for idx, path in enumerate(answer_paths, start=1))

    candidates = payload.get("candidates") or []
    if candidates:
        lines.append("Candidates:")
        for idx, candidate in enumerate(candidates, start=1):
            path = candidate.get("path") or "(unknown path)"
            extras: list[str] = []
            score = candidate.get("score")
            if score is not None:
                extras.append(f"score={score}")
            route = candidate.get("route") or candidate.get("route_label")
            if route:
                extras.append(str(route))
            next_read = candidate.get("next_read")
            if next_read:
                extras.append(f"next_read={next_read}")
            suffix = f" ({', '.join(extras)})" if extras else ""
            lines.append(f"{idx}. {path}{suffix}")

    if len(lines) == 1:
        return "(no results)"
    return "\n".join(lines)


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
