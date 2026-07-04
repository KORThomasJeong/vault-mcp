# Changelog

All notable changes to vault-mcp.

## Unreleased

### Added
- **Transcript-done webhook** (`POST /hooks/transcript-done`): a custom HTTP
  route on the same FastMCP process — MCP protocol and this webhook share one
  server but are separate doors. When STT-web pushes a raw transcript into the
  vault it fires this hook, and we run a headless `claude -p` that reads the
  vault's own cleanup-prompt guide and synthesises the Meeting MOM (no manual
  paste step). Guardrails, all in `webhook.py` (pure logic, unit-tested):
  1. **HMAC auth** — the MCP path's auth does not cover this door, so it carries
     its own. `X-Transcript-Signature: sha256=<HMAC-SHA256(secret, raw body)>`,
     compared constant-time. The route is **only mounted when
     `TRANSCRIPT_HOOK_SECRET` is set** — no secret, no unauthenticated way to
     fire the agent.
  2. **202 + background** — validate, flip the raw file's frontmatter to
     `processing`, then return `202 Accepted` immediately and run `claude -p` as
     an asyncio background task (STT-web's hook call never blocks on the minutes
     of synthesis).
  3. **Timeout** — the headless run is killed at `TRANSCRIPT_HOOK_TIMEOUT`
     (default 1800s / 30m); the vault_exec 15s cap is far too short for this
     path, so it has its own limit.
  4. **Exit-code branch** — exit 0 → frontmatter `status: processed`; anything
     else (incl. timeout) → `status: failed` with the error, so it can be
     retried.
  Submitted paths are validated to sit under `TRANSCRIPT_ROOT` and then resolved
  through the existing vault path guard, so the hook can never point the agent
  at an arbitrary file. Config: `TRANSCRIPT_HOOK_SECRET`, `CLAUDE_BIN`,
  `TRANSCRIPT_HOOK_TIMEOUT`, `TRANSCRIPT_ALLOWED_TOOLS`, `TRANSCRIPT_MCP_CONFIG`,
  `TRANSCRIPT_PROMPT_GUIDE`, `TRANSCRIPT_ROOT` (see `.env.example`).
- **`vault_exec` tool**: runs an allowlisted shell command on the vault host
  (cwd = vault root) and returns stdout/stderr/exit code. This is a single-user
  server gated by the GitHub user allowlist (`GITHUB_ALLOWED_USERS`) + static
  token, so by the owner's choice the tool is intentionally permissive:
  1. the command must start with an approved prefix
     (`find`/`ls`/`rm`/`mv`/`cp`/`mkdir`/`cat`/`echo`/`bash ~/.claude/`/
     `python3 ~/.hermes/`/`hermes `);
  2. `rm` is confined to the vault root (each path argument is resolved and must
     live under `VAULT_PATH`);
  3. 15s timeout; runs with `cwd = VAULT_PATH`.

  Command chaining / substitution / pipes are **not** restricted — the
  connecting account is trusted (only the owner can authenticate). This means
  `vault_exec` is effectively arbitrary command execution behind auth. If the
  server is ever shared or the threat model changes (e.g. concern about
  MCP prompt-injection steering the tool), re-add the chaining/pipe guards or
  drop `echo`/`cat`. Disable entirely by removing the tool registration in
  `server.py`.

## 0.2.0

Authentication overhaul and production-deployment hardening.

### Added
- **GitHub OAuth auth mode** (`AUTH_MODE=github`) via FastMCP's `GitHubProvider`
  (OAuth-proxy under the hood), so the server works with **Claude Desktop /
  claude.ai remote connectors** — their connector UI authenticates via OAuth and
  has no field for a static Bearer token.
- **User allowlist** (`GITHUB_ALLOWED_USERS`) enforced by an `AllowlistMiddleware`
  on every tool call. OAuth proves *who you are*; the allowlist decides *whether
  you're allowed*. See [AUTHENTICATION.md](AUTHENTICATION.md).
- **Simultaneous auth (MultiAuth)**: in `github` mode, if `MCP_AUTH_TOKEN` is
  also set, the server accepts **both** GitHub OAuth *and* a static token at once
  (Claude Desktop via OAuth, Claude Code / automation via token). The static
  token is marked `trusted` so it bypasses the allowlist (holding the secret is
  authorization) and carries the required scope.
- `AUTH_MODE` (`token` | `github` | `none`), `BASE_URL`, `GITHUB_CLIENT_ID`,
  `GITHUB_CLIENT_SECRET`, `GITHUB_ALLOWED_USERS` config.
- `FAST_SEARCH_BIN`: a warm semantic-search front-end (called
  `<bin> "<query>" -n <limit>`), preferred over `QMD_BIN`. Lets `vault_search`
  use a resident embedding daemon instead of a per-call model load. See
  [DEPLOYMENT.md](DEPLOYMENT.md#semantic-search-backend).
- `docs/` with architecture, authentication, and deployment guides.

### Changed
- `from_env` infers `auth_mode` when unset: `github` if `GITHUB_CLIENT_ID` is
  present, else `token` if `MCP_AUTH_TOKEN` is present, else `none`.
- **Fail-closed**: `github` mode refuses to start without client id/secret,
  `BASE_URL`, and a non-empty `GITHUB_ALLOWED_USERS`.
- Title search treats an empty `wiki-query` result (`no rows`) as "(no matches)"
  rather than reporting a failure.

### Notes
- `MCP_HOST` must be `0.0.0.0` when the reverse proxy reaches the server over the
  LAN (e.g. Nginx Proxy Manager in Docker) rather than `127.0.0.1`.

## 0.1.0

Initial release.

- Streamable HTTP MCP server over `mcp.run(transport="http")`.
- Tools: `vault_taxonomy`, `vault_search`, `vault_read`, `vault_write`,
  `vault_save_url`.
- Path guards confining all operations to the vault, blocking regenerable
  index/log artifacts and legacy dumps; writes restricted to PARA buckets.
- Static Bearer-token auth via `StaticTokenVerifier`.
- Optional companion CLIs for search and URL-save; tools degrade gracefully when
  absent.
