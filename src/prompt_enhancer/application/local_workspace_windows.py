"""Non-inheritable Windows workspace handles that do not follow reparse points.

Each ancestor is held by the caller. Omitting write/delete sharing prevents
replacement or conversion of a checked component while an operation is in
progress. Reviewed writes keep private stages handle-owned, replace only while
the parent chain is pinned, and discard displaced/staged files by handle. No
privileges are enabled and no unguarded path fallback is used.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import msvcrt
import os
from pathlib import Path
import threading
import uuid

from .local_agent_limits import LocalAgentError


class _FileInformation(ctypes.Structure):
    _fields_ = [
        ("attributes", wintypes.DWORD),
        ("created", wintypes.FILETIME),
        ("accessed", wintypes.FILETIME),
        ("written", wintypes.FILETIME),
        ("volume", wintypes.DWORD),
        ("size_high", wintypes.DWORD),
        ("size_low", wintypes.DWORD),
        ("links", wintypes.DWORD),
        ("index_high", wintypes.DWORD),
        ("index_low", wintypes.DWORD),
    ]


_kernel = ctypes.WinDLL("kernel32", use_last_error=True)
_create = _kernel.CreateFileW
_create.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                   ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
_create.restype = wintypes.HANDLE
_information = _kernel.GetFileInformationByHandle
_information.argtypes = [wintypes.HANDLE, ctypes.POINTER(_FileInformation)]
_information.restype = wintypes.BOOL
_close = _kernel.CloseHandle
_close.argtypes = [wintypes.HANDLE]
_close.restype = wintypes.BOOL
_type = _kernel.GetFileType
_type.argtypes = [wintypes.HANDLE]
_type.restype = wintypes.DWORD
_set_information = _kernel.SetFileInformationByHandle
_set_information.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
_set_information.restype = wintypes.BOOL
_replace_file = _kernel.ReplaceFileW
_replace_file.argtypes = [
    wintypes.LPCWSTR,
    wintypes.LPCWSTR,
    wintypes.LPCWSTR,
    wintypes.DWORD,
    ctypes.c_void_p,
    ctypes.c_void_p,
]
_replace_file.restype = wintypes.BOOL
_get_final_path = _kernel.GetFinalPathNameByHandleW
_get_final_path.argtypes = [wintypes.HANDLE, wintypes.LPWSTR, wintypes.DWORD, wintypes.DWORD]
_get_final_path.restype = wintypes.DWORD
_INVALID = ctypes.c_void_p(-1).value

_DELETE = 0x00010000
_FILE_SHARE_READ = 0x00000001
_FILE_SHARE_WRITE = 0x00000002
_FILE_SHARE_DELETE = 0x00000004
_CREATE_NEW = 1
_OPEN_EXISTING = 3
_FILE_ATTRIBUTE_TEMPORARY = 0x00000100
_FILE_FLAG_BACKUP_SEMANTICS = 0x02000000
_FILE_FLAG_OPEN_REPARSE_POINT = 0x00200000
_FILE_DISPOSITION_INFO = 4
_FILE_DISPOSITION_INFO_EX = 21
_FILE_RENAME_INFO = 3
_FILE_DISPOSITION_DELETE = 0x00000001
_FILE_DISPOSITION_POSIX_SEMANTICS = 0x00000002
_FILE_DISPOSITION_IGNORE_READONLY_ATTRIBUTE = 0x00000010
_CLSCTX_INPROC_SERVER = 0x1
_COINIT_APARTMENTTHREADED = 0x2
_FOF_SILENT = 0x0004
_FOF_NOCONFIRMATION = 0x0010
_FOF_ALLOWUNDO = 0x0040
_FOF_NOERRORUI = 0x0400
_FOFX_RECYCLEONDELETE = 0x00080000
_FOFX_EARLYFAILURE = 0x00100000
_FOFX_ADDUNDORECORD = 0x20000000
_RECYCLE_OPERATION_TIMEOUT_SECONDS = 15.0


class RecycleOperationUnverified(OSError):
    """The Shell worker did not settle before the bounded verification deadline."""


class _Guid(ctypes.Structure):
    _fields_ = [
        ("data1", wintypes.DWORD),
        ("data2", wintypes.WORD),
        ("data3", wintypes.WORD),
        ("data4", ctypes.c_ubyte * 8),
    ]

    @classmethod
    def parse(cls, value: str) -> "_Guid":
        return cls.from_buffer_copy(uuid.UUID(value).bytes_le)


_ole32 = ctypes.OleDLL("ole32", use_last_error=True)
_co_initialize = _ole32.CoInitializeEx
_co_initialize.argtypes = [ctypes.c_void_p, wintypes.DWORD]
_co_initialize.restype = ctypes.c_long
_co_uninitialize = _ole32.CoUninitialize
_co_uninitialize.argtypes = []
_co_uninitialize.restype = None
_co_create = _ole32.CoCreateInstance
_co_create.argtypes = [
    ctypes.POINTER(_Guid),
    ctypes.c_void_p,
    wintypes.DWORD,
    ctypes.POINTER(_Guid),
    ctypes.POINTER(ctypes.c_void_p),
]
_co_create.restype = ctypes.c_long

_shell32 = ctypes.WinDLL("shell32", use_last_error=True)
_create_shell_item = _shell32.SHCreateItemFromParsingName
_create_shell_item.argtypes = [
    wintypes.LPCWSTR,
    ctypes.c_void_p,
    ctypes.POINTER(_Guid),
    ctypes.POINTER(ctypes.c_void_p),
]
_create_shell_item.restype = ctypes.c_long

_CLSID_FILE_OPERATION = _Guid.parse("3ad05575-8857-4850-9277-11b85bdb8e09")
_IID_FILE_OPERATION = _Guid.parse("947aab5f-0a5c-4c13-b4d6-4bf7836fc9f8")
_IID_SHELL_ITEM = _Guid.parse("43826d1e-e718-42ee-bc55-a1e261c37bfe")


class _FileDispositionInfoEx(ctypes.Structure):
    _fields_ = [("flags", wintypes.DWORD)]


class _FileDispositionInfo(ctypes.Structure):
    _fields_ = [("delete_file", wintypes.BOOL)]


class _FileRenameInfo(ctypes.Structure):
    _fields_ = [
        ("replace_if_exists", wintypes.BOOL),
        ("root_directory", wintypes.HANDLE),
        ("file_name_length", wintypes.DWORD),
        ("file_name", wintypes.WCHAR * 1),
    ]


def _extended_path(path: Path) -> str:
    spelling = str(path)
    if spelling.startswith("\\\\?\\"):
        return spelling
    return "\\\\?\\UNC\\" + spelling[2:] if spelling.startswith("\\\\") else "\\\\?\\" + spelling


def _open_descriptor(
    path: Path,
    *,
    desired_access: int,
    creation: int,
    attributes: int,
    descriptor_flags: int,
    directory: bool,
    share_mode: int = _FILE_SHARE_READ,
) -> int:
    handle = _create(
        _extended_path(path),
        desired_access,
        share_mode,
        None,
        creation,
        attributes | _FILE_FLAG_OPEN_REPARSE_POINT,
        None,
    )
    if handle == _INVALID:
        code = ctypes.get_last_error()
        if code in {2, 3}:
            raise FileNotFoundError("workspace_path_not_found")
        if code in {80, 183}:
            raise FileExistsError("workspace_path_exists")
        raise OSError("workspace_handle_unavailable")
    try:
        info = _FileInformation()
        if not _information(handle, ctypes.byref(info)):
            raise OSError("workspace_metadata_unavailable")
        if info.attributes & 0x400:
            raise LocalAgentError("workspace_link_or_reparse_refused")
        if _type(handle) != 1 or bool(info.attributes & 0x10) != directory:
            raise LocalAgentError("workspace_not_a_directory" if directory else "workspace_file_unavailable")
        descriptor = msvcrt.open_osfhandle(handle, descriptor_flags | os.O_BINARY | os.O_NOINHERIT)
        handle = None  # The descriptor now owns the native handle.
        return descriptor
    finally:
        if handle is not None and not _close(handle):
            raise OSError("workspace_handle_release_failed")


def open_read_descriptor(path: Path, *, directory: bool) -> int:
    """Return an owned CRT descriptor, or a fixed-code failure without paths."""
    return _open_descriptor(
        path,
        desired_access=0x80000000,
        creation=_OPEN_EXISTING,
        attributes=_FILE_FLAG_BACKUP_SEMANTICS if directory else 0,
        descriptor_flags=os.O_RDONLY,
        directory=directory,
    )


def open_reviewed_target_descriptor(path: Path) -> int:
    """Open a reviewed regular file against later writes while permitting guarded replacement."""
    return _open_descriptor(
        path,
        desired_access=0x80000000 | _DELETE,
        creation=_OPEN_EXISTING,
        attributes=0,
        descriptor_flags=os.O_RDONLY,
        directory=False,
        share_mode=_FILE_SHARE_READ | _FILE_SHARE_WRITE | _FILE_SHARE_DELETE,
    )


def open_trash_source_descriptor(path: Path) -> int:
    """Open one reviewed regular file while permitting the Shell's exact move."""

    return _open_descriptor(
        path,
        desired_access=0x80000000 | _DELETE,
        creation=_OPEN_EXISTING,
        attributes=0,
        descriptor_flags=os.O_RDONLY,
        directory=False,
        share_mode=_FILE_SHARE_READ | _FILE_SHARE_WRITE | _FILE_SHARE_DELETE,
    )


