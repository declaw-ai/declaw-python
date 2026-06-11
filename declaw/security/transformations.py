from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict

# Maximum allowed length for regex patterns to limit complexity.
MAX_PATTERN_LENGTH = 1000

# Detect regex patterns vulnerable to catastrophic backtracking (ReDoS).
# Checks for nested quantifiers like (a+)+, (a*)+, (a+)*, etc.
_REDOS_PATTERN = re.compile(r"(\(.*[+*].*\))[+*]|\(\?:[^)]*[+*][^)]*\)[+*]")


def check_redos(pattern: str) -> None:
    """Raise ValueError if the pattern contains nested quantifiers (ReDoS risk).

    Checks for patterns like ``(a+)+``, ``(a*)+``, ``(a|b)*c*`` wrapped in
    outer quantifiers, which can cause catastrophic backtracking.
    """
    if len(pattern) > MAX_PATTERN_LENGTH:
        raise ValueError(
            f"Regex pattern too long ({len(pattern)} chars, max {MAX_PATTERN_LENGTH})."
        )
    if _REDOS_PATTERN.search(pattern):
        raise ValueError(
            f"Regex pattern '{pattern}' contains nested quantifiers which may "
            "cause catastrophic backtracking (ReDoS). Simplify the pattern."
        )


class TransformDirection(str, Enum):
    OUTBOUND = "outbound"
    INBOUND = "inbound"
    BOTH = "both"


@dataclass
class TransformationRule:
    match: str
    replace: str
    direction: str = TransformDirection.OUTBOUND.value

    def __post_init__(self) -> None:
        valid_dirs = {d.value for d in TransformDirection}
        if self.direction not in valid_dirs:
            raise ValueError(f"Invalid direction: '{self.direction}'. Valid: {sorted(valid_dirs)}")
        # Check for ReDoS-vulnerable patterns before compiling
        check_redos(self.match)
        try:
            re.compile(self.match)
        except re.error as e:
            raise ValueError(f"Invalid regex pattern '{self.match}': {e}") from e

    def applies_to(self, direction: str) -> bool:
        if self.direction == TransformDirection.BOTH.value:
            return True
        return self.direction == direction

    def apply(self, text: str) -> str:
        return re.sub(self.match, self.replace, text)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "match": self.match,
            "replace": self.replace,
            "direction": self.direction,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> TransformationRule:
        return cls(
            match=data["match"],
            replace=data["replace"],
            direction=data.get("direction", TransformDirection.OUTBOUND.value),
        )
