from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, Optional, Union


class FileType(str, Enum):
    FILE = "file"
    DIR = "dir"


@dataclass
class EntryInfo:
    name: str
    path: str
    type: FileType
    size: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "path": self.path,
            "type": self.type.value,
            "size": self.size,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> EntryInfo:
        return cls(
            name=data["name"],
            path=data["path"],
            type=FileType(data.get("type", "file")),
            size=data.get("size", 0),
        )


@dataclass
class WriteInfo:
    path: str
    size: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {"path": self.path, "size": self.size}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> WriteInfo:
        return cls(path=data["path"], size=data.get("size", 0))


@dataclass
class WriteEntry:
    path: str
    data: Union[str, bytes]

    def to_dict(self) -> Dict[str, Any]:
        # Batch endpoint is JSON string-only. Callers (e.g. Filesystem.write_files)
        # must route bytes entries to PUT /files/raw before calling this.
        if not isinstance(self.data, str):
            raise TypeError(
                "WriteEntry.to_dict() is for the JSON batch endpoint and requires str data. "
                "Bytes entries are dispatched via PUT /files/raw and should not be serialized."
            )
        return {"path": self.path, "data": self.data}


class FilesystemEventType(str, Enum):
    CREATE = "create"
    WRITE = "write"
    REMOVE = "remove"
    RENAME = "rename"
    CHMOD = "chmod"


@dataclass
class FilesystemEvent:
    type: FilesystemEventType
    path: str
    timestamp: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": self.type.value,
            "path": self.path,
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> FilesystemEvent:
        return cls(
            type=FilesystemEventType(data["type"]),
            path=data["path"],
            timestamp=data.get("timestamp"),
        )
