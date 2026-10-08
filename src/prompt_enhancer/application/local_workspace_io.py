"""Bounded inspection of the admitted workspace through no-follow handles.

Windows pins every path component against writes/rename until inspection ends.
POSIX uses directory-relative descriptors and O_NOFOLLOW. Cancellation is
cooperative between bounded operations; it cannot preempt a stalled OS call.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
import errno
import os
from pathlib import Path
import stat

from .local_agent_limits import LocalAgentError
from .runtime_cancellation import RuntimeCooperativeStop, current_runtime_cancellation


def check_workspace_cancellation() -> None:
    cancellation = current_runtime_cancellation()
    if cancellation is not None and cancellation.is_set():
        raise RuntimeCooperativeStop("workspace_inspection_cancelled")


def is_link_or_reparse(metadata: os.stat_result) -> bool:
    return stat.S_ISLNK(metadata.st_mode) or bool(getattr(metadata, "st_file_attributes", 0) & 0x400)


def _identity(metadata: os.stat_result) -> tuple[int, int]:
    return metadata.st_dev, metadata.st_ino


def _revision(metadata: os.stat_result) -> tuple[int, ...]:
    return (*_identity(metadata), metadata.st_size, metadata.st_mtime_ns, metadata.st_ctime_ns, metadata.st_nlink)


@dataclass(frozen=True, slots=True)
class InspectedEntry:
    path: Path
    metadata: os.stat_result | None


@dataclass(frozen=True, slots=True)
class InspectedFile:
    payload: bytes
    metadata: os.stat_result
    truncated: bool


class WorkspaceIO:
    def __init__(self, root: Path) -> None:
        self.root = root
        self._root_identity: tuple[int, int] | None = None
        try:
            with self._directory(root, lambda: None) as descriptor:
                self._root_identity = _identity(os.fstat(descriptor))
        except OSError as error:
            raise LocalAgentError("workspace_directory_unavailable") from error

    @contextmanager
    def _directory(
        self,
        target: Path,
        check: Callable[[], None],
        *,
        mutation: bool = False,
    ) -> Iterator[int]:
        if not target.is_relative_to(self.root):
            raise LocalAgentError("path_outside_workspace")
        with ExitStack() as stack:
            parent: int | None = None
            # Start at the volume/root: checking only the final component would
            # still follow a swapped intermediate junction or symbolic link.
            for component in reversed((target, *target.parents)):
                check()
                if os.name == "nt":
                    from .local_workspace_windows import (
                        open_mutation_directory_descriptor,
                        open_read_descriptor,
                    )

                    descriptor = (
                        open_mutation_directory_descriptor(component)
                        if mutation and component == target
                        else open_read_descriptor(component, directory=True)
                    )
                else:
                    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
                    try:
                        descriptor = os.open(component if parent is None else component.name, flags, dir_fd=parent)
                    except OSError as error:
                        if error.errno == errno.ELOOP:
                            raise LocalAgentError("workspace_link_or_reparse_refused") from error
                        raise
                stack.callback(os.close, descriptor)
                metadata = os.fstat(descriptor)
                if is_link_or_reparse(metadata) or not stat.S_ISDIR(metadata.st_mode):
                    raise LocalAgentError("workspace_link_or_reparse_refused")
                if component == self.root and self._root_identity is not None and _identity(metadata) != self._root_identity:
                    raise LocalAgentError("workspace_root_changed")
                parent = descriptor
            assert parent is not None
            check()
            yield parent

    @contextmanager
    def _directory_pair(
        self,
        left: Path,
        right: Path,
        check: Callable[[], None],
        *,
        mutation: bool = False,
    ) -> Iterator[tuple[int, int]]:
        """Pin two directory chains while opening their shared ancestors once."""

        if not left.is_relative_to(self.root) or not right.is_relative_to(self.root):
            raise LocalAgentError("path_outside_workspace")

        def chain(target: Path) -> tuple[Path, ...]:
            return tuple(reversed((target, *target.parents)))

        left_chain = chain(left)
        right_chain = chain(right)
        shared = 0
        while (
            shared < len(left_chain)
            and shared < len(right_chain)
            and left_chain[shared] == right_chain[shared]
        ):
            shared += 1
        if shared == 0:
            raise LocalAgentError("path_outside_workspace")

        with ExitStack() as stack:
            def opened(component: Path, parent: int | None, *, final_mutation: bool) -> int:
                check()
                if os.name == "nt":
                    from .local_workspace_windows import (
                        open_mutation_directory_descriptor,
                        open_read_descriptor,
                    )

                    descriptor = (
                        open_mutation_directory_descriptor(component)
                        if final_mutation
                        else open_read_descriptor(component, directory=True)
                    )
                else:
                    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
                    try:
                        descriptor = os.open(
                            component if parent is None else component.name,
                            flags,
                            dir_fd=parent,
                        )
                    except OSError as error:
                        if error.errno == errno.ELOOP:
                            raise LocalAgentError("workspace_link_or_reparse_refused") from error
                        raise
                stack.callback(os.close, descriptor)
                metadata = os.fstat(descriptor)
                if is_link_or_reparse(metadata) or not stat.S_ISDIR(metadata.st_mode):
                    raise LocalAgentError("workspace_link_or_reparse_refused")
                if (
                    component == self.root
                    and self._root_identity is not None
                    and _identity(metadata) != self._root_identity
                ):
                    raise LocalAgentError("workspace_root_changed")
                return descriptor

            parent: int | None = None
            for component in left_chain[:shared]:
                parent = opened(
                    component,
                    parent,
                    final_mutation=mutation and component in {left, right},
                )
            assert parent is not None
            common_parent = parent

            def branch(parts: tuple[Path, ...]) -> int:
                branch_parent = common_parent
                if len(parts) == shared:
                    return branch_parent
                for index, component in enumerate(parts[shared:]):
                    branch_parent = opened(
                        component,
                        branch_parent,
                        final_mutation=mutation and index == len(parts[shared:]) - 1,
                    )
                return branch_parent

            left_descriptor = branch(left_chain)
            right_descriptor = left_descriptor if left == right else branch(right_chain)
            check()
            yield left_descriptor, right_descriptor

    @staticmethod
    def _stat_entry(path: Path, parent: int) -> os.stat_result:
        return path.lstat() if os.name == "nt" else os.stat(path.name, dir_fd=parent, follow_symlinks=False)

    def entries(self, target: Path, *, limit: int, check: Callable[[], None] = check_workspace_cancellation
                ) -> tuple[tuple[InspectedEntry, ...], bool]:
        """Inspect at most limit entries; one lookahead establishes truncation."""
        results: list[InspectedEntry] = []
        with self._directory(target, check) as parent:
            # Path.iterdir used listdir on older supported Python releases;
            # scandir keeps enumeration lazy on every supported interpreter.
            with os.scandir(target if os.name == "nt" else parent) as iterator:
                for entry in iterator:
                    check()
                    if len(results) >= limit:
                        return tuple(results), False
                    candidate = target / entry.name
                    try:
                        metadata = self._stat_entry(candidate, parent)
                    except OSError:
                        metadata = None
                    results.append(InspectedEntry(candidate, metadata))
                check()
                return tuple(results), True

    def directory_identity(
        self,
        target: Path,
        check: Callable[[], None] = check_workspace_cancellation,
    ) -> tuple[int, int]:
        """Return an opaque identity after opening every component no-follow."""

        with self._directory(target, check) as descriptor:
            check()
            return _identity(os.fstat(descriptor))

    def read(self, target: Path, *, limit: int, allow_prefix: bool = False, single_link: bool = False,
             check: Callable[[], None] = check_workspace_cancellation,
             consume: Callable[[int], None] | None = None) -> InspectedFile:
        check()
        if target == self.root:
            raise LocalAgentError("workspace_file_unavailable")
        with self._directory(target.parent, check) as parent:
            before_path = self._stat_entry(target, parent)
            if is_link_or_reparse(before_path):
                raise LocalAgentError("workspace_link_or_reparse_refused")
            if not stat.S_ISREG(before_path.st_mode) or (single_link and before_path.st_nlink != 1):
                raise LocalAgentError("workspace_file_unavailable")
            if os.name == "nt":
                from .local_workspace_windows import open_read_descriptor

                descriptor = open_read_descriptor(target, directory=False)
            else:
                try:
                    descriptor = os.open(target.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, dir_fd=parent)
                except OSError as error:
                    if error.errno == errno.ELOOP:
                        raise LocalAgentError("workspace_link_or_reparse_refused") from error
                    raise
            try:
                before = os.fstat(descriptor)
                if is_link_or_reparse(before) or not stat.S_ISREG(before.st_mode) or (single_link and before.st_nlink != 1):
                    raise LocalAgentError("workspace_file_unavailable")
                if _revision(before_path) != _revision(before):
                    raise LocalAgentError("workspace_file_changed")
                if before.st_size > limit and not allow_prefix:
                    raise LocalAgentError("workspace_file_too_large")
                payload = bytearray()
                maximum = limit + 1 if allow_prefix else limit
                while len(payload) < maximum:
                    check()
                    chunk = os.read(descriptor, min(65_536, maximum - len(payload)))
                    if not chunk:
                        break
                    if consume is not None:
                        consume(len(chunk))
                    payload.extend(chunk)
                after = os.fstat(descriptor)
                after_path = self._stat_entry(target, parent)
                check()
                if (_revision(before) != _revision(after) or _revision(after_path) != _revision(after)
                        or is_link_or_reparse(after_path) or len(payload) != min(after.st_size, maximum)):
                    raise LocalAgentError("workspace_file_changed")
                truncated = len(payload) > limit
                if truncated and not allow_prefix:
                    raise LocalAgentError("workspace_file_changed")
                return InspectedFile(bytes(payload[:limit]), after, truncated)
            finally:
                os.close(descriptor)
