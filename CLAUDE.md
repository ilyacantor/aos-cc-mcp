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

### Phase-Gating
This repo is phase-gated. Each phase lands as its own prompt, its own CC session, its own review. Phases are not batched. Any future CC session working on this repo must read this CLAUDE.md at startup and must not lift phase or tier restrictions without an explicit prompt authorizing it.

---

## Current Phase: 1a — Scaffolding and JSONL Parser

### In scope
- Repo scaffolding (pyproject.toml, src layout, tests)
- FastMCP server skeleton (zero tools, imports and instantiates cleanly)
- JSONL session log parser (reads real CC session files, produces typed events)
- Tests against real fixture data

### Out of scope (deferred to later phases)
- MCP tools (no @mcp.tool decorators)
- Auth (no bearer tokens, no session tokens)
- Network (no Tailscale, no HTTP)
- Writes (no file writes, no session launches)
- Mode system (no Plan/Approve/YOLO enforcement)
- Audit log
- Kill switch

See [DEFERRED.md](DEFERRED.md) for the full phase roadmap.

---

## Authoritative References
- MCP server construction: Python MCP SDK README (https://github.com/modelcontextprotocol/python-sdk)
- `/mnt/skills/examples/mcp-builder/SKILL.md` — listed as the authoritative MCP build guide in the original prompt, but was not present on the build machine. The Python MCP SDK README was used instead.

---

## Agent Instructions
- Read this CLAUDE.md before starting any work on this repo.
- Do not lift phase or tier restrictions without an explicit prompt authorizing it.
- Do not add @mcp.tool decorators until Phase 2 authorizes it.
- Do not add Tier 3 capabilities ever without a new constitutional prompt.
- All tests must pass before reporting done.
