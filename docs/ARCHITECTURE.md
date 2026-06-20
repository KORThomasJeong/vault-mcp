# Architecture

## Principle: the server is hands, not a brain

vault-mcp holds **no LLM**. It exposes a deterministic set of tools over MCP; the
connecting model (Claude Desktop, claude.ai, Claude Code) is the intelligence.
When you say "save this to my vault", the model:

1. calls `vault_taxonomy` to learn your folder structure and PARA policy,
2. decides the destination folder itself,
3. calls `vault_write(folder=…, …)`.

No classification model runs on the server. This keeps it fast, cheap, and free
of its own token cost.

```
 Claude Desktop / claude.ai / Claude Code      (the brain)
        │  HTTPS  +  OAuth or Bearer token
        ▼
 reverse proxy (TLS)  ──►  vault-mcp  (FastMCP, Streamable HTTP)   (the hands)
                              │  deterministic tools
                              ├─ vault_taxonomy   folder tree + PARA policy
                              ├─ vault_search     semantic / title
                              ├─ vault_read       note body (guarded)
                              ├─ vault_write      create / overwrite / append
                              └─ vault_save_url   fetch + extract + save
                              ▼
                         the Obsidian vault (filesystem)
```

## Modules

| File | Responsibility |
|---|---|
| `config.py` | Read & validate all config from the environment (one place; nothing machine-specific elsewhere). Fails closed on unsafe auth config. |
| `guards.py` | `VaultGuard` — path safety. Confines every path to the vault, blocks traversal/symlink escape, blocks regenerable index/log reads, restricts writes to PARA buckets. |
| `notes.py` | `read_note` / `write_note` — pure filesystem logic, frontmatter rendering, create/overwrite/append semantics. No MCP coupling (unit-testable). |
| `taxonomy.py` | `build_taxonomy` — folder tree + PARA policy + subcategory whitelists for the model to choose a folder. |
| `external.py` | Thin wrappers around optional companion CLIs (semantic search, title search, URL save, index rebuild). Degrade gracefully when a binary is unconfigured. |
| `auth.py` | `AllowlistMiddleware` + identity extraction — authorization on top of OAuth authentication. |
| `server.py` | Wires config → auth provider(s) → tools → `mcp.run(transport="http")`. |

## Tools

| Tool | Input | Behaviour |
|---|---|---|
| `vault_taxonomy` | — | Returns `{policy, folders, whitelists}`. Call first when deciding where to write. |
| `vault_search` | `query`, `mode=semantic\|title`, `limit` | `semantic` → `FAST_SEARCH_BIN` (or `QMD_BIN` fallback); `title` → `wiki-query alias`. |
| `vault_read` | `path` | Returns `{path, content}`. Blocks index/log/legacy reads and over-large files. |
| `vault_write` | `folder`, `filename`, `content`, `mode`, `frontmatter?`, `rebuild_index?` | Create (fail if exists) / overwrite / append. Auto-adds minimal frontmatter. |
| `vault_save_url` | `url`, `folder?`, `rebuild_index?` | Shell to `SAVE_LINK_BIN`; returns its JSON preview. |

## Safety model

- **Path containment** (`guards.py`): paths are normalised and `resolve()`d, then
  checked to be inside the vault root — defeats `..`, absolute paths, and symlink
  escapes. Absolute/`~` inputs are rejected outright.
- **Read denylist**: `Wiki/_maps/`, `Wiki/_indexes/`, `Wiki/_logs/`, and
  `90-Archive/Wiki_legacy_*` / `Wiki_repair_backup_*` are refused — they are
  machine-generated, huge, and would waste tokens.
- **Write allowlist**: only `01-Inbox/`, `10-Projects/`, `20-Areas/`,
  `30-Resources/`, `docs/`. The vault root is never written.
- **Auth required for tool calls** (see [AUTHENTICATION.md](AUTHENTICATION.md)).

## Testing

`tests/` covers the risky pure logic without a live model or network:
`test_guards.py` (containment), `test_notes.py` (read/write/frontmatter),
`test_server.py` (tools via an in-memory FastMCP `Client`), `test_auth.py`
(fail-closed auth-config validation).

```bash
uv run --extra dev pytest
```
