# Changelog

All notable changes to vault-mcp.

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
