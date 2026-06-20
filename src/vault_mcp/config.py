"""Runtime configuration, read once from the environment.

Everything that is machine- or user-specific (the vault location, the auth
token, helper binary names) lives here so the rest of the code stays generic and
the public repository never hard-codes a personal path or secret.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Config:
    vault_path: Path
    auth_token: str | None
    host: str
    port: int
    path: str
    fast_search_bin: str | None
    qmd_bin: str | None
    wiki_query_bin: str | None
    save_link_bin: str | None
    index_rebuild_cmd: str | None

    @classmethod
    def from_env(cls, environ: dict[str, str] | None = None) -> "Config":
        env = os.environ if environ is None else environ

        raw_vault = env.get("VAULT_PATH", "").strip()
        if not raw_vault:
            raise RuntimeError(
                "VAULT_PATH is required. Set it to the absolute path of your vault."
            )
        vault_path = Path(raw_vault).expanduser().resolve()
        if not vault_path.is_dir():
            raise RuntimeError(f"VAULT_PATH does not point to a directory: {vault_path}")

        def opt(name: str) -> str | None:
            value = env.get(name, "").strip()
            return value or None

        return cls(
            vault_path=vault_path,
            auth_token=opt("MCP_AUTH_TOKEN"),
            host=env.get("MCP_HOST", "127.0.0.1").strip() or "127.0.0.1",
            port=int(env.get("MCP_PORT", "8848").strip() or "8848"),
            path=env.get("MCP_PATH", "/mcp").strip() or "/mcp",
            fast_search_bin=opt("FAST_SEARCH_BIN"),
            qmd_bin=opt("QMD_BIN"),
            wiki_query_bin=opt("WIKI_QUERY_BIN"),
            save_link_bin=opt("SAVE_LINK_BIN"),
            index_rebuild_cmd=opt("INDEX_REBUILD_CMD"),
        )
