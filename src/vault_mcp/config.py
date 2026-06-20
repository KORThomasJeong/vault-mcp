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
    # auth
    auth_mode: str            # "token" | "github" | "none"
    auth_token: str | None
    base_url: str | None
    github_client_id: str | None
    github_client_secret: str | None
    github_allowed_users: frozenset[str]
    # transport
    host: str
    port: int
    path: str
    # helper binaries
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

        auth_token = opt("MCP_AUTH_TOKEN")
        github_client_id = opt("GITHUB_CLIENT_ID")
        # Default mode preserves backwards compatibility: explicit AUTH_MODE wins,
        # otherwise infer from which credentials are present.
        auth_mode = (opt("AUTH_MODE") or "").lower()
        if not auth_mode:
            if github_client_id:
                auth_mode = "github"
            elif auth_token:
                auth_mode = "token"
            else:
                auth_mode = "none"
        if auth_mode not in ("token", "github", "none"):
            raise RuntimeError(f"AUTH_MODE must be token|github|none, got {auth_mode!r}")

        allowed = frozenset(
            u.strip().lower()
            for u in (env.get("GITHUB_ALLOWED_USERS", "") or "").split(",")
            if u.strip()
        )

        if auth_mode == "github":
            # Fail closed: never start an internet-facing OAuth server that lets
            # *any* authenticated GitHub user in.
            missing = [
                name
                for name, val in (
                    ("GITHUB_CLIENT_ID", github_client_id),
                    ("GITHUB_CLIENT_SECRET", opt("GITHUB_CLIENT_SECRET")),
                    ("BASE_URL", opt("BASE_URL")),
                )
                if not val
            ]
            if missing:
                raise RuntimeError(
                    "AUTH_MODE=github requires: " + ", ".join(missing)
                )
            if not allowed:
                raise RuntimeError(
                    "AUTH_MODE=github requires GITHUB_ALLOWED_USERS (comma-separated "
                    "GitHub logins) so only you can connect."
                )

        return cls(
            vault_path=vault_path,
            auth_mode=auth_mode,
            auth_token=auth_token,
            base_url=opt("BASE_URL"),
            github_client_id=github_client_id,
            github_client_secret=opt("GITHUB_CLIENT_SECRET"),
            github_allowed_users=allowed,
            host=env.get("MCP_HOST", "127.0.0.1").strip() or "127.0.0.1",
            port=int(env.get("MCP_PORT", "8848").strip() or "8848"),
            path=env.get("MCP_PATH", "/mcp").strip() or "/mcp",
            fast_search_bin=opt("FAST_SEARCH_BIN"),
            qmd_bin=opt("QMD_BIN"),
            wiki_query_bin=opt("WIKI_QUERY_BIN"),
            save_link_bin=opt("SAVE_LINK_BIN"),
            index_rebuild_cmd=opt("INDEX_REBUILD_CMD"),
        )
