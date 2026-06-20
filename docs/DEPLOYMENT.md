# Deployment

A production setup: the server runs locally, a reverse proxy terminates TLS at a
public hostname, and a process manager keeps it alive.

```
Claude Desktop / claude.ai ──HTTPS──▶ reverse proxy (TLS, your-host)
                                            │  http
                                            ▼
                                   vault-mcp  0.0.0.0:8848
                                            │
                                   the Obsidian vault
```

## 1. Bind address

`MCP_HOST` controls where the server listens.

- `127.0.0.1` — only if the proxy runs on the **same host, same network
  namespace**.
- `0.0.0.0` — **required** when the proxy reaches the server over the LAN, e.g.
  **Nginx Proxy Manager / nginx in Docker**. A Docker container cannot reach the
  host's `127.0.0.1`; it connects to the host's LAN IP, which a `127.0.0.1`-bound
  socket refuses → **502 Bad Gateway**.

Auth still guards every tool call, so `0.0.0.0` behind a firewall is fine.

## 2. Reverse proxy

Point `https://your-host/` at `http://<host-lan-ip>:8848` and forward the whole
host (the OAuth routes `/authorize`, `/token`, `/register`, `/auth/callback`, the
`/.well-known/*` metadata, and `/mcp` all live under root).

Required proxy settings:
- **WebSocket / streaming pass-through: ON**
- **Disable response buffering** so SSE streams (nginx: `proxy_buffering off;`)
- **Long read timeout** (nginx: `proxy_read_timeout 3600s;`)
- **TLS** (Let's Encrypt) with Force-SSL

### Nginx Proxy Manager

- Proxy Host → Forward Hostname/Port: `<host-lan-ip>` : `8848`, scheme `http`
- **Websockets Support: ON**
- Advanced tab:
  ```nginx
  proxy_buffering off;
  proxy_read_timeout 3600s;
  ```
- SSL tab: request a cert + Force SSL.

### Plain nginx

```nginx
location / {
    proxy_pass http://127.0.0.1:8848;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-Proto https;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_buffering off;
    proxy_read_timeout 3600s;
}
```

Set `BASE_URL=https://your-host` so OAuth metadata advertises the public URL.

## 3. Keep it running

### macOS — launchd

`~/Library/LaunchAgents/com.example.vault-mcp.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key><string>com.example.vault-mcp</string>
    <key>ProgramArguments</key>
    <array>
        <string>/path/to/uv</string><string>run</string><string>vault-mcp</string>
    </array>
    <key>WorkingDirectory</key><string>/path/to/vault-mcp</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key><string>/path/to/.local/bin:/usr/local/bin:/usr/bin:/bin</string>
    </dict>
    <key>RunAtLoad</key><true/>
    <key>KeepAlive</key><true/>
    <key>StandardOutPath</key><string>/path/to/vault-mcp/vault-mcp.log</string>
    <key>StandardErrorPath</key><string>/path/to/vault-mcp/vault-mcp.log</string>
</dict>
</plist>
```

```bash
launchctl load ~/Library/LaunchAgents/com.example.vault-mcp.plist
launchctl list | grep vault-mcp
```

The server reads `.env` from `WorkingDirectory` via `python-dotenv`, so the agent
needs no secrets inline.

### Linux — systemd (sketch)

A `systemd --user` unit with `ExecStart=/path/to/uv run vault-mcp`,
`WorkingDirectory=/path/to/vault-mcp`, `Restart=always` is the equivalent.

## 4. Connect clients

```bash
# Claude Code, token mode
claude mcp add --transport http vault https://your-host/mcp \
  --header "Authorization: Bearer <token>"

# Claude Code, github mode (opens a browser)
claude mcp add --transport http vault https://your-host/mcp
```

Claude Desktop / claude.ai: **Settings → Connectors → Add custom connector** →
`https://your-host/mcp` → complete the GitHub OAuth flow (github mode).

## Semantic search backend

`vault_search mode=semantic` shells out to `FAST_SEARCH_BIN` (preferred) or
`QMD_BIN`. `FAST_SEARCH_BIN` is any executable called as
`<bin> "<query>" -n <limit>` that prints results — e.g. a thin client to a
**resident embedding daemon**, so each query avoids loading a model.

This decouples vault-mcp from any particular embedding stack: the daemon can use
a local model or a hosted embeddings API (e.g. OpenAI / Azure OpenAI
`text-embedding-3-large`) — vault-mcp doesn't care, it just calls the binary. If
neither `FAST_SEARCH_BIN` nor `QMD_BIN` is set, semantic search reports itself
disabled and read/write/taxonomy keep working.

## Health checks

```bash
curl -s -o /dev/null -w '%{http_code}\n' https://your-host/.well-known/oauth-authorization-server  # 200
curl -s -o /dev/null -w '%{http_code}\n' -X POST https://your-host/mcp \
  -H 'Accept: application/json, text/event-stream' -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'   # 401 (auth challenge)
```
