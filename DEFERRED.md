# AOS CC MCP — Deferred Phases

Each phase lands as its own prompt, its own CC session, its own review. Phases are not batched.

---

## Phase 2b: Network + Coordinator Registration
- Tailscale Funnel integration (expose server to coordinator over Tailscale)
- Coordinator project registration (register this server with the AOS Coordinator on claude.ai)
- Network transport auth guard (refuse to start with HTTP transport when AOS_CC_MCP_TOKEN is unset)

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

## Deferred from Phase 2a

- `scope_expansion` anomaly rule reserved but not implemented in Phase 2a; requires prompt-intent-to-file-edit correlation beyond current regex heuristic; revisit in Phase 3+ or after coordinator runtime data suggests a concrete rule shape.

## Parser observations from Phase 1a

- Assistant text/thinking blocks are currently classified as Unknown. If the coordinator later needs to reason about assistant reasoning (not just actions), add an AssistantMessage event type.
- CC harness-internal event types observed in real fixtures: custom-title, agent-name, queue-operation. Currently classified as Unknown with raw preserved. Revisit if subagent state becomes relevant to anomaly detection.
