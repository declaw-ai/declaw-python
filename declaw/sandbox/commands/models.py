from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass
class Stdout:
    line: str
    timestamp: Optional[float] = None


@dataclass
class Stderr:
    line: str
    timestamp: Optional[float] = None


@dataclass
class CommandResult:
    stdout: str = ""
    stderr: str = ""
    exit_code: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "stdout": self.stdout,
            "stderr": self.stderr,
            "exit_code": self.exit_code,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> CommandResult:
        return cls(
            stdout=data.get("stdout", ""),
            stderr=data.get("stderr", ""),
            exit_code=data.get("exit_code", 0),
        )


@dataclass
class PtySize:
    cols: int = 80
    rows: int = 24

    def to_dict(self) -> Dict[str, Any]:
        return {"cols": self.cols, "rows": self.rows}


@dataclass
class PtyOutput:
    data: bytes = b""

    def to_dict(self) -> Dict[str, Any]:
        return {"data": self.data.decode("utf-8", errors="replace")}


@dataclass
class ProcessInfo:
    pid: int
    cmd: str
    is_pty: bool = False
    envs: Dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "pid": self.pid,
            "cmd": self.cmd,
            "is_pty": self.is_pty,
            "envs": self.envs,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ProcessInfo:
        return cls(
            pid=data["pid"],
            cmd=data.get("cmd", ""),
            is_pty=data.get("is_pty", False),
            envs=data.get("envs", {}),
        )


Username = str
DEFAULT_USERNAME: Username = "user"
