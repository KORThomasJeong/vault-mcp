# vault-mcp

A small **remote MCP server** that lets an LLM (claude.ai, Claude Code, mobile)
**search, read, and write** an [Obsidian](https://obsidian.md) vault organised
with the [PARA](https://fortelabs.com/blog/para/) method — and **save URLs** as
notes.

The server holds **no LLM of its own**. It is a deterministic set of tools; the
connecting model is the brain. When you ask it to "save this to my vault", the
model calls `vault_taxonomy` to see your folder structure, picks the right
folder itself, and calls `vault_write`.

```
claude.ai / Claude Code  ──https + Bearer token──▶  reverse proxy / TLS
                                                          │
                                                  127.0.0.1:8848 (this server)
                                                          │
                                                  ~/Obsidian/YourVault
```

## Tools

| Tool | What it does |
|---|---|
| `vault_taxonomy` | Returns the folder tree, PARA policy, and subcategory whitelists so the model can choose a destination folder. |
| `vault_search` | `semantic` (hybrid vector search) or `title` (exact name/path lookup). |
| `vault_read` | Returns a note's content. Machine-generated index/log files and legacy dumps are blocked. |
| `vault_write` | Create / overwrite / append a note. The caller supplies the folder. Writes are restricted to PARA buckets; the vault root is never written. |
| `vault_save_url` | Fetch a URL, extract clean text, save it as a note, and return a small preview. |

## Safety

- Every path is resolved and confined to the vault root — no `..` traversal, no absolute paths, no symlink escapes.
- Writes are allowed only under `01-Inbox/`, `10-Projects/`, `20-Areas/`, `30-Resources/`, `docs/`.
- Reads of regenerable index/map/log artifacts and legacy wiki backups are refused (they are huge and waste tokens).
- A static **Bearer token** (`MCP_AUTH_TOKEN`) guards every request.

## Install

```bash
git clone https://github.com/KORThomasJeong/vault-mcp.git
cd vault-mcp
cp .env.example .env        # then edit .env
uv sync
```

Generate an auth token:

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

## Configure

All config is via environment (see `.env.example`):

| Var | Required | Default | Notes |
|---|---|---|---|
| `VAULT_PATH` | ✅ | — | Absolute path to the vault root. |
| `MCP_AUTH_TOKEN` |  | (none) | Bearer token. **Set this for any internet-facing deployment.** |
| `MCP_HOST` |  | `127.0.0.1` | Keep on localhost behind a proxy. |
| `MCP_PORT` |  | `8848` | |
| `MCP_PATH` |  | `/mcp` | |
| `QMD_BIN` |  | `qmd` | Semantic search helper. Blank → that mode is disabled. |
| `WIKI_QUERY_BIN` |  | `wiki-query` | Title/path search helper. Blank → disabled. |
| `SAVE_LINK_BIN` |  | `obsidian-save-link` | URL→note helper. Blank → disabled. |
| `INDEX_REBUILD_CMD` |  | (none) | Command run when a tool is called with `rebuild_index=true`. |

The search and URL-save tools shell out to optional companion CLIs. If you don't
have them, those tools simply report that they're disabled — read/write/taxonomy
still work.

## Run

```bash
uv run vault-mcp
# serves Streamable HTTP at http://127.0.0.1:8848/mcp
```

Expose it through your existing reverse proxy (Caddy/nginx/Cloudflare) so that
`https://your-domain:port/mcp` forwards to `127.0.0.1:8848`.

### Connect from Claude Code

```bash
claude mcp add --transport http vault https://your-domain:port/mcp \
  --header "Authorization: Bearer <your-token>"
```

### Connect from claude.ai

Add a custom connector pointing at `https://your-domain:port/mcp` with the
`Authorization: Bearer <token>` header. (claude.ai requires HTTPS.)

## Develop

```bash
uv run --extra dev pytest
```

## License

MIT