def descriptor_final_path(descriptor: int) -> str:
    """Return the kernel-resolved final DOS path for one still-open handle."""

    native = msvcrt.get_osfhandle(descriptor)
    required = _get_final_path(native, None, 0, 0)
    if required == 0:
        raise OSError("workspace_final_path_unavailable")
    buffer = ctypes.create_unicode_buffer(required + 1)
    written = _get_final_path(native, buffer, len(buffer), 0)
    if written == 0 or written >= len(buffer):
        raise OSError("workspace_final_path_unavailable")
    return buffer.value


def descriptor_is_in_recycle_bin(descriptor: int, source: Path) -> bool:
    """Verify that an open local-drive item now resides below `$Recycle.Bin`."""

    drive = source.drive
    if len(drive) != 2 or drive[1] != ":":
        return False
    final = descriptor_final_path(descriptor).replace("/", "\\")
    if final.startswith("\\\\?\\"):
        final = final[4:]
    expected = f"{drive}\\$Recycle.Bin\\"
    return final.casefold().startswith(expected.casefold())


def _com_method(
    interface: ctypes.c_void_p,
    index: int,
    restype: object,
    *argtypes: object,
):
    vtable = ctypes.cast(
        interface,
        ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p)),
    ).contents
    return ctypes.WINFUNCTYPE(restype, ctypes.c_void_p, *argtypes)(vtable[index])


