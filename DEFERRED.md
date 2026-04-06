# AOS CC MCP — Deferred Phases

Each phase lands as its own prompt, its own CC session, its own review. Phases are not batched.

---

## Phase 1b: Security Foundation
- Append-only audit log (all operations logged, no log mutation)
- Kill switch env var (AOS_CC_MCP_DISABLED — server refuses all requests when set)
- Bearer token auth (server rejects unauthenticated requests)
- Mode system implementation (Plan/Approve/YOLO with server-enforced state machine)
- Default mode on startup is always Plan

## Phase 2: Tier 0 Read Tools
- `list_sessions` — enumerate available session logs
- `session_summary` — high-level summary of a session (event counts, duration, tools used)
- `read_session` — full parsed event stream for a session
- `search_sessions` — keyword/regex search across sessions
- `extract_commits` — find git commits made during a session
- `detect_anomalies` — flag unusual patterns (silent fallbacks, repeated failures, scope creep)
- `diff_intent_vs_execution` — compare what was asked vs what was done
- Tailscale Funnel integration (expose server to coordinator over Tailscale)
- Coordinator project registration (register this server with the AOS Coordinator on claude.ai)

## Phase 3: Tier 1 Write Tools
- `append_to_deferred` — append entries to DEFERRED.md files in repos under ~/code/
- `write_coordinator_note` — write to ~/aos-coordinator-notes/
- `log_decision` — append to the decision log
- Dry-run support (preview writes without executing)
- Rate limits (cap write frequency)
- Blast radius path validation (whitelist of writable paths, enforced at server level)

## Phase 4: Tier 2 Write Tools
- `launch_cc_session` — start a new Claude Code session with a prompt
- `stage_files_for_review` — prepare files for human review before commit
- `create_file` — create new files (not overwrite)
- Session token mechanism for YOLO mode (scoped, time-limited, revocable)
- Scope contract enforcement (tools declare what they will touch, server verifies)
- Mandatory post-execution diff reports (every write operation reports what changed)
- Rollback capability (undo last write operation)

---

## Parser observations from Phase 1a

- Assistant text/thinking blocks are currently classified as Unknown. If the coordinator later needs to reason about assistant reasoning (not just actions), add an AssistantMessage event type.
- CC harness-internal event types observed in real fixtures: custom-title, agent-name, queue-operation. Currently classified as Unknown with raw preserved. Revisit if subagent state becomes relevant to anomaly detection.
- Phase 2 `detect_anomalies` tool must correlate Bash ToolCall events with their corresponding ToolResult events by tool_use_id to determine command success/failure as a single fact.
