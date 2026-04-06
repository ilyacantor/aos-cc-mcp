"""Tests for the mode system state machine."""

from __future__ import annotations

from aos_cc_mcp.modes import Mode, ModeManager, Tier, ToolDecision


class TestModeDefaults:
    """Mode manager always starts in Plan mode."""

    def test_default_mode_is_plan(self) -> None:
        mm = ModeManager()
        assert mm.mode == Mode.PLAN

    def test_fresh_instance_is_always_plan(self) -> None:
        for _ in range(5):
            assert ModeManager().mode == Mode.PLAN


class TestModeTransitions:
    """Mode can be set to any valid mode."""

    def test_set_to_approve(self) -> None:
        mm = ModeManager()
        mm.set_mode(Mode.APPROVE)
        assert mm.mode == Mode.APPROVE

    def test_set_to_yolo(self) -> None:
        mm = ModeManager()
        mm.set_mode(Mode.YOLO)
        assert mm.mode == Mode.YOLO

    def test_set_back_to_plan(self) -> None:
        mm = ModeManager()
        mm.set_mode(Mode.YOLO)
        mm.set_mode(Mode.PLAN)
        assert mm.mode == Mode.PLAN


class TestTier3AlwaysBlocked:
    """Tier 3 is constitutionally prohibited in every mode."""

    def test_plan_blocks_t3(self) -> None:
        mm = ModeManager()
        assert mm.evaluate(Tier.T3) == ToolDecision.BLOCKED_BY_TIER

    def test_approve_blocks_t3(self) -> None:
        mm = ModeManager()
        mm.set_mode(Mode.APPROVE)
        assert mm.evaluate(Tier.T3) == ToolDecision.BLOCKED_BY_TIER

    def test_yolo_blocks_t3(self) -> None:
        mm = ModeManager()
        mm.set_mode(Mode.YOLO)
        assert mm.evaluate(Tier.T3) == ToolDecision.BLOCKED_BY_TIER


class TestTier0AlwaysAllowed:
    """Tier 0 read tools are allowed in every mode."""

    def test_plan_allows_t0(self) -> None:
        mm = ModeManager()
        assert mm.evaluate(Tier.T0) == ToolDecision.ALLOWED

    def test_approve_allows_t0(self) -> None:
        mm = ModeManager()
        mm.set_mode(Mode.APPROVE)
        assert mm.evaluate(Tier.T0) == ToolDecision.ALLOWED

    def test_yolo_allows_t0(self) -> None:
        mm = ModeManager()
        mm.set_mode(Mode.YOLO)
        assert mm.evaluate(Tier.T0) == ToolDecision.ALLOWED


class TestPlanModeBlocksWrites:
    """Plan mode blocks all write tiers (T1, T2)."""

    def test_plan_blocks_t1(self) -> None:
        mm = ModeManager()
        assert mm.evaluate(Tier.T1) == ToolDecision.BLOCKED_BY_MODE

    def test_plan_blocks_t2(self) -> None:
        mm = ModeManager()
        assert mm.evaluate(Tier.T2) == ToolDecision.BLOCKED_BY_MODE


class TestApproveModeNeedsConfirmation:
    """Approve mode requires confirmation for write tiers."""

    def test_approve_confirms_t1(self) -> None:
        mm = ModeManager()
        mm.set_mode(Mode.APPROVE)
        assert mm.evaluate(Tier.T1) == ToolDecision.NEEDS_CONFIRMATION

    def test_approve_confirms_t2(self) -> None:
        mm = ModeManager()
        mm.set_mode(Mode.APPROVE)
        assert mm.evaluate(Tier.T2) == ToolDecision.NEEDS_CONFIRMATION


class TestYoloModeAllowsWrites:
    """YOLO mode allows all non-T3 tiers without confirmation."""

    def test_yolo_allows_t1(self) -> None:
        mm = ModeManager()
        mm.set_mode(Mode.YOLO)
        assert mm.evaluate(Tier.T1) == ToolDecision.ALLOWED

    def test_yolo_allows_t2(self) -> None:
        mm = ModeManager()
        mm.set_mode(Mode.YOLO)
        assert mm.evaluate(Tier.T2) == ToolDecision.ALLOWED


class TestFullModeMatrix:
    """Complete matrix: every mode x every tier."""

    def test_full_matrix(self) -> None:
        expected = {
            (Mode.PLAN, Tier.T0): ToolDecision.ALLOWED,
            (Mode.PLAN, Tier.T1): ToolDecision.BLOCKED_BY_MODE,
            (Mode.PLAN, Tier.T2): ToolDecision.BLOCKED_BY_MODE,
            (Mode.PLAN, Tier.T3): ToolDecision.BLOCKED_BY_TIER,
            (Mode.APPROVE, Tier.T0): ToolDecision.ALLOWED,
            (Mode.APPROVE, Tier.T1): ToolDecision.NEEDS_CONFIRMATION,
            (Mode.APPROVE, Tier.T2): ToolDecision.NEEDS_CONFIRMATION,
            (Mode.APPROVE, Tier.T3): ToolDecision.BLOCKED_BY_TIER,
            (Mode.YOLO, Tier.T0): ToolDecision.ALLOWED,
            (Mode.YOLO, Tier.T1): ToolDecision.ALLOWED,
            (Mode.YOLO, Tier.T2): ToolDecision.ALLOWED,
            (Mode.YOLO, Tier.T3): ToolDecision.BLOCKED_BY_TIER,
        }

        for (mode, tier), expected_decision in expected.items():
            mm = ModeManager()
            mm.set_mode(mode)
            actual = mm.evaluate(tier)
            assert actual == expected_decision, (
                f"Mode={mode.value}, Tier=T{tier.value}: "
                f"expected {expected_decision.value}, got {actual.value}"
            )