def _hresult_failed(value: int) -> bool:
    return ctypes.c_long(value).value < 0


def _release_com(interface: ctypes.c_void_p | None) -> None:
    if interface is None or not interface.value:
        return
    release = _com_method(interface, 2, wintypes.ULONG)
    release(interface)


def _recycle_path_sta(path: Path) -> None:
    initialized = False
    operation = ctypes.c_void_p()
    item = ctypes.c_void_p()
    try:
        initialized_result = _co_initialize(None, _COINIT_APARTMENTTHREADED)
        if _hresult_failed(initialized_result):
            raise OSError("workspace_recycle_com_unavailable")
        initialized = True
        result = _co_create(
            ctypes.byref(_CLSID_FILE_OPERATION),
            None,
            _CLSCTX_INPROC_SERVER,
            ctypes.byref(_IID_FILE_OPERATION),
            ctypes.byref(operation),
        )
        if _hresult_failed(result) or not operation.value:
            raise OSError("workspace_recycle_operation_unavailable")
        flags = (
            _FOF_SILENT
            | _FOF_NOCONFIRMATION
            | _FOF_ALLOWUNDO
            | _FOF_NOERRORUI
            | _FOFX_RECYCLEONDELETE
            | _FOFX_EARLYFAILURE
            | _FOFX_ADDUNDORECORD
        )
        set_flags = _com_method(operation, 5, ctypes.c_long, wintypes.DWORD)
        if _hresult_failed(set_flags(operation, flags)):
            raise OSError("workspace_recycle_flags_refused")
        result = _create_shell_item(
            str(path),
            None,
            ctypes.byref(_IID_SHELL_ITEM),
            ctypes.byref(item),
        )
        if _hresult_failed(result) or not item.value:
            raise OSError("workspace_recycle_item_unavailable")
        delete_item = _com_method(
            operation,
            18,
            ctypes.c_long,
            ctypes.c_void_p,
            ctypes.c_void_p,
        )
        if _hresult_failed(delete_item(operation, item, None)):
            raise OSError("workspace_recycle_delete_refused")
        perform = _com_method(operation, 21, ctypes.c_long)
        perform_result = perform(operation)
        aborted = wintypes.BOOL()
        get_aborted = _com_method(
            operation,
            22,
            ctypes.c_long,
            ctypes.POINTER(wintypes.BOOL),
        )
        aborted_result = get_aborted(operation, ctypes.byref(aborted))
        if (
            _hresult_failed(perform_result)
            or _hresult_failed(aborted_result)
            or bool(aborted.value)
        ):
            raise OSError("workspace_recycle_operation_failed")
    finally:
        _release_com(item)
        _release_com(operation)
        if initialized:
            _co_uninitialize()


