from __future__ import annotations

import datetime
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


def _parse_datetime(s: str) -> datetime.datetime:
    """Parse ISO datetime, truncating nanoseconds to microseconds for Python compat."""
    s = re.sub(r"(\.\d{6})\d+", r"\1", s)
    s = s.replace("Z", "+00:00")
    return datetime.datetime.fromisoformat(s)


class SandboxState(str, Enum):
    LIVE = "live"
    RUNNING = "running"
    PAUSED = "paused"
    CREATING = "creating"
    KILLED = "killed"


@dataclass
class SandboxInfo:
    sandbox_id: str
    template_id: str
    name: str
    metadata: Dict[str, str] = field(default_factory=dict)
    started_at: Optional[datetime.datetime] = None
    end_at: Optional[datetime.datetime] = None
    state: SandboxState = SandboxState.RUNNING

    def to_dict(self) -> Dict[str, Any]:
        return {
            "sandbox_id": self.sandbox_id,
            "template_id": self.template_id,
            "name": self.name,
            "metadata": self.metadata,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "end_at": self.end_at.isoformat() if self.end_at else None,
            "state": self.state.value,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> SandboxInfo:
        started_at = None
        if data.get("started_at"):
            started_at = _parse_datetime(data["started_at"])
        end_at = None
        if data.get("end_at"):
            end_at = _parse_datetime(data["end_at"])
        return cls(
            sandbox_id=data["sandbox_id"],
            template_id=data["template_id"],
            name=data.get("name", ""),
            metadata=data.get("metadata", {}),
            started_at=started_at,
            end_at=end_at,
            state=SandboxState(data.get("state", "running")),
        )


@dataclass
class SandboxMetrics:
    timestamp: datetime.datetime
    cpu_usage_percent: float = 0.0
    memory_usage_mb: float = 0.0
    disk_usage_mb: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp.isoformat(),
            "cpu_usage_percent": self.cpu_usage_percent,
            "memory_usage_mb": self.memory_usage_mb,
            "disk_usage_mb": self.disk_usage_mb,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> SandboxMetrics:
        return cls(
            timestamp=datetime.datetime.fromisoformat(data["timestamp"]),
            cpu_usage_percent=data.get("cpu_usage_percent", 0.0),
            memory_usage_mb=data.get("memory_usage_mb", 0.0),
            disk_usage_mb=data.get("disk_usage_mb", 0.0),
        )


@dataclass
class SandboxQuery:
    metadata: Optional[Dict[str, str]] = None
    state: Optional[List[SandboxState]] = None

    def to_dict(self) -> Dict[str, Any]:
        result: Dict[str, Any] = {}
        if self.metadata is not None:
            result["metadata"] = self.metadata
        if self.state is not None:
            result["state"] = [s.value for s in self.state]
        return result


@dataclass
class SnapshotInfo:
    snapshot_id: str
    sandbox_id: str
    created_at: Optional[datetime.datetime] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "snapshot_id": self.snapshot_id,
            "sandbox_id": self.sandbox_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> SnapshotInfo:
        created_at = None
        if data.get("created_at"):
            created_at = datetime.datetime.fromisoformat(data["created_at"])
        return cls(
            snapshot_id=data["snapshot_id"],
            sandbox_id=data["sandbox_id"],
            created_at=created_at,
        )


@dataclass
class Snapshot:
    """Metadata for a manual/pause/periodic sandbox snapshot."""

    snapshot_id: str
    sandbox_id: str
    source: str  # "periodic" | "pause" | "manual"
    mem_blob_key: str
    vmstate_blob_key: str
    mem_size_bytes: Optional[int]
    pause_duration_ms: Optional[int]
    created_at: str

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Snapshot":
        return cls(
            snapshot_id=d["snapshot_id"],
            sandbox_id=d["sandbox_id"],
            source=d["source"],
            mem_blob_key=d.get("mem_blob_key", ""),
            vmstate_blob_key=d.get("vmstate_blob_key", ""),
            mem_size_bytes=d.get("mem_size_bytes"),
            pause_duration_ms=d.get("pause_duration_ms"),
            created_at=d.get("created_at", ""),
        )


@dataclass
class SandboxLifecycle:
    on_timeout: str = "kill"
    auto_resume: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "on_timeout": self.on_timeout,
            "auto_resume": self.auto_resume,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> SandboxLifecycle:
        return cls(
            on_timeout=data.get("on_timeout", "kill"),
            auto_resume=data.get("auto_resume", False),
        )
