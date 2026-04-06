# AOS CC MCP — Coordinator Handoff

Phase 2b connection package for the claude.ai coordinator project.

---

## Server URL

**Funnel URL:** `https://papax1.tail5fabd0.ts.net`

The server runs on Ilya's X1 laptop (WSL2), exposed to the internet via Tailscale Funnel. The URL is stable as long as Tailscale is running.

## Authentication

Retrieve the bearer token from `~/code/aos-cc-mcp/.env` on X1. Do NOT commit the token. Paste it into the coordinator project system prompt or memory as the MCP auth token.

All requests must include the header:
```
Authorization: Bearer <token>
```

Requests without a valid token are rejected with HTTP 401.

## Available Tools (7 tools, all Tier 0 read-only)

| Tool | Description |
|------|-------------|
| `list_sessions` | Enumerate available CC session logs with optional date/project filters |
| `session_summary` | Compact synthesis of one session: event counts, duration, files, anomaly count |
| `read_session` | Parsed event stream at three verbosity levels (summary/events/full) |
| `search_sessions` | Case-insensitive keyword search across all sessions |
| `extract_commits` | Git commits made during a session or date range |
| `detect_anomalies` | Flag unusual patterns via 7 mechanical rules (hook bypass, silent errors, etc.) |
| `diff_intent_vs_execution` | Compare first prompt intent vs actual files touched |

## MCP Client Configuration

For a claude.ai project connecting as an MCP client over Streamable HTTP:

```json
{
  "mcpServers": {
    "aos-cc-mcp": {
      "type": "url",
      "url": "https://papax1.tail5fabd0.ts.net/mcp",
      "headers": {
        "Authorization": "Bearer <TOKEN_FROM_ENV_FILE>"
      }
    }
  }
}
```

## Testing the Connection

From any machine with curl:

```bash
# Should return 401
curl -s -w "\nHTTP %{http_code}\n" -X POST https://papax1.tail5fabd0.ts.net/mcp

# Should return 200 with MCP initialize response
curl -s -w "\nHTTP %{http_code}\n" -X POST \
  -H "Authorization: Bearer <TOKEN>" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"test","version":"1.0"}},"id":1}' \
  https://papax1.tail5fabd0.ts.net/mcp
```

## Operating Principles

The server operates under strict constitutional rules documented in `CLAUDE.md`:
- All 7 tools are Tier 0 (read-only, always available)
- Server starts in Plan mode (read-only) by default
- No write tools are available in this phase
- Kill switch: set `AOS_CC_MCP_DISABLED=1` on X1 to shut down immediately
- Full audit log of all tool calls maintained on X1

## Process Management

The server runs under pm2 on X1:
- `pm2 status aos-cc-mcp` — check if running
- `pm2 restart aos-cc-mcp` — restart
- `pm2 logs aos-cc-mcp` — view logs
- `pm2 stop aos-cc-mcp` — stop (Funnel will return 502)
