# AOS CC MCP

MCP server that exposes Claude Code session logs and a scoped set of write capabilities to the AOS Coordinator running on claude.ai.

---

## Constitutional Rules

### Operating Modes
This server has three operating modes, enforced at the server level (implemented in Phase 1b):
- **Plan** — read-only. Default on startup. Always.
- **Approve** — writes require per-call human confirmation.
- **YOLO** — writes under a scoped session token.

The server is read-capable by design and write-capable by design, but writes are gated by mode.

### Tool Tiers

**Tier 0: Read-only, always available.**
Read session logs, list sessions, search, summarize. No side effects.

**Tier 1: Low-blast-radius writes.**
Append to DEFERRED.md files in repos under ~/code/, write to ~/aos-coordinator-notes/, append to a decision log. Append-only operations against known safe paths.

**Tier 2: Meaningful writes.**
Launch CC sessions, stage files for review, create new files. Requires Approve or YOLO mode.

**Tier 3: Explicitly prohibited. Constitutional-level ban.**
- No bash execution
- No git commits
- No file deletion
- No file overwrite (create or append only)
- No writes to ~/.claude/
- No network egress
- No package installation

Tier 3 is not "deferred." It is prohibited at the constitutional level. Adding any Tier 3 capability requires a new prompt, a new review, and explicit lifting of the prohibition. Do not add Tier 3 tools under any circumstance in any future phase without an explicit prompt authorizing it.

### Auth footgun — read before enabling network transport
When `AOS_CC_MCP_TOKEN` is unset, the server accepts all connections with zero authentication. This is acceptable for local stdio transport during development. It is a critical vulnerability if the server is exposed via HTTP, Tailscale Funnel, or any other network transport without setting the token. Phase 2 enables network transport. Before enabling any network transport, verify `AOS_CC_MCP_TOKEN` is set to a non-empty value. The server should refuse to start with network transport enabled while the token is unset — this check will be added in Phase 2.

### Phase-Gating
This repo is phase-gated. Each phase lands as its own prompt, its own CC session, its own review. Phases are not batched. Any future CC session working on this repo must read this CLAUDE.md at startup and must not lift phase or tier restrictions without an explicit prompt authorizing it.

---

## Current Phase: 2a — Tier 0 Read Tools

### Tools Registered

| Tool | Tier | Description |
|------|------|-------------|
| `list_sessions` | T0 | Enumerate available session logs with optional date/project filters |
| `session_summary` | T0 | High-level summary of a session (event counts, duration, tools used, anomaly count) |
| `read_session` | T0 | Parsed event stream for a session at three verbosity levels (summary/events/full) |
| `search_sessions` | T0 | Case-insensitive keyword search across all sessions |
| `extract_commits` | T0 | Find git commits made during a session or date range |
| `detect_anomalies` | T0 | Flag unusual patterns via 7 mechanical rules (no judgment calls) |
| `diff_intent_vs_execution` | T0 | Compare first prompt intent vs actual files touched |

All tools are Tier 0 (read-only, always available). Registered via `register_tool_tier()` in `src/aos_cc_mcp/tools.py`.

### Completed (Phase 1a + 1b + 2a)
- Repo scaffolding (pyproject.toml, src layout, tests)
- FastMCP server skeleton with stdio transport
- JSONL session log parser (reads real CC session files, produces typed events)
- Append-only audit log, kill switch, bearer token auth, mode system
- Middleware wiring (audit + mode enforcement on all tool calls)
- 7 Tier 0 read-only tools with full test coverage
- Anomaly detection engine (7 rules, hand-crafted fixtures)
- Tests against real fixture data (139 tests)

### Out of scope (deferred to later phases)
- Network (no Tailscale, no HTTP exposure)
- Write tools (Tier 1 and Tier 2)
- Session tokens for YOLO mode
- Client-side confirmation mechanism for Approve mode

See [DEFERRED.md](DEFERRED.md) for the full phase roadmap.

---

## Authoritative References
- MCP server construction: Python MCP SDK README (https://github.com/modelcontextprotocol/python-sdk)
- `/mnt/skills/examples/mcp-builder/SKILL.md` — listed as the authoritative MCP build guide in the original prompt, but was not present on the build machine. The Python MCP SDK README was used instead.

---

## Agent Instructions
- Read this CLAUDE.md before starting any work on this repo.
- Do not lift phase or tier restrictions without an explicit prompt authorizing it.
- Do not add Tier 1+ tools without an explicit prompt authorizing it.
- Do not add Tier 3 capabilities ever without a new constitutional prompt.
- All tests must pass before reporting done.
