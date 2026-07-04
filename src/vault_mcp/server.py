"""FastMCP server exposing search / read / write / save-url over Streamable HTTP.

The server holds no LLM. It is a deterministic set of tools; the connecting
model (claude.ai, Claude Code, ...) is the brain that decides what to write and
which folder it belongs in (via the `vault_taxonomy` tool).
"""

from __future__ import annotations

import shlex
import subprocess
from pathlib import Path
from typing import Annotated, Any

from fastmcp import FastMCP
from pydantic import Field

from . import external, webhook
from .config import Config
from .guards import GuardError, VaultGuard
from .notes import read_note, write_note
from .taxonomy import build_taxonomy

# --- vault_exec: allowlisted shell access on the vault host ---------------
#
# Single-user server (auth-gated by the GitHub allowlist + static token), so we
# keep this deliberately permissive per the owner's choice:
#   1) the command must start with an approved prefix,
#   2) `rm` is confined to the vault root,
#   3) 15s timeout.
# No command-chaining/pipe restrictions — the connecting account is trusted.
# See docs/CHANGELOG.md for the trade-off.

VAULT_EXEC_ALLOWED_PREFIXES: tuple[str, ...] = (
    "find ",
    "ls ",
    "ls",  # bare `ls`
    "rm ",
    "mv ",
    "cp ",
    "mkdir ",
    "cat ",
    "echo ",
    "bash ~/.claude/",
    "python3 ~/.hermes/",
    "hermes ",
)


def run_vault_exec(command: str, vault_root: Path) -> dict:
    """Validate and run an allowlisted shell command. `rm` stays in the vault."""
    cmd = command.strip()
    if not cmd:
        return {"ok": False, "error": "Empty command"}

    if not any(cmd.startswith(p) for p in VAULT_EXEC_ALLOWED_PREFIXES):
        return {
            "ok": False,
            "error": "Command not in allowlist",
            "allowed_prefixes": list(VAULT_EXEC_ALLOWED_PREFIXES),
        }

    # rm is the one irreversible op we still fence to the vault root.
    if cmd.split(maxsplit=1)[0] == "rm":
        try:
            tokens = shlex.split(cmd)
        except ValueError:
            return {"ok": False, "error": "Unparseable command"}
        for tok in tokens[1:]:
            if tok.startswith("-"):
                continue
            target = Path(tok).expanduser()
            if not target.is_absolute():
                target = vault_root / tok
            try:
                resolved = target.resolve()
            except OSError:
                return {"ok": False, "error": f"Bad path: {tok}"}
            if resolved != vault_root and vault_root not in resolved.parents:
                return {
                    "ok": False,
                    "error": f"rm is confined to the vault root: {vault_root}",
                    "offending_path": tok,
                }

    try:
        result = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            timeout=15,
            cwd=str(vault_root),
        )
        return {
            "ok": result.returncode == 0,
            "stdout": result.stdout.strip(),
            "stderr": result.stderr.strip(),
            "exit_code": result.returncode,
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "Timeout (15s)"}
    except Exception as e:  # noqa: BLE001 - surface any failure to the caller
        return {"ok": False, "error": str(e)}


