"""FastMCP server exposing search / read / write / save-url over Streamable HTTP.

The server holds no LLM. It is a deterministic set of tools; the connecting
model (claude.ai, Claude Code, ...) is the brain that decides what to write and
which folder it belongs in (via the `vault_taxonomy` tool).
"""

from __future__ import annotations

from typing import Annotated, Any

from fastmcp import FastMCP
from pydantic import Field

from . import external
from .config import Config
from .guards import GuardError, VaultGuard
from .notes import read_note, write_note
from .taxonomy import build_taxonomy


def build_server(config: Config) -> FastMCP:
    guard = VaultGuard(config.vault_path)

    auth = None
    if config.auth_token:
        from fastmcp.server.auth import StaticTokenVerifier

        auth = StaticTokenVerifier(
            tokens={config.auth_token: {"sub": "owner", "client_id": "vault-mcp"}}
        )

    mcp = FastMCP("Vault MCP", auth=auth)

    @mcp.tool
    def vault_taxonomy() -> dict:
        """Return the vault's folder tree, PARA policy, and subcategory
        whitelists. Call this FIRST when deciding where to save a note, then pass
        the chosen folder to `vault_write`."""
        return build_taxonomy(config.vault_path)

    @mcp.tool
    def vault_search(
        query: Annotated[str, Field(description="Search query.")],
        mode: Annotated[
            str, Field(description="'semantic' (hybrid vector search) or 'title' (exact title/path lookup).")
        ] = "semantic",
        limit: Annotated[int, Field(ge=1, le=50, description="Max results.")] = 8,
    ) -> str:
        """Search the vault. 'semantic' for meaning-based discovery, 'title' for
        finding a note by its name or path."""
        if mode == "title":
            return external.title_search(config.wiki_query_bin, query, limit)
        return external.semantic_search(
            config.fast_search_bin, config.qmd_bin, query, "obsidian", limit
        )

    @mcp.tool
    def vault_read(
        path: Annotated[str, Field(description="Vault-relative path, e.g. '30-Resources/AI/note.md'.")],
    ) -> dict:
        """Read a note's full content. Machine-generated index/log files and the
        legacy wiki dump are blocked."""
        try:
            return read_note(guard, path)
        except GuardError as e:
            return {"error": str(e)}

    @mcp.tool
    def vault_write(
        folder: Annotated[str, Field(description="Destination folder, vault-relative (from vault_taxonomy).")],
        filename: Annotated[str, Field(description="File name; '.md' added if missing.")],
        content: Annotated[str, Field(description="Markdown body (without frontmatter).")],
        mode: Annotated[
            str, Field(description="'create' (fail if exists), 'overwrite', or 'append'.")
        ] = "create",
        frontmatter: Annotated[
            dict[str, Any] | None, Field(description="Optional YAML frontmatter to merge.")
        ] = None,
        rebuild_index: Annotated[
            bool, Field(description="Rebuild the wiki index after writing (default off).")
        ] = False,
    ) -> dict:
        """Create, overwrite, or append to a note. The caller chooses `folder`
        (see vault_taxonomy). Writes are restricted to the PARA source buckets."""
        try:
            result = write_note(guard, folder, filename, content, mode, frontmatter)
        except GuardError as e:
            return {"error": str(e)}
        if rebuild_index:
            result["index"] = external.rebuild_index(config.index_rebuild_cmd)
        return result

    @mcp.tool
    def vault_save_url(
        url: Annotated[str, Field(description="URL to fetch, extract, and save as a source note.")],
        folder: Annotated[
            str | None, Field(description="Optional destination folder; defaults to the helper's own default.")
        ] = None,
        rebuild_index: Annotated[
            bool, Field(description="Rebuild the wiki index after saving (default off).")
        ] = False,
    ) -> dict:
        """Fetch a URL, extract clean text, and save it as a note. Returns a
        small preview so you can write an executive summary back with vault_write."""
        result = external.save_url(config.save_link_bin, url, folder)
        if rebuild_index:
            result["index"] = external.rebuild_index(config.index_rebuild_cmd)
        return result

    return mcp


def main() -> None:
    from dotenv import load_dotenv

    load_dotenv()
    config = Config.from_env()
    mcp = build_server(config)
    mcp.run(
        transport="http",
        host=config.host,
        port=config.port,
        path=config.path,
    )


if __name__ == "__main__":
    main()
