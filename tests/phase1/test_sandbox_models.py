import datetime
import json

from declaw import (
    SandboxInfo,
    SandboxLifecycle,
    SandboxMetrics,
    SandboxQuery,
    SandboxState,
    SnapshotInfo,
)


class TestSandboxState:
    def test_enum_values(self):
        assert SandboxState.RUNNING == "running"
        assert SandboxState.PAUSED == "paused"
        assert SandboxState.CREATING == "creating"
        assert SandboxState.KILLED == "killed"


class TestSandboxInfo:
    def test_construction(self):
        info = SandboxInfo(sandbox_id="sbx-1", template_id="tpl-1", name="base")
        assert info.sandbox_id == "sbx-1"
        assert info.state == SandboxState.RUNNING

    def test_round_trip(self):
        now = datetime.datetime(2026, 1, 1, 12, 0, 0)
        info = SandboxInfo(
            sandbox_id="sbx-1",
            template_id="tpl-1",
            name="test",
            metadata={"key": "val"},
            started_at=now,
            state=SandboxState.PAUSED,
        )
        d = info.to_dict()
        restored = SandboxInfo.from_dict(d)
        assert restored.sandbox_id == "sbx-1"
        assert restored.state == SandboxState.PAUSED
        assert restored.metadata == {"key": "val"}
        assert restored.started_at == now

    def test_json_serializable(self):
        info = SandboxInfo(sandbox_id="sbx-1", template_id="tpl-1", name="base")
        s = json.dumps(info.to_dict())
        assert "sbx-1" in s


class TestSandboxMetrics:
    def test_round_trip(self):
        now = datetime.datetime(2026, 3, 18, 10, 0, 0)
        m = SandboxMetrics(timestamp=now, cpu_usage_percent=45.2, memory_usage_mb=512.0)
        restored = SandboxMetrics.from_dict(m.to_dict())
        assert restored.cpu_usage_percent == 45.2
        assert restored.memory_usage_mb == 512.0


class TestSandboxQuery:
    def test_empty(self):
        q = SandboxQuery()
        assert q.to_dict() == {}

    def test_with_filters(self):
        q = SandboxQuery(
            metadata={"env": "prod"},
            state=[SandboxState.RUNNING, SandboxState.PAUSED],
        )
        d = q.to_dict()
        assert d["metadata"] == {"env": "prod"}
        assert "running" in d["state"]
        assert "paused" in d["state"]


class TestSnapshotInfo:
    def test_round_trip(self):
        now = datetime.datetime(2026, 6, 15, 8, 30, 0)
        snap = SnapshotInfo(snapshot_id="snap-1", sandbox_id="sbx-1", created_at=now)
        restored = SnapshotInfo.from_dict(snap.to_dict())
        assert restored.snapshot_id == "snap-1"
        assert restored.created_at == now


class TestSandboxLifecycle:
    def test_defaults(self):
        lc = SandboxLifecycle()
        assert lc.on_timeout == "kill"
        assert lc.auto_resume is False

    def test_pause_with_resume(self):
        lc = SandboxLifecycle(on_timeout="pause", auto_resume=True)
        d = lc.to_dict()
        assert d["on_timeout"] == "pause"
        assert d["auto_resume"] is True
        restored = SandboxLifecycle.from_dict(d)
        assert restored.on_timeout == "pause"
        assert restored.auto_resume is True
