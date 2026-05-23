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

### Tier 0 Shell Exceptions
`diff_intent_vs_execution` shells out to `git ls-files` in the session's project directory to build a lookup set of tracked file paths. This is a read-only operation with no side effects. It is the only place in the codebase where a Tier 0 tool executes a shell command, and it is whitelisted by design for this specific purpose. If the `git` call fails or returns nothing, the tool falls back to filename-regex extraction. No other shell commands are permitted in Tier 0 tools.

### Phase-Gating
This repo is phase-gated. Each phase lands as its own prompt, its own CC session, its own review. Phases are not batched. Any future CC session working on this repo must read this CLAUDE.md at startup and must not lift phase or tier restrictions without an explicit prompt authorizing it.

---

## Current Phase: 3a — First Tier 2 Write Tool

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
| `dispatch_cc_session` | T2 | Spawn a headless CC subprocess with a prompt, wait for completion, return session ID |

Tier 0 tools are read-only and always available. Tier 2 tools require Approve or YOLO mode (blocked in Plan). All tools registered via `register_tool_tier()` in `src/aos_cc_mcp/tools.py`.

### Tier 2 Tools — Constitutional Constraints

`dispatch_cc_session` is the first Tier 2 tool. It spawns `claude -p <prompt>` as a subprocess in a repo under `/home/ilyac/code/`, waits for completion, and returns the session ID for follow-up reads via the Tier 0 tools. Implementation lives in `src/aos_cc_mcp/dispatch.py`.

Constitutional constraints on this tool (and any future Tier 2 tools following this pattern):
- **No shell interpolation.** The prompt is passed as a single argv element to `subprocess.Popen` in list form. Never `shell=True`, never string interpolation.
- **Closed-enum arguments.** The `model` parameter is restricted to `{sonnet, opus, haiku}`. The `repo` parameter is restricted to `[a-zA-Z0-9_-]` and resolved against the hardcoded prefix `/home/ilyac/code/`.
- **No surface expansion.** No parameters that let the caller influence subprocess argv, env, cwd, or stdin beyond the spec.
- **Structured returns.** Every response is a dict with fixed keys. Errors are structured, not exceptions.
- **Audit without leaking.** The tool writes a completion entry to the audit log with dispatch metadata (repo, exit_code, duration, session_id, timed_out) but never logs the prompt content in the completion entry (already captured by middleware).

### Transport Configuration

Transport is selected via `AOS_CC_MCP_TRANSPORT` environment variable:
- `stdio` (default) — local stdio transport, no token required.
- `http` — Streamable HTTP on 127.0.0.1:8765, bearer token required.

HTTP transport refuses to start when `AOS_CC_MCP_TOKEN` is unset. See `.env.example` for configuration template.

The server reads `.env` from the repo root via python-dotenv on startup.

### Process Management

The server runs under pm2 (`ecosystem.config.cjs`). pm2 handles autorestart and log management.

### Completed (Phase 1a + 1b + 2a + 2a.1 + 2b + 3a)
- Repo scaffolding (pyproject.toml, src layout, tests)
- FastMCP server skeleton with stdio transport
- JSONL session log parser (reads real CC session files, produces typed events)
- Append-only audit log, kill switch, bearer token auth, mode system
- Middleware wiring (audit + mode enforcement on all tool calls)
- 7 Tier 0 read-only tools with full test coverage
- Anomaly detection engine (7 rules, hand-crafted fixtures)
- Phase 2a.1 reshape: datetime fixes, anomaly false positive reduction, git ls-files lookup for diff_intent_vs_execution, field renames, commit_count, tool_use_id correlation
- Phase 2b: Streamable HTTP transport (env var toggle), token enforcement for HTTP, python-dotenv, pm2 supervision, Tailscale Funnel exposure, coordinator handoff doc
- Phase 3a: `dispatch_cc_session` — first Tier 2 write tool with constitutional constraint discipline

### Out of scope (deferred to later phases)
- Tier 1 write tools (append_to_deferred, write_coordinator_note, log_decision)
- Additional Tier 2 tools (stage_files_for_review, create_file)
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

---

# Branch hygiene (B17)

- Feature branches are merged to dev and deleted in the same session they are created.
- Unmerged branches at session end are a B17 failure and must be reported.
- `--no-verify` is banned. If a hook blocks a legitimate change, fix the hook scope, then commit.
- Session start: run `git fetch --all --prune && git branch -a` and report stale branches before new work.

## Test result reporting

Before claiming a suite is green/passing/done:
1. Quote the final pytest summary line verbatim ("X passed, Y failed in Zs")
2. If that line is absent from tool output, state: "Suite did not complete. Partial signal: <what was actually observed>"
3. Never map per-test or per-file pass counts to suite-level claims. "test_smoke 6/6" = "6 of 6 smoke tests passed; full suite status unknown" — never "green"
4. No "honest deviation" / "spot-checked" / "looks good" framing as a substitute for the summary line
5. Same rule for any long-running command: no completion claim without the final stdout/exit-code evidence in-context