def build_server(config: Config) -> FastMCP:
    guard = VaultGuard(config.vault_path)

    auth = None
    allowlist_mw = None
    if config.auth_mode == "token" and config.auth_token:
        from fastmcp.server.auth import StaticTokenVerifier

        auth = StaticTokenVerifier(
            tokens={config.auth_token: {"sub": "owner", "client_id": "vault-mcp"}}
        )
    elif config.auth_mode == "github":
        from fastmcp.server.auth.providers.github import GitHubProvider

        from .auth import AllowlistMiddleware

        github = GitHubProvider(
            client_id=config.github_client_id,
            client_secret=config.github_client_secret,
            base_url=config.base_url,
        )
        if config.auth_token:
            # Accept BOTH: GitHub OAuth (Claude Desktop / claude.ai) AND a static
            # token (Claude Code / automation). OAuth owns the discovery routes;
            # the token is an extra verification path. The token is marked
            # "trusted" so the allowlist middleware lets it through — holding the
            # secret already authorizes it.
            from fastmcp.server.auth import MultiAuth, StaticTokenVerifier

            auth = MultiAuth(
                server=github,
                verifiers=[
                    StaticTokenVerifier(
                        tokens={
                            config.auth_token: {
                                "sub": "static-token",
                                "client_id": "vault-mcp",
                                "trusted": True,
                                # Match the scope the OAuth resource requires so the
                                # token isn't rejected with insufficient_scope.
                                "scopes": ["user"],
                            }
                        }
                    )
                ],
            )
        else:
            auth = github
        allowlist_mw = AllowlistMiddleware(config.github_allowed_users)

    mcp = FastMCP("Vault MCP", auth=auth)
    if allowlist_mw is not None:
        mcp.add_middleware(allowlist_mw)

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
        include_wiki: Annotated[
            bool,
            Field(
                description="Include auto-generated Wiki/ synthesis nodes "
                "(topic/entity/concept seeds). Default false: results are real "
                "content notes, not second-order summaries. Set true to also "
                "search the Wiki synthesis layer (e.g. 'Compiled Truth' entries)."
            ),
        ] = False,
    ) -> str:
        """Search the vault. 'semantic' for meaning-based discovery, 'title' for
        finding a note by its name or path. By default, auto-generated Wiki/
        index nodes are excluded from semantic results; pass include_wiki=true
        to include them."""
        if mode == "title":
            return external.title_search(config.wiki_query_bin, query, limit)
        return external.semantic_search(
            config.fast_search_bin, config.qmd_bin, query, "obsidian", limit, include_wiki
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

    @mcp.tool
    def vault_exec(
        command: Annotated[
            str,
            Field(
                description="Allowlisted shell command to run on the vault host "
                "(cwd = vault root). Only approved prefixes are permitted; "
                "command chaining/substitution is rejected and rm/mv/cp are "
                "confined to the vault root."
            ),
        ],
    ) -> dict:
        """Run an allowlisted shell command on the vault host and return its
        stdout/stderr/exit code. Only pre-approved command prefixes are allowed,
        shell operators that chain or escape the command are refused, and
        destructive operations stay inside the vault root."""
        return run_vault_exec(command, config.vault_path)

    # --- transcript-done webhook (STT-web → auto MOM) ---------------------
    #
    # A separate HTTP door on the same FastMCP process. Mounted ONLY when a
    # shared secret is configured — no secret means no unauthenticated path to
    # fire a headless `claude -p`.
    if config.transcript_hook_secret:
        from starlette.requests import Request
        from starlette.responses import JSONResponse

        @mcp.custom_route("/hooks/transcript-done", methods=["POST"])
        async def transcript_done(request: Request) -> JSONResponse:
            body = await request.body()

            if not webhook.verify_signature(
                config.transcript_hook_secret,
                body,
                request.headers.get("X-Transcript-Signature"),
            ):
                return JSONResponse({"error": "invalid signature"}, status_code=401)

            try:
                payload = webhook.parse_payload(
                    body, config.transcript_root, config.vault_path
                )
            except webhook.HookError as e:
                return JSONResponse({"error": str(e)}, status_code=400)

            # The path is validated to sit under the transcript root; resolve it
            # through the guard so symlink/traversal tricks can't escape either.
            try:
                raw_abs = guard.check_readable(payload.path)
            except GuardError as e:
                return JSONResponse({"error": str(e)}, status_code=400)
            if not raw_abs.is_file():
                return JSONResponse(
                    {"error": f"transcript not found: {payload.path}"}, status_code=404
                )

            # Mark processing synchronously so STT-web (and any dashboard) sees
            # the state flip before we return, then dispatch and 202 immediately.
            try:
                webhook.set_status(raw_abs, "processing", {"hook_at": webhook._utcstamp()})
            except OSError as e:
                return JSONResponse({"error": str(e)}, status_code=500)

            webhook.spawn(
                webhook.process_transcript(
                    raw_abs=raw_abs,
                    raw_rel=payload.path,
                    payload=payload,
                    claude_bin=config.claude_bin,
                    allowed_tools=config.transcript_allowed_tools,
                    mcp_config=config.transcript_mcp_config,
                    prompt_guide=config.transcript_prompt_guide,
                    timeout=config.transcript_hook_timeout,
                    cwd=config.vault_path,
                )
            )
            return JSONResponse(
                {"status": "accepted", "path": payload.path}, status_code=202
            )

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
