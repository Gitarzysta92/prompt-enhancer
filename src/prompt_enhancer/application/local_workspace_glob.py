"""Portable, root-anchored glob matching without filesystem traversal."""

from __future__ import annotations

import fnmatch
import os
from pathlib import PurePosixPath, PureWindowsPath

from .local_agent_limits import LocalAgentError, MAX_SEARCH_DEPTH


class WorkspaceGlob:
    def __init__(self, pattern: str) -> None:
        windows = PureWindowsPath(pattern)
        if (not pattern or len(pattern) > 1024 or windows.drive or windows.root
                or any(ord(char) < 32 or ord(char) == 127 or char == ":" for char in pattern)
                or (os.name != "nt" and "\\" in pattern)):
            raise LocalAgentError("workspace_glob_invalid")
        normalized = pattern.replace("\\", "/") if os.name == "nt" else pattern
        self.parts = PurePosixPath(normalized).parts
        if (not self.parts or len(self.parts) > MAX_SEARCH_DEPTH or ".." in self.parts
                or normalized.endswith("/")
                or any("**" in part and part != "**" for part in self.parts)):
            raise LocalAgentError("workspace_glob_invalid")

    def _closure(self, states: set[int]) -> set[int]:
        result = set(states)
        for start in states:
            while start < len(self.parts) and self.parts[start] == "**":
                start += 1
                result.add(start)
        return result

    def _states(self, path: PurePosixPath) -> set[int]:
        states = self._closure({0})
        for name in path.parts:
            following: set[int] = set()
            for position in states:
                if position == len(self.parts):
                    continue
                pattern = self.parts[position]
                if pattern == "**":
                    following.add(position)
                elif fnmatch.fnmatchcase(name.casefold() if os.name == "nt" else name,
                                        pattern.casefold() if os.name == "nt" else pattern):
                    following.add(position + 1)
            states = self._closure(following)
        return states

    def matches(self, path: PurePosixPath) -> bool:
        return len(self.parts) in self._states(path)

    def can_descend(self, path: PurePosixPath) -> bool:
        return any(position < len(self.parts) for position in self._states(path))