def recycle_path(path: Path) -> None:
    """Move one filesystem item through `IFileOperation` into the Recycle Bin."""

    failures: list[BaseException] = []

    def run() -> None:
        try:
            _recycle_path_sta(path)
        except BaseException as error:  # transfer a fixed failure to the caller thread
            failures.append(error)

    worker = threading.Thread(target=run, name="workspace-recycle", daemon=True)
    worker.start()
    worker.join(timeout=_RECYCLE_OPERATION_TIMEOUT_SECONDS)
    if worker.is_alive():
        raise RecycleOperationUnverified("workspace_recycle_operation_unverified")
    if failures:
        raise OSError("workspace_recycle_operation_failed") from failures[0]


def open_move_source_descriptor(path: Path) -> int:
    """Open the reviewed move source while denying competing delete/rename access."""

    return _open_descriptor(
        path,
        desired_access=0x80000000 | _DELETE,
        creation=_OPEN_EXISTING,
        attributes=0,
        descriptor_flags=os.O_RDONLY,
        directory=False,
        share_mode=_FILE_SHARE_READ | _FILE_SHARE_WRITE,
    )


def open_move_directory_source_descriptor(path: Path) -> int:
    """Open a reviewed directory entry for a handle-bound rename."""

    return _open_descriptor(
        path,
        desired_access=0x80000000 | _DELETE,
        creation=_OPEN_EXISTING,
        attributes=_FILE_FLAG_BACKUP_SEMANTICS,
        descriptor_flags=os.O_RDONLY,
        directory=True,
        share_mode=_FILE_SHARE_READ | _FILE_SHARE_WRITE,
    )


