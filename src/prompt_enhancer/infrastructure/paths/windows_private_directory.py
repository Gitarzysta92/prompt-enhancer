"""Narrow Win32 security support for the fixed update-staging directory.

The adapter creates no parent directories and never changes an existing ACL.
It deliberately exposes only typed policy outcomes: SIDs, Windows error values,
and local paths stay inside this module.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import os
from pathlib import Path

from ...application.paths.policy import PathRejection


_ACCESS_ALLOWED_ACE_TYPE = 0
_ACL_SIZE_INFORMATION = 2
_CONTAINER_INHERIT_ACE = 0x02
_DACL_SECURITY_INFORMATION = 0x00000004
_DRIVE_FIXED = 3
_ERROR_INSUFFICIENT_BUFFER = 122
_FILE_ALL_ACCESS = 0x1F01FF
_FILE_ATTRIBUTE_DIRECTORY = 0x10
_FILE_ATTRIBUTE_REPARSE_POINT = 0x400
_FILE_FLAG_BACKUP_SEMANTICS = 0x02000000
_FILE_FLAG_OPEN_REPARSE_POINT = 0x00200000
_FILE_READ_ATTRIBUTES = 0x80
_FILE_SHARE_DELETE = 0x00000004
_FILE_SHARE_READ = 0x00000001
_FILE_SHARE_WRITE = 0x00000002
_FS_PERSISTENT_ACLS = 0x00000008
_GRANT_ACCESS = 1
_INHERITED_ACE = 0x10
_MAX_ACE_COUNT = 8
_MAX_ACE_SIZE = 512
_MAX_DACL_BYTES = 4 * 1024
_MAX_SID_SIZE = 68
_MIN_ACL_SIZE = 8
_MIN_SID_SIZE = 8
_OBJECT_INHERIT_ACE = 0x01
_OPEN_EXISTING = 3
_OWNER_SECURITY_INFORMATION = 0x00000001
_READ_CONTROL = 0x00020000
_SE_DACL_PROTECTED = 0x1000
_SE_FILE_OBJECT = 1
_SECURITY_DESCRIPTOR_REVISION = 1
_TOKEN_QUERY = 0x0008
_TOKEN_USER_INFORMATION_CLASS = 1
_TRUSTEE_IS_SID = 0
_TRUSTEE_IS_UNKNOWN = 0
_WIN_LOCAL_SYSTEM_SID = 22


class _SecurityAttributes(ctypes.Structure):
    _fields_ = [
        ("nLength", wintypes.DWORD),
        ("lpSecurityDescriptor", ctypes.c_void_p),
        ("bInheritHandle", wintypes.BOOL),
    ]


class _SidAndAttributes(ctypes.Structure):
    _fields_ = [("Sid", ctypes.c_void_p), ("Attributes", wintypes.DWORD)]


class _TokenUser(ctypes.Structure):
    _fields_ = [("User", _SidAndAttributes)]


class _TrusteeW(ctypes.Structure):
    _fields_ = [
        ("pMultipleTrustee", ctypes.c_void_p),
        ("MultipleTrusteeOperation", wintypes.DWORD),
        ("TrusteeForm", wintypes.DWORD),
        ("TrusteeType", wintypes.DWORD),
        ("ptstrName", ctypes.c_void_p),
    ]


class _ExplicitAccessW(ctypes.Structure):
    _fields_ = [
        ("grfAccessPermissions", wintypes.DWORD),
        ("grfAccessMode", wintypes.DWORD),
        ("grfInheritance", wintypes.DWORD),
        ("Trustee", _TrusteeW),
    ]


class _ByHandleFileInformation(ctypes.Structure):
    _fields_ = [
        ("dwFileAttributes", wintypes.DWORD),
        ("ftCreationTimeLowDateTime", wintypes.DWORD),
        ("ftCreationTimeHighDateTime", wintypes.DWORD),
        ("ftLastAccessTimeLowDateTime", wintypes.DWORD),
        ("ftLastAccessTimeHighDateTime", wintypes.DWORD),
        ("ftLastWriteTimeLowDateTime", wintypes.DWORD),
        ("ftLastWriteTimeHighDateTime", wintypes.DWORD),
        ("dwVolumeSerialNumber", wintypes.DWORD),
        ("nFileSizeHigh", wintypes.DWORD),
        ("nFileSizeLow", wintypes.DWORD),
        ("nNumberOfLinks", wintypes.DWORD),
        ("nFileIndexHigh", wintypes.DWORD),
        ("nFileIndexLow", wintypes.DWORD),
    ]


class _AclSizeInformation(ctypes.Structure):
    _fields_ = [
        ("AceCount", wintypes.DWORD),
        ("AclBytesInUse", wintypes.DWORD),
        ("AclBytesFree", wintypes.DWORD),
    ]


class _AceHeader(ctypes.Structure):
    _fields_ = [
        ("AceType", ctypes.c_ubyte),
        ("AceFlags", ctypes.c_ubyte),
        ("AceSize", ctypes.c_ushort),
    ]


class _AccessAllowedAce(ctypes.Structure):
    _fields_ = [
        ("Header", _AceHeader),
        ("Mask", wintypes.DWORD),
        ("SidStart", wintypes.DWORD),
    ]


class _WindowsPrivateDirectorySecurity:
    """Owns pointer-safe, fail-closed Win32 DACL creation and inspection."""

    def __init__(self) -> None:
        self._available = os.name == "nt"
        if not self._available:
            return
        self._kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self._advapi = ctypes.WinDLL("advapi32", use_last_error=True)
        self._configure_functions()

    def _configure_functions(self) -> None:
        self._kernel.CreateDirectoryW.argtypes = (
            wintypes.LPCWSTR,
            ctypes.POINTER(_SecurityAttributes),
        )
        self._kernel.CreateDirectoryW.restype = wintypes.BOOL
        self._kernel.CreateFileW.argtypes = (
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
            ctypes.c_void_p,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.HANDLE,
        )
        self._kernel.CreateFileW.restype = wintypes.HANDLE
        self._kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
        self._kernel.CloseHandle.restype = wintypes.BOOL
        self._kernel.GetFileInformationByHandle.argtypes = (
            wintypes.HANDLE,
            ctypes.POINTER(_ByHandleFileInformation),
        )
        self._kernel.GetFileInformationByHandle.restype = wintypes.BOOL
        self._kernel.GetVolumeInformationW.argtypes = (
            wintypes.LPCWSTR,
            ctypes.c_void_p,
            wintypes.DWORD,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.POINTER(wintypes.DWORD),
            ctypes.c_void_p,
            wintypes.DWORD,
        )
        self._kernel.GetVolumeInformationW.restype = wintypes.BOOL
        self._kernel.GetDriveTypeW.argtypes = (wintypes.LPCWSTR,)
        self._kernel.GetDriveTypeW.restype = wintypes.UINT
        self._kernel.GetCurrentProcess.argtypes = ()
        self._kernel.GetCurrentProcess.restype = wintypes.HANDLE
        self._kernel.LocalFree.argtypes = (ctypes.c_void_p,)
        self._kernel.LocalFree.restype = ctypes.c_void_p
        self._advapi.OpenProcessToken.argtypes = (
            wintypes.HANDLE,
            wintypes.DWORD,
            ctypes.POINTER(wintypes.HANDLE),
        )
        self._advapi.OpenProcessToken.restype = wintypes.BOOL
        self._advapi.GetTokenInformation.argtypes = (
            wintypes.HANDLE,
            ctypes.c_int,
            ctypes.c_void_p,
            wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD),
        )
        self._advapi.GetTokenInformation.restype = wintypes.BOOL
        self._advapi.CreateWellKnownSid.argtypes = (
            wintypes.DWORD,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.POINTER(wintypes.DWORD),
        )
        self._advapi.CreateWellKnownSid.restype = wintypes.BOOL
        self._advapi.InitializeSecurityDescriptor.argtypes = (
            ctypes.c_void_p,
            wintypes.DWORD,
        )
        self._advapi.InitializeSecurityDescriptor.restype = wintypes.BOOL
        self._advapi.SetSecurityDescriptorDacl.argtypes = (
            ctypes.c_void_p,
            wintypes.BOOL,
            ctypes.c_void_p,
            wintypes.BOOL,
        )
        self._advapi.SetSecurityDescriptorDacl.restype = wintypes.BOOL
        self._advapi.SetSecurityDescriptorOwner.argtypes = (
            ctypes.c_void_p,
            ctypes.c_void_p,
            wintypes.BOOL,
        )
        self._advapi.SetSecurityDescriptorOwner.restype = wintypes.BOOL
        self._advapi.SetSecurityDescriptorControl.argtypes = (
            ctypes.c_void_p,
            ctypes.c_ushort,
            ctypes.c_ushort,
        )
        self._advapi.SetSecurityDescriptorControl.restype = wintypes.BOOL
        self._advapi.GetSecurityDescriptorControl.argtypes = (
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_ushort),
            ctypes.POINTER(wintypes.DWORD),
        )
        self._advapi.GetSecurityDescriptorControl.restype = wintypes.BOOL
        self._advapi.GetSecurityDescriptorDacl.argtypes = (
            ctypes.c_void_p,
            ctypes.POINTER(wintypes.BOOL),
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.POINTER(wintypes.BOOL),
        )
        self._advapi.GetSecurityDescriptorDacl.restype = wintypes.BOOL
        self._advapi.GetSecurityInfo.argtypes = (
            wintypes.HANDLE,
            ctypes.c_int,
            wintypes.DWORD,
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_void_p),
        )
        self._advapi.GetSecurityInfo.restype = wintypes.DWORD
        self._advapi.GetAclInformation.argtypes = (
            ctypes.c_void_p,
            ctypes.c_void_p,
            wintypes.DWORD,
            wintypes.DWORD,
        )
        self._advapi.GetAclInformation.restype = wintypes.BOOL
        self._advapi.GetAce.argtypes = (
            ctypes.c_void_p,
            wintypes.DWORD,
            ctypes.POINTER(ctypes.c_void_p),
        )
        self._advapi.GetAce.restype = wintypes.BOOL
        self._advapi.IsValidSid.argtypes = (ctypes.c_void_p,)
        self._advapi.IsValidSid.restype = wintypes.BOOL
        self._advapi.GetLengthSid.argtypes = (ctypes.c_void_p,)
        self._advapi.GetLengthSid.restype = wintypes.DWORD
        self._advapi.EqualSid.argtypes = (ctypes.c_void_p, ctypes.c_void_p)
        self._advapi.EqualSid.restype = wintypes.BOOL
        self._advapi.SetEntriesInAclW.argtypes = (
            wintypes.ULONG,
            ctypes.POINTER(_ExplicitAccessW),
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_void_p),
        )
        self._advapi.SetEntriesInAclW.restype = wintypes.DWORD

    def inspect(self, path: Path) -> PathRejection | None:
        if not self._available or not self._supports_persistent_acls(path):
            return PathRejection.WINDOWS_DACL_UNAVAILABLE
        handle = self._open_directory(path)
        if handle is None:
            return PathRejection.INSPECTION_FAILED
        try:
            information = _ByHandleFileInformation()
            if not self._kernel.GetFileInformationByHandle(handle, ctypes.byref(information)):
                return PathRejection.INSPECTION_FAILED
            if not information.dwFileAttributes & _FILE_ATTRIBUTE_DIRECTORY:
                return PathRejection.INSPECTION_FAILED
            if information.dwFileAttributes & _FILE_ATTRIBUTE_REPARSE_POINT:
                return PathRejection.REPARSE_OR_SYMLINK
            if information.nNumberOfLinks != 1:
                return PathRejection.INSPECTION_FAILED
            return self._verify_descriptor(handle)
        finally:
            self._kernel.CloseHandle(handle)

    def create_then_inspect(self, path: Path) -> PathRejection | None:
        if not self._available or not self._supports_persistent_acls(path):
            return PathRejection.WINDOWS_DACL_UNAVAILABLE
        user_sid = self._current_process_user_sid()
        system_sid = self._local_system_sid()
        if user_sid is None or system_sid is None:
            return PathRejection.WINDOWS_DACL_UNAVAILABLE
        descriptor = ctypes.create_string_buffer(64)
        user_buffer = ctypes.create_string_buffer(user_sid)
        system_buffer = ctypes.create_string_buffer(system_sid)
        dacl = ctypes.c_void_p()
        try:
            if not self._advapi.InitializeSecurityDescriptor(
                ctypes.byref(descriptor), _SECURITY_DESCRIPTOR_REVISION
            ):
                return PathRejection.WINDOWS_DACL_UNAVAILABLE
            entries = (_ExplicitAccessW * 2)(
                self._allow_entry(user_buffer),
                self._allow_entry(system_buffer),
            )
            if self._advapi.SetEntriesInAclW(2, entries, None, ctypes.byref(dacl)) != 0:
                return PathRejection.WINDOWS_DACL_UNAVAILABLE
            if not self._advapi.SetSecurityDescriptorDacl(
                ctypes.byref(descriptor), True, dacl, False
            ):
                return PathRejection.WINDOWS_DACL_UNAVAILABLE
            if not self._advapi.SetSecurityDescriptorOwner(
                ctypes.byref(descriptor), ctypes.cast(user_buffer, ctypes.c_void_p), False
            ):
                return PathRejection.WINDOWS_DACL_UNAVAILABLE
            if not self._advapi.SetSecurityDescriptorControl(
                ctypes.byref(descriptor), _SE_DACL_PROTECTED, _SE_DACL_PROTECTED
            ):
                return PathRejection.WINDOWS_DACL_UNAVAILABLE
            attributes = _SecurityAttributes(
                nLength=ctypes.sizeof(_SecurityAttributes),
                lpSecurityDescriptor=ctypes.cast(descriptor, ctypes.c_void_p),
                bInheritHandle=False,
            )
            if not self._kernel.CreateDirectoryW(str(path), ctypes.byref(attributes)):
                return PathRejection.INSPECTION_FAILED
        finally:
            if dacl.value is not None:
                self._kernel.LocalFree(dacl)
        return self.inspect(path)

    def _supports_persistent_acls(self, path: Path) -> bool:
        drive = path.anchor
        if not drive or self._kernel.GetDriveTypeW(drive) != _DRIVE_FIXED:
            return False
        flags = wintypes.DWORD()
        if not self._kernel.GetVolumeInformationW(
            drive, None, 0, None, None, ctypes.byref(flags), None, 0
        ):
            return False
        return bool(flags.value & _FS_PERSISTENT_ACLS)

    def _open_directory(self, path: Path) -> wintypes.HANDLE | None:
        handle = self._kernel.CreateFileW(
            str(path),
            _READ_CONTROL | _FILE_READ_ATTRIBUTES,
            _FILE_SHARE_READ | _FILE_SHARE_WRITE | _FILE_SHARE_DELETE,
            None,
            _OPEN_EXISTING,
            _FILE_FLAG_BACKUP_SEMANTICS | _FILE_FLAG_OPEN_REPARSE_POINT,
            None,
        )
        if handle == ctypes.c_void_p(-1).value:
            return None
        return handle

    def _verify_descriptor(self, handle: wintypes.HANDLE) -> PathRejection | None:
        owner = ctypes.c_void_p()
        dacl = ctypes.c_void_p()
        descriptor = ctypes.c_void_p()
        result = self._advapi.GetSecurityInfo(
            handle,
            _SE_FILE_OBJECT,
            _OWNER_SECURITY_INFORMATION | _DACL_SECURITY_INFORMATION,
            ctypes.byref(owner),
            None,
            ctypes.byref(dacl),
            None,
            ctypes.byref(descriptor),
        )
        if result != 0 or not descriptor.value or not owner.value or not dacl.value:
            if descriptor.value:
                self._kernel.LocalFree(descriptor)
            return PathRejection.PERMISSIONS_UNVERIFIED
        try:
            control = ctypes.c_ushort()
            revision = wintypes.DWORD()
            if not self._advapi.GetSecurityDescriptorControl(
                descriptor, ctypes.byref(control), ctypes.byref(revision)
            ):
                return PathRejection.PERMISSIONS_UNVERIFIED
            if not control.value & _SE_DACL_PROTECTED:
                return PathRejection.PERMISSIONS_UNVERIFIED
            present = wintypes.BOOL()
            defaulted = wintypes.BOOL()
            descriptor_dacl = ctypes.c_void_p()
            if not self._advapi.GetSecurityDescriptorDacl(
                descriptor,
                ctypes.byref(present),
                ctypes.byref(descriptor_dacl),
                ctypes.byref(defaulted),
            ):
                return PathRejection.PERMISSIONS_UNVERIFIED
            if not present.value or not descriptor_dacl.value or descriptor_dacl.value != dacl.value:
                return PathRejection.PERMISSIONS_UNVERIFIED
            user_sid = self._current_process_user_sid()
            system_sid = self._local_system_sid()
            if user_sid is None or system_sid is None:
                return PathRejection.WINDOWS_DACL_UNAVAILABLE
            user_buffer = ctypes.create_string_buffer(user_sid)
            system_buffer = ctypes.create_string_buffer(system_sid)
            if not self._advapi.EqualSid(owner, ctypes.cast(user_buffer, ctypes.c_void_p)):
                return PathRejection.PERMISSIONS_UNVERIFIED
            return self._verify_exact_dacl(dacl, user_buffer, system_buffer)
        finally:
            self._kernel.LocalFree(descriptor)

    def _verify_exact_dacl(
        self,
        dacl: ctypes.c_void_p,
        user_sid: ctypes.Array[ctypes.c_char],
        system_sid: ctypes.Array[ctypes.c_char],
    ) -> PathRejection | None:
        details = _AclSizeInformation()
        if not self._advapi.GetAclInformation(
            dacl, ctypes.byref(details), ctypes.sizeof(details), _ACL_SIZE_INFORMATION
        ):
            return PathRejection.PERMISSIONS_UNVERIFIED
        if (
            details.AceCount != 2
            or details.AceCount > _MAX_ACE_COUNT
            or details.AclBytesInUse < _MIN_ACL_SIZE
            or details.AclBytesInUse > _MAX_DACL_BYTES
        ):
            return PathRejection.PERMISSIONS_UNVERIFIED
        dacl_start = dacl.value
        dacl_end = dacl_start + details.AclBytesInUse
        expected = {
            ctypes.addressof(user_sid): False,
            ctypes.addressof(system_sid): False,
        }
        for index in range(details.AceCount):
            ace = ctypes.c_void_p()
            if not self._advapi.GetAce(dacl, index, ctypes.byref(ace)) or not ace.value:
                return PathRejection.PERMISSIONS_UNVERIFIED
            if not dacl_start <= ace.value <= dacl_end - ctypes.sizeof(_AceHeader):
                return PathRejection.PERMISSIONS_UNVERIFIED
            header = _AceHeader.from_address(ace.value)
            if (
                header.AceType != _ACCESS_ALLOWED_ACE_TYPE
                or header.AceFlags != (_CONTAINER_INHERIT_ACE | _OBJECT_INHERIT_ACE)
                or header.AceFlags & _INHERITED_ACE
                or header.AceSize < ctypes.sizeof(_AccessAllowedAce)
                or header.AceSize > _MAX_ACE_SIZE
                or ace.value + header.AceSize > dacl_end
            ):
                return PathRejection.PERMISSIONS_UNVERIFIED
            allowed = _AccessAllowedAce.from_address(ace.value)
            if allowed.Mask != _FILE_ALL_ACCESS:
                return PathRejection.PERMISSIONS_UNVERIFIED
            sid_address = ace.value + _AccessAllowedAce.SidStart.offset
            sid = ctypes.c_void_p(sid_address)
            if not self._valid_ace_sid(sid, header.AceSize):
                return PathRejection.PERMISSIONS_UNVERIFIED
            matched = None
            for expected_address, seen in expected.items():
                if self._advapi.EqualSid(sid, ctypes.c_void_p(expected_address)):
                    matched = expected_address
                    if seen:
                        return PathRejection.PERMISSIONS_UNVERIFIED
                    break
            if matched is None:
                return PathRejection.PERMISSIONS_UNVERIFIED
            expected[matched] = True
        if not all(expected.values()):
            return PathRejection.PERMISSIONS_UNVERIFIED
        return None

    def _valid_ace_sid(self, sid: ctypes.c_void_p, ace_size: int) -> bool:
        if _AccessAllowedAce.SidStart.offset + _MIN_SID_SIZE > ace_size:
            return False
        subauthority_count = ctypes.c_ubyte.from_address(sid.value + 1).value
        declared_size = _MIN_SID_SIZE + 4 * subauthority_count
        if (_AccessAllowedAce.SidStart.offset + declared_size > ace_size
                or declared_size > _MAX_SID_SIZE):
            return False
        if not self._advapi.IsValidSid(sid):
            return False
        length = self._advapi.GetLengthSid(sid)
        return length == declared_size

    def _current_process_user_sid(self) -> bytes | None:
        token = wintypes.HANDLE()
        if not self._advapi.OpenProcessToken(
            self._kernel.GetCurrentProcess(), _TOKEN_QUERY, ctypes.byref(token)
        ):
            return None
        try:
            size = wintypes.DWORD()
            self._advapi.GetTokenInformation(
                token, _TOKEN_USER_INFORMATION_CLASS, None, 0, ctypes.byref(size)
            )
            if ctypes.get_last_error() != _ERROR_INSUFFICIENT_BUFFER or size.value == 0:
                return None
            if size.value > 4 * 1024:
                return None
            buffer = ctypes.create_string_buffer(size.value)
            if not self._advapi.GetTokenInformation(
                token,
                _TOKEN_USER_INFORMATION_CLASS,
                buffer,
                size.value,
                ctypes.byref(size),
            ):
                return None
            sid = _TokenUser.from_buffer(buffer).User.Sid
            return self._copy_sid(sid)
        finally:
            self._kernel.CloseHandle(token)

    def _local_system_sid(self) -> bytes | None:
        size = wintypes.DWORD()
        self._advapi.CreateWellKnownSid(
            _WIN_LOCAL_SYSTEM_SID, None, None, ctypes.byref(size)
        )
        if ctypes.get_last_error() != _ERROR_INSUFFICIENT_BUFFER or size.value == 0:
            return None
        if size.value > _MAX_SID_SIZE:
            return None
        buffer = ctypes.create_string_buffer(size.value)
        if not self._advapi.CreateWellKnownSid(
            _WIN_LOCAL_SYSTEM_SID, None, buffer, ctypes.byref(size)
        ):
            return None
        return self._copy_sid(ctypes.cast(buffer, ctypes.c_void_p))

    def _copy_sid(self, sid: ctypes.c_void_p) -> bytes | None:
        if not sid or not self._advapi.IsValidSid(sid):
            return None
        length = self._advapi.GetLengthSid(sid)
        if length == 0 or length > _MAX_SID_SIZE:
            return None
        return ctypes.string_at(sid, length)

    @staticmethod
    def _allow_entry(sid: ctypes.Array[ctypes.c_char]) -> _ExplicitAccessW:
        return _ExplicitAccessW(
            grfAccessPermissions=_FILE_ALL_ACCESS,
            grfAccessMode=_GRANT_ACCESS,
            grfInheritance=_CONTAINER_INHERIT_ACE | _OBJECT_INHERIT_ACE,
            Trustee=_TrusteeW(
                pMultipleTrustee=None,
                MultipleTrusteeOperation=0,
                TrusteeForm=_TRUSTEE_IS_SID,
                TrusteeType=_TRUSTEE_IS_UNKNOWN,
                ptstrName=ctypes.cast(sid, ctypes.c_void_p),
            ),
        )


__all__ = ("_WindowsPrivateDirectorySecurity",)
