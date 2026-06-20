# Authentication & Authorization

vault-mcp is meant to be reachable over the public internet, so **auth is the
front door**. There are three modes plus a combined mode.

| Mode | Authenticates with | Works with |
|---|---|---|
| `token` | `Authorization: Bearer <token>` | Claude Code (`--header`). **Not** Claude Desktop / claude.ai connector UI (no header field). |
| `github` | GitHub OAuth (browser, PKCE), restricted to an allowlist | Claude Desktop / claude.ai remote connectors, Claude Code. |
| `none` | nothing | trusted/private networks only. |
| `github` + token | both at once (MultiAuth) | Desktop via OAuth **and** CLI/automation via token, one server. |

`AUTH_MODE` selects the mode. If unset it is inferred: `github` when
`GITHUB_CLIENT_ID` is set, else `token` when `MCP_AUTH_TOKEN` is set, else `none`.

## Why GitHub OAuth for Claude Desktop

The Claude Desktop / claude.ai custom-connector UI authenticates **only via
OAuth** — there is no field to paste a static Bearer token, and the "no auth"
path is unreliable. So a token-only server cannot be added as a remote connector
there. `github` mode solves this: FastMCP's `GitHubProvider` presents an
OAuth/DCR-compliant surface that the connector can drive.

## Authentication ≠ authorization

OAuth proves **who you are** (a GitHub account). It does **not** decide whether
you're allowed in — by default *any* GitHub user could complete the flow, which
is **more open than a static token**. vault-mcp closes this with an allowlist:

- `GITHUB_ALLOWED_USERS` — comma-separated GitHub logins.
- `AllowlistMiddleware` (`auth.py`) checks every `tools/call` and rejects any
  identity not on the list.
- **Fail-closed**: `github` mode refuses to start without `GITHUB_CLIENT_ID`,
  `GITHUB_CLIENT_SECRET`, `BASE_URL`, and a non-empty `GITHUB_ALLOWED_USERS`.

## MultiAuth: OAuth and token together

In `github` mode, if `MCP_AUTH_TOKEN` is also set, the server wraps
`GitHubProvider` in FastMCP's `MultiAuth` with a `StaticTokenVerifier`:

- The OAuth provider owns the discovery routes/metadata (one clean surface).
- A request with a bearer token is verified against either source; first success
  wins.
- The static token carries the OAuth resource's required scope and a `trusted`
  claim. `AllowlistMiddleware` lets any `trusted` token through — **holding the
  secret is the authorization** — while OAuth identities are still checked
  against `GITHUB_ALLOWED_USERS`.

Result: Claude Desktop connects via OAuth; Claude Code / scripts use the token;
one server, one URL.

## Set up GitHub OAuth

1. Register an OAuth App at <https://github.com/settings/developers> → **New OAuth App**:
   - **Homepage URL**: `https://your-host`
   - **Authorization callback URL**: `https://your-host/auth/callback`
2. In `.env`:
   ```
   AUTH_MODE=github
   GITHUB_CLIENT_ID=<client id>
   GITHUB_CLIENT_SECRET=<client secret>
   BASE_URL=https://your-host
   GITHUB_ALLOWED_USERS=<your-login>
   # optional: also accept a static token for Claude Code / automation
   MCP_AUTH_TOKEN=<token>
   ```
3. Restart the server.

`BASE_URL` must be the **public HTTPS URL** the reverse proxy serves — it appears
in the OAuth discovery metadata and redirect URIs. Behind a proxy the server
still binds locally; only `BASE_URL` tells it its public identity.

## Verifying

```bash
# OAuth metadata advertises the public URL
curl -s https://your-host/.well-known/oauth-authorization-server

# unauthenticated tool calls are challenged
curl -s -o /dev/null -w '%{http_code}\n' -X POST https://your-host/mcp \
  -H 'Accept: application/json, text/event-stream' -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'   # -> 401
```