def open_mutation_directory_descriptor(path: Path) -> int:
    """Pin the final mutation parent while allowing child publication.

    Child creation, replacement, and rename do not require another process to
    rename or delete the parent directory itself. Omitting delete sharing keeps
    an absolute-path Windows publication bound to the reviewed parent handle.
    """
    return _open_descriptor(
        path,
        desired_access=0x80000000 | 0x40000000,
        creation=_OPEN_EXISTING,
        attributes=_FILE_FLAG_BACKUP_SEMANTICS,
        descriptor_flags=os.O_RDONLY,
        directory=True,
        share_mode=_FILE_SHARE_READ | _FILE_SHARE_WRITE,
    )


def create_staged_descriptor(path: Path) -> int:
    """Create an exclusive private stage that can be renamed or discarded by handle."""
    return _open_descriptor(
        path,
        desired_access=0x80000000 | 0x40000000 | _DELETE,
        creation=_CREATE_NEW,
        attributes=_FILE_ATTRIBUTE_TEMPORARY,
        descriptor_flags=os.O_RDWR,
        directory=False,
        share_mode=_FILE_SHARE_READ | _FILE_SHARE_WRITE | _FILE_SHARE_DELETE,
    )


def discard_descriptor(descriptor: int) -> None:
    """Remove the link owned by an open private stage; never resolve a cleanup path."""
    native = msvcrt.get_osfhandle(descriptor)
    extended = _FileDispositionInfoEx(
        _FILE_DISPOSITION_DELETE
        | _FILE_DISPOSITION_POSIX_SEMANTICS
        | _FILE_DISPOSITION_IGNORE_READONLY_ATTRIBUTE
    )
    if _set_information(
        native,
        _FILE_DISPOSITION_INFO_EX,
        ctypes.byref(extended),
        ctypes.sizeof(extended),
    ):
        return
    legacy = _FileDispositionInfo(True)
    if not _set_information(
        native,
        _FILE_DISPOSITION_INFO,
        ctypes.byref(legacy),
        ctypes.sizeof(legacy),
    ):
        raise OSError("workspace_stage_cleanup_failed")


def replace_file_with_backup(target: Path, replacement: Path, backup: Path) -> None:
    """Atomically replace a target while retaining the displaced name for CAS verification."""
    if not _replace_file(
        _extended_path(target),
        _extended_path(replacement),
        _extended_path(backup),
        0,
        None,
        None,
    ):
        raise OSError(ctypes.get_last_error(), "workspace_atomic_publish_failed")


def rename_descriptor_no_replace(
    descriptor: int,
    target: Path,
) -> None:
    """Rename an opened file or directory into pinned ancestry without replacement.

    ``FileRenameInfo`` binds the source to its already-open handle and the
    destination path's entire ancestor chain is pinned by ``WorkspaceIO``.
    ``replace_if_exists`` remains false, so an external target race cannot be
    overwritten.
    """

    encoded = str(target).encode("utf-16-le", errors="strict")
    name_offset = _FileRenameInfo.file_name.offset
    # Allocate from the structure size, not merely FileName's offset. The
    # native structure has trailing alignment after FileName[1]; retaining it
    # also leaves a zeroed wide terminator beyond FileNameLength.
    buffer_size = ctypes.sizeof(_FileRenameInfo) + len(encoded)
    buffer = ctypes.create_string_buffer(buffer_size)
    information = ctypes.cast(buffer, ctypes.POINTER(_FileRenameInfo)).contents
    information.replace_if_exists = False
    information.root_directory = None
    information.file_name_length = len(encoded)
    ctypes.memmove(ctypes.addressof(buffer) + name_offset, encoded, len(encoded))
    if _set_information(
        msvcrt.get_osfhandle(descriptor),
        _FILE_RENAME_INFO,
        buffer,
        buffer_size,
    ):
        return
    code = ctypes.get_last_error()
    if code in {80, 183}:
        raise FileExistsError("workspace_path_exists")
    if code in {2, 3}:
        raise FileNotFoundError("workspace_path_not_found")
    raise OSError(code, "workspace_atomic_move_failed")
