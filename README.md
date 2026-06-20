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
Claude Desktop / claude.ai / Claude Code
        │  HTTPS + GitHub OAuth (or Bearer token)
        ▼
 reverse proxy / TLS  ──►  vault-mcp (this server)  ──►  ~/Obsidian/YourVault
```

> **Docs:** [Architecture](docs/ARCHITECTURE.md) ·
> [Authentication](docs/AUTHENTICATION.md) ·
> [Deployment](docs/DEPLOYMENT.md) · [Changelog](docs/CHANGELOG.md)

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
- Auth is required: a static **Bearer token** or **GitHub OAuth** with a user allowlist (see [Authentication](#authentication)).

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
| `AUTH_MODE` |  | inferred | `token` \| `github` \| `none`. See [Authentication](#authentication). |
| `MCP_AUTH_TOKEN` |  | (none) | Bearer token (token mode). |
| `GITHUB_CLIENT_ID` / `GITHUB_CLIENT_SECRET` |  | (none) | GitHub OAuth app credentials (github mode). |
| `BASE_URL` |  | (none) | Public HTTPS URL of the server (github mode). |
| `GITHUB_ALLOWED_USERS` |  | (none) | Comma-separated GitHub logins allowed to connect. **Required in github mode.** |
| `MCP_HOST` |  | `127.0.0.1` | Use `0.0.0.0` when the proxy reaches it over the LAN (e.g. NPM in Docker), else 502. |
| `MCP_PORT` |  | `8848` | |
| `MCP_PATH` |  | `/mcp` | |
| `FAST_SEARCH_BIN` |  | (none) | Warm semantic-search front-end, called `<bin> "<query>" -n <limit>`. Preferred over `QMD_BIN`. |
| `QMD_BIN` |  | `qmd` | Fallback semantic search helper. Blank + no `FAST_SEARCH_BIN` → that mode is disabled. |
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

Expose it through your existing reverse proxy (nginx / Nginx Proxy Manager /
Caddy / Cloudflare) so that `https://your-host/mcp` forwards to `127.0.0.1:8848`.
Enable WebSocket/streaming pass-through and disable response buffering so SSE
works (for nginx: `proxy_buffering off;`, a long `proxy_read_timeout`).

## Authentication

| Mode | How clients authenticate | Works with |
|---|---|---|
| `token` | `Authorization: Bearer <token>` header | Claude Code (`--header`). **Not** the Claude Desktop / claude.ai custom-connector UI (no header field). |
| `github` | GitHub OAuth (browser), restricted to `GITHUB_ALLOWED_USERS` | Claude Desktop / claude.ai remote connectors, Claude Code. |
| `none` | nothing | trusted/private networks only. |
| `github` + token | both at once (MultiAuth) | Desktop via OAuth **and** CLI/automation via token, one server. |

> **OAuth authenticates, the allowlist authorizes.** In `github` mode the server
> refuses to start unless `GITHUB_ALLOWED_USERS` is set — otherwise *any* GitHub
> account could connect, which is more open than a token.

> **Both at once:** set `MCP_AUTH_TOKEN` alongside `github` mode and the server
> accepts GitHub OAuth *and* the static token simultaneously (MultiAuth). Details
> in [docs/AUTHENTICATION.md](docs/AUTHENTICATION.md).

### Set up GitHub OAuth (github mode)

1. Register an OAuth App at <https://github.com/settings/developers> → **New OAuth App**:
   - **Homepage URL**: `https://your-host`
   - **Authorization callback URL**: `https://your-host/auth/callback`
2. Copy the **Client ID**, generate a **Client secret**, and put them plus
   `BASE_URL=https://your-host`, `AUTH_MODE=github`, and
   `GITHUB_ALLOWED_USERS=<your-login>` in `.env`.
3. Restart the server.

### Connect from Claude Code

```bash
# token mode
claude mcp add --transport http vault https://your-host/mcp \
  --header "Authorization: Bearer <your-token>"

# github mode (OAuth — opens a browser)
claude mcp add --transport http vault https://your-host/mcp
```

### Connect from Claude Desktop / claude.ai

Settings → Connectors → add a custom connector pointing at `https://your-host/mcp`.
Use **github mode** — the desktop/web connector UI authenticates via OAuth and
has no field for a static Bearer token.

## Develop

```bash
uv run --extra dev pytest
```

## License

MIT
