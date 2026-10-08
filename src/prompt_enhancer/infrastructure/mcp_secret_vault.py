"""Narrow OS-backed secret vault for managed MCP configuration.

The Windows adapter addresses only deterministic Prompt Enhancer targets.  It
never enumerates Credential Manager, never reads unrelated credentials, and
never exposes a value through HTTP.  Non-Windows or unavailable hosts fail
closed.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import re
import sys
from typing import Literal

from pydantic import SecretStr

from ..application.mcp_server_management import (
    MAX_MCP_SECRET_BYTES,
    McpManagedServerError,
)


_REFERENCE = re.compile(r"^[0-9a-f]{32}$")
_TARGET_PREFIX = "PromptEnhancer/MCP/"
_CRED_TYPE_GENERIC = 1
_CRED_PERSIST_LOCAL_MACHINE = 2
_ERROR_NOT_FOUND = 1168


class _CredentialW(ctypes.Structure):
    _fields_ = [
        ("Flags", wintypes.DWORD),
        ("Type", wintypes.DWORD),
        ("TargetName", wintypes.LPWSTR),
        ("Comment", wintypes.LPWSTR),
        ("LastWritten", wintypes.FILETIME),
        ("CredentialBlobSize", wintypes.DWORD),
        ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
        ("Persist", wintypes.DWORD),
        ("AttributeCount", wintypes.DWORD),
        ("Attributes", ctypes.c_void_p),
        ("TargetAlias", wintypes.LPWSTR),
        ("UserName", wintypes.LPWSTR),
    ]


class UnavailableMcpSecretVault:
    @property
    def provider(self) -> Literal["unavailable"]:
        return "unavailable"

    def available(self) -> bool:
        return False

    def contains(self, reference_id: str) -> bool:
        del reference_id
        return False

    def read(self, reference_id: str) -> SecretStr:
        del reference_id
        raise McpManagedServerError("mcp_managed_secret_vault_unavailable")

    def write(self, reference_id: str, value: SecretStr) -> None:
        del reference_id, value
        raise McpManagedServerError("mcp_managed_secret_vault_unavailable")

    def delete(self, reference_id: str) -> None:
        del reference_id
        raise McpManagedServerError("mcp_managed_secret_vault_unavailable")


class WindowsCredentialManagerMcpSecretVault:
    """Use Windows Credential Manager without enumeration or value logging."""

    def __init__(self) -> None:
        self._api = None
        if sys.platform != "win32":
            return
        try:
            api = ctypes.WinDLL("Advapi32.dll", use_last_error=True)
            api.CredWriteW.argtypes = [ctypes.POINTER(_CredentialW), wintypes.DWORD]
            api.CredWriteW.restype = wintypes.BOOL
            api.CredReadW.argtypes = [
                wintypes.LPCWSTR,
                wintypes.DWORD,
                wintypes.DWORD,
                ctypes.POINTER(ctypes.POINTER(_CredentialW)),
            ]
            api.CredReadW.restype = wintypes.BOOL
            api.CredDeleteW.argtypes = [
                wintypes.LPCWSTR,
                wintypes.DWORD,
                wintypes.DWORD,
            ]
            api.CredDeleteW.restype = wintypes.BOOL
            api.CredFree.argtypes = [ctypes.c_void_p]
            api.CredFree.restype = None
            self._api = api
        except (AttributeError, OSError):
            self._api = None

    @property
    def provider(self) -> Literal["windows_credential_manager", "unavailable"]:
        return "windows_credential_manager" if self.available() else "unavailable"

    def available(self) -> bool:
        return self._api is not None

    @staticmethod
    def _target(reference_id: str) -> str:
        if _REFERENCE.fullmatch(reference_id) is None:
            raise McpManagedServerError("mcp_managed_secret_reference_invalid")
        return _TARGET_PREFIX + reference_id

    def _require_api(self):
        if self._api is None:
            raise McpManagedServerError("mcp_managed_secret_vault_unavailable")
        return self._api

    def contains(self, reference_id: str) -> bool:
        api = self._require_api()
        pointer = ctypes.POINTER(_CredentialW)()
        if not api.CredReadW(
            self._target(reference_id),
            _CRED_TYPE_GENERIC,
            0,
            ctypes.byref(pointer),
        ):
            if ctypes.get_last_error() == _ERROR_NOT_FOUND:
                return False
            raise McpManagedServerError("mcp_managed_secret_vault_read_failed")
        try:
            return True
        finally:
            api.CredFree(pointer)

    def read(self, reference_id: str) -> SecretStr:
        """Read only one deterministic Prompt Enhancer target just in time."""

        api = self._require_api()
        pointer = ctypes.POINTER(_CredentialW)()
        if not api.CredReadW(
            self._target(reference_id),
            _CRED_TYPE_GENERIC,
            0,
            ctypes.byref(pointer),
        ):
            raise McpManagedServerError("mcp_managed_secret_vault_read_failed")
        try:
            size = int(pointer.contents.CredentialBlobSize)
            blob_pointer = pointer.contents.CredentialBlob
            if (
                size <= 0
                or size > MAX_MCP_SECRET_BYTES
                or not bool(blob_pointer)
            ):
                raise McpManagedServerError("mcp_managed_secret_vault_read_failed")
            try:
                raw = ctypes.string_at(blob_pointer, size).decode("utf-8", errors="strict")
            except (UnicodeDecodeError, ValueError):
                raise McpManagedServerError(
                    "mcp_managed_secret_vault_read_failed"
                ) from None
            if not raw or "\x00" in raw:
                raise McpManagedServerError("mcp_managed_secret_vault_read_failed")
            return SecretStr(raw)
        finally:
            api.CredFree(pointer)

    def write(self, reference_id: str, value: SecretStr) -> None:
        api = self._require_api()
        blob = value.get_secret_value().encode("utf-8")
        if not blob or len(blob) > MAX_MCP_SECRET_BYTES or b"\x00" in blob:
            raise McpManagedServerError("mcp_managed_secret_value_invalid")
        buffer = (ctypes.c_ubyte * len(blob)).from_buffer_copy(blob)
        credential = _CredentialW()
        credential.Type = _CRED_TYPE_GENERIC
        credential.TargetName = self._target(reference_id)
        credential.Comment = "Prompt Enhancer managed MCP secret"
        credential.CredentialBlobSize = len(blob)
        credential.CredentialBlob = ctypes.cast(
            buffer, ctypes.POINTER(ctypes.c_ubyte)
        )
        credential.Persist = _CRED_PERSIST_LOCAL_MACHINE
        credential.UserName = "Prompt Enhancer"
        if not api.CredWriteW(ctypes.byref(credential), 0):
            raise McpManagedServerError("mcp_managed_secret_vault_write_failed")

    def delete(self, reference_id: str) -> None:
        api = self._require_api()
        if api.CredDeleteW(self._target(reference_id), _CRED_TYPE_GENERIC, 0):
            return
        if ctypes.get_last_error() != _ERROR_NOT_FOUND:
            raise McpManagedServerError("mcp_managed_secret_vault_delete_failed")


def platform_mcp_secret_vault():
    vault = WindowsCredentialManagerMcpSecretVault()
    return vault if vault.available() else UnavailableMcpSecretVault()


__all__ = (
    "UnavailableMcpSecretVault",
    "WindowsCredentialManagerMcpSecretVault",
    "platform_mcp_secret_vault",
)
