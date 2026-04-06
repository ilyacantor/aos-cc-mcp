"""Tests for the append-only audit log."""

from __future__ import annotations

import json
from pathlib import Path

from aos_cc_mcp.audit import AuditLog


class TestAuditLogCreation:
    """Audit log creates its parent directory and file on first write."""

    def test_creates_parent_dir(self, tmp_path: Path) -> None:
        log_path = tmp_path / "subdir" / "audit.log"
        audit = AuditLog(log_path)
        audit.log(operation="test_op", mode="plan")
        assert log_path.exists()
        assert log_path.parent.is_dir()

    def test_file_does_not_exist_before_write(self, tmp_path: Path) -> None:
        log_path = tmp_path / "audit.log"
        AuditLog(log_path)
        assert not log_path.exists()


class TestAuditLogAppendOnly:
    """Audit log only appends — never overwrites or truncates."""

    def test_multiple_writes_append(self, tmp_path: Path) -> None:
        log_path = tmp_path / "audit.log"
        audit = AuditLog(log_path)

        audit.log(operation="op1", mode="plan")
        audit.log(operation="op2", mode="approve")
        audit.log(operation="op3", mode="yolo")

        entries = audit.read_entries()
        assert len(entries) == 3
        assert entries[0]["operation"] == "op1"
        assert entries[1]["operation"] == "op2"
        assert entries[2]["operation"] == "op3"

    def test_entries_are_jsonl(self, tmp_path: Path) -> None:
        log_path = tmp_path / "audit.log"
        audit = AuditLog(log_path)

        audit.log(operation="test", mode="plan")

        with log_path.open() as f:
            lines = f.readlines()
        assert len(lines) == 1
        parsed = json.loads(lines[0])
        assert parsed["operation"] == "test"


class TestAuditLogFields:
    """Audit entries contain all required fields."""

    def test_required_fields_present(self, tmp_path: Path) -> None:
        log_path = tmp_path / "audit.log"
        audit = AuditLog(log_path)

        audit.log(operation="test_op", mode="plan", success=True)

        entries = audit.read_entries()
        entry = entries[0]
        assert "timestamp" in entry
        assert entry["operation"] == "test_op"
        assert entry["mode"] == "plan"
        assert entry["success"] is True

    def test_optional_details(self, tmp_path: Path) -> None:
        log_path = tmp_path / "audit.log"
        audit = AuditLog(log_path)

        audit.log(operation="test", mode="plan", details={"key": "value"})

        entries = audit.read_entries()
        assert entries[0]["details"] == {"key": "value"}

    def test_error_field(self, tmp_path: Path) -> None:
        log_path = tmp_path / "audit.log"
        audit = AuditLog(log_path)

        audit.log(operation="test", mode="plan", success=False, error="something broke")

        entries = audit.read_entries()
        assert entries[0]["success"] is False
        assert entries[0]["error"] == "something broke"

    def test_no_error_or_details_when_not_provided(self, tmp_path: Path) -> None:
        log_path = tmp_path / "audit.log"
        audit = AuditLog(log_path)

        audit.log(operation="test", mode="plan")

        entries = audit.read_entries()
        assert "error" not in entries[0]
        assert "details" not in entries[0]


class TestAuditLogReadEntries:
    """read_entries returns all entries in order."""

    def test_empty_log(self, tmp_path: Path) -> None:
        log_path = tmp_path / "audit.log"
        audit = AuditLog(log_path)
        assert audit.read_entries() == []

    def test_preserves_order(self, tmp_path: Path) -> None:
        log_path = tmp_path / "audit.log"
        audit = AuditLog(log_path)

        for i in range(10):
            audit.log(operation=f"op_{i}", mode="plan")

        entries = audit.read_entries()
        assert len(entries) == 10
        for i, entry in enumerate(entries):
            assert entry["operation"] == f"op_{i}"
