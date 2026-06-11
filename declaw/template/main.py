from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class CopyItem:
    src: str
    dst: str
    mode: Optional[int] = None


@dataclass
class TemplateBase:
    """Builder for defining sandbox templates via a fluent API."""

    _base_image: str = "ubuntu:22.04"
    _run_cmds: List[List[str]] = field(default_factory=list)
    _copies: List[CopyItem] = field(default_factory=list)
    _envs: Dict[str, str] = field(default_factory=dict)
    _apt_packages: List[str] = field(default_factory=list)
    _start_cmd: Optional[str] = None
    _start_cmd_ready: Optional[Any] = None
    # When set, the server uses this Dockerfile verbatim and ignores the
    # helper fields above. Use for multi-stage builds, ARG, ONBUILD, etc.
    _dockerfile: Optional[str] = None

    def from_base_image(self, image: str = "ubuntu:22.04") -> TemplateBase:
        self._base_image = image
        return self

    def from_dockerfile(self, content: str) -> TemplateBase:
        """Use a raw Dockerfile string instead of the structured helpers.

        When set, all other ``apt_install`` / ``run_cmd`` / ``set_envs`` /
        ``copy`` / ``set_start_cmd`` / ``from_base_image`` calls on this
        spec are ignored — the Dockerfile is sent to the build worker
        verbatim.

        Args:
            content: The full Dockerfile contents. Must contain a
                ``FROM`` instruction. Capped server-side at 64 KiB.
        """
        self._dockerfile = content
        return self

    def run_cmd(self, cmds: List[str]) -> TemplateBase:
        self._run_cmds.append(cmds)
        return self

    def copy(self, src: str, dst: str, mode: Optional[int] = None) -> TemplateBase:
        self._copies.append(CopyItem(src=src, dst=dst, mode=mode))
        return self

    def set_envs(self, envs: Dict[str, str]) -> TemplateBase:
        self._envs.update(envs)
        return self

    def apt_install(self, *packages: str) -> TemplateBase:
        self._apt_packages.extend(packages)
        return self

    def set_start_cmd(self, cmd: str, ready_check: Optional[Any] = None) -> TemplateBase:
        self._start_cmd = cmd
        self._start_cmd_ready = ready_check
        return self

    def to_dict(self) -> Dict[str, Any]:
        # Raw Dockerfile path: send only the dockerfile field; the server
        # ignores helpers when this is set.
        if self._dockerfile is not None:
            return {"dockerfile": self._dockerfile}
        result: Dict[str, Any] = {"base_image": self._base_image}
        if self._run_cmds:
            # Server expects each run_cmd as a single shell line. The
            # helper accepts both styles — ``run_cmd(["pip3 install x"])``
            # and ``run_cmd(["pip3", "install", "x"])`` — and we
            # space-join the inner list so both serialize the same. (#233)
            result["run_cmds"] = [" ".join(group) for group in self._run_cmds]
        if self._copies:
            result["copies"] = [{"src": c.src, "dst": c.dst, "mode": c.mode} for c in self._copies]
        if self._envs:
            result["envs"] = self._envs
        if self._apt_packages:
            result["apt_packages"] = self._apt_packages
        if self._start_cmd:
            result["start_cmd"] = self._start_cmd
        return result


@dataclass
class BuildInfo:
    build_id: str
    status: str
    template_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "build_id": self.build_id,
            "status": self.status,
            "template_id": self.template_id,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> BuildInfo:
        return cls(
            build_id=data["build_id"],
            status=data["status"],
            template_id=data.get("template_id"),
        )


@dataclass
class TemplateBuildStatus:
    build_id: str
    status: str
    logs: List[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> TemplateBuildStatus:
        return cls(
            build_id=data["build_id"],
            status=data["status"],
            logs=data.get("logs", []),
        )
