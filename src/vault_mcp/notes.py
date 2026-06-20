"""Read and write note files. Pure filesystem logic, no MCP coupling, so it can
be unit-tested directly.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import yaml

from .guards import GuardError, VaultGuard

MAX_READ_BYTES = 512_000  # guard against accidentally returning a giant file


def read_note(guard: VaultGuard, rel: str) -> dict:
    path = guard.check_readable(rel)
    if not path.is_file():
        raise GuardError(f"Not a file: {rel}")
    size = path.stat().st_size
    if size > MAX_READ_BYTES:
        raise GuardError(
            f"File is {size} bytes (> {MAX_READ_BYTES}); too large to return."
        )
    return {
        "path": guard.rel_posix(rel),
        "content": path.read_text(encoding="utf-8"),
    }


def _render_frontmatter(fm: dict) -> str:
    body = yaml.safe_dump(fm, allow_unicode=True, sort_keys=False).strip()
    return f"---\n{body}\n---\n\n"


def write_note(
    guard: VaultGuard,
    folder: str,
    filename: str,
    content: str,
    mode: str = "create",
    frontmatter: dict | None = None,
    now: datetime | None = None,
) -> dict:
    if mode not in ("create", "overwrite", "append"):
        raise GuardError(f"Invalid mode: {mode!r}")
    if "/" in filename or filename in ("", ".", ".."):
        raise GuardError(f"Invalid filename: {filename!r}")
    if not filename.endswith(".md"):
        filename += ".md"

    rel = f"{folder.rstrip('/')}/{filename}"
    path = guard.check_writable(rel)

    exists = path.exists()
    if mode == "create" and exists:
        raise GuardError(
            f"{guard.rel_posix(rel)} already exists. Use mode='overwrite' or "
            "mode='append' to change it."
        )

    if mode == "append":
        if not exists:
            raise GuardError(f"Cannot append: {guard.rel_posix(rel)} does not exist.")
        with path.open("a", encoding="utf-8") as fh:
            if content and not content.startswith("\n"):
                fh.write("\n")
            fh.write(content)
            if not content.endswith("\n"):
                fh.write("\n")
        return {"path": guard.rel_posix(rel), "mode": mode, "created": False}

    # create / overwrite
    stamp = (now or datetime.now(timezone.utc)).strftime("%Y-%m-%d")
    fm = {"created": stamp, "source": "mcp"}
    if frontmatter:
        fm.update(frontmatter)
    path.parent.mkdir(parents=True, exist_ok=True)
    body = content if content.endswith("\n") else content + "\n"
    path.write_text(_render_frontmatter(fm) + body, encoding="utf-8")
    return {"path": guard.rel_posix(rel), "mode": mode, "created": not exists}
