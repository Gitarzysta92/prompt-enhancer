"""Bounded, read-only Windows trust evidence for an already-open MSIX file.

This module deliberately delegates signature validation to the documented
``WINTRUST_ACTION_GENERIC_VERIFY_V2`` policy provider.  It does not parse MSIX
signature XML, invoke a command-line verifier, install anything, or open a
certificate store.  The provider state owns all certificate pointers and is
closed on every verification attempt.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import hashlib
import os
from pathlib import Path
from typing import Callable, Protocol

from .msix_preflight import PackageSignerUnavailable


_DWORD = ctypes.c_uint32
_BOOL = ctypes.c_int32
_LONG = ctypes.c_int32
_HANDLE = ctypes.c_void_p
_BYTE = ctypes.c_ubyte

_WTD_UI_NONE = 2
_WTD_CHOICE_FILE = 1
_WTD_STATEACTION_VERIFY = 1
_WTD_STATEACTION_CLOSE = 2
_WTD_REVOKE_WHOLECHAIN = 1
_WTD_REVOCATION_CHECK_CHAIN_EXCLUDE_ROOT = 0x00000080
_WTD_CACHE_ONLY_URL_RETRIEVAL = 0x00001000
_PROVIDER_FLAGS = (
    _WTD_REVOCATION_CHECK_CHAIN_EXCLUDE_ROOT | _WTD_CACHE_ONLY_URL_RETRIEVAL
)
_INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
_MAX_LEAF_DER_BYTES = 1024 * 1024
_MAX_CHAIN_CERTIFICATES = 128
_X509_ASN_ENCODING = 0x00000001
_PKCS_7_ASN_ENCODING = 0x00010000
_KNOWN_CERT_ENCODINGS = _X509_ASN_ENCODING | _PKCS_7_ASN_ENCODING
_SGNR_TYPE_TIMESTAMP = 0x00000010

# These are the status codes for a conclusively invalid Authenticode result.
# Transport/revocation availability failures intentionally are *not* included:
# cache-only verification cannot turn uncertainty into an unsigned package.
_INVALID_SIGNATURE_STATUSES = frozenset({
    0x800B0004,  # TRUST_E_SUBJECT_NOT_TRUSTED
    0x800B0100,  # TRUST_E_NOSIGNATURE
    0x800B0101,  # CERT_E_EXPIRED
    0x800B0102,  # CERT_E_VALIDITYPERIODNESTING
    0x800B0109,  # CERT_E_UNTRUSTEDROOT
    0x800B010C,  # CERT_E_REVOKED
    0x800B010D,  # CERT_E_UNTRUSTEDTESTROOT
    0x800B0110,  # CERT_E_WRONG_USAGE
    0x80096010,  # TRUST_E_BAD_DIGEST
})


class _GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", _DWORD),
        ("Data2", ctypes.c_uint16),
        ("Data3", ctypes.c_uint16),
        ("Data4", _BYTE * 8),
    ]


class _WINTRUST_FILE_INFO(ctypes.Structure):
    _fields_ = [
        ("cbStruct", _DWORD),
        ("pcwszFilePath", wintypes.LPCWSTR),
        ("hFile", _HANDLE),
        ("pgKnownSubject", ctypes.POINTER(_GUID)),
    ]


class _WINTRUST_DATA(ctypes.Structure):
    _fields_ = [
        ("cbStruct", _DWORD),
        ("pPolicyCallbackData", ctypes.c_void_p),
        ("pSIPClientData", ctypes.c_void_p),
        ("dwUIChoice", _DWORD),
        ("fdwRevocationChecks", _DWORD),
        ("dwUnionChoice", _DWORD),
        ("pFile", ctypes.POINTER(_WINTRUST_FILE_INFO)),
        ("dwStateAction", _DWORD),
        ("hWVTStateData", _HANDLE),
        ("pwszURLReference", wintypes.LPCWSTR),
        ("dwProvFlags", _DWORD),
        ("dwUIContext", _DWORD),
        ("pSignatureSettings", ctypes.c_void_p),
    ]


class _CERT_CONTEXT(ctypes.Structure):
    _fields_ = [
        ("dwCertEncodingType", _DWORD),
        ("pbCertEncoded", ctypes.POINTER(_BYTE)),
        ("cbCertEncoded", _DWORD),
        ("pCertInfo", ctypes.c_void_p),
        ("hCertStore", _HANDLE),
    ]


class _CRYPT_PROVIDER_CERT(ctypes.Structure):
    _fields_ = [
        ("cbStruct", _DWORD),
        ("pCert", ctypes.POINTER(_CERT_CONTEXT)),
        ("fCommercial", _BOOL),
        ("fTrustedRoot", _BOOL),
        ("fSelfSigned", _BOOL),
        ("fTestCert", _BOOL),
        ("dwRevokedReason", _DWORD),
        ("dwConfidence", _DWORD),
        ("dwError", _DWORD),
        ("pTrustListContext", ctypes.c_void_p),
        ("fTrustListSignerCert", _BOOL),
        ("pCtlContext", ctypes.c_void_p),
        ("dwCtlError", _DWORD),
        ("fIsCyclic", _BOOL),
        ("pChainElement", ctypes.c_void_p),
    ]


class _FILETIME(ctypes.Structure):
    _fields_ = [("dwLowDateTime", _DWORD), ("dwHighDateTime", _DWORD)]


class _CRYPT_PROVIDER_SGNR(ctypes.Structure):
    _fields_ = [
        ("cbStruct", _DWORD),
        ("sftVerifyAsOf", _FILETIME),
        ("csCertChain", _DWORD),
        ("pasCertChain", ctypes.c_void_p),
        ("dwSignerType", _DWORD),
        ("psSigner", ctypes.c_void_p),
        ("dwError", _DWORD),
        ("csCounterSigners", _DWORD),
        ("pasCounterSigners", ctypes.c_void_p),
        ("pChainContext", ctypes.c_void_p),
    ]


_GENERIC_VERIFY_V2 = _GUID(
    0x00AAC56B,
    0xCD44,
    0x11D0,
    (_BYTE * 8)(0x8C, 0xC2, 0x00, 0xC0, 0x4F, 0xC2, 0x95, 0xEE),
)


class _WinTrustNative(Protocol):
    def win_verify_trust(
        self,
        hwnd: int | None,
        action: ctypes.POINTER(_GUID),
        data: ctypes.POINTER(_WINTRUST_DATA),
    ) -> int: ...

    def provider_data_from_state(self, state: int | None) -> int | None: ...

    def provider_signer_from_chain(
        self, provider_data: int, signer_index: int, counter_signer: bool, counter_index: int
    ) -> int | None: ...

    def provider_cert_from_chain(self, signer: int, certificate_index: int) -> int | None: ...


class _WinTrustDll:
    """A deliberately tiny wrapper around dynamically-probed Wintrust exports."""

    def __init__(self) -> None:
        if os.name != "nt":
            raise PackageSignerUnavailable("native signature verification is unavailable")
        try:
            dll = ctypes.WinDLL("wintrust.dll", use_last_error=True)
            verify = dll.WinVerifyTrust
            provider_data = dll.WTHelperProvDataFromStateData
            provider_signer = dll.WTHelperGetProvSignerFromChain
            provider_cert = dll.WTHelperGetProvCertFromChain
        except (AttributeError, OSError):
            raise PackageSignerUnavailable("native signature verification is unavailable") from None

        verify.argtypes = [_HANDLE, ctypes.POINTER(_GUID), ctypes.POINTER(_WINTRUST_DATA)]
        verify.restype = _LONG
        provider_data.argtypes = [_HANDLE]
        provider_data.restype = ctypes.c_void_p
        provider_signer.argtypes = [ctypes.c_void_p, _DWORD, _BOOL, _DWORD]
        provider_signer.restype = ctypes.c_void_p
        provider_cert.argtypes = [ctypes.c_void_p, _DWORD]
        provider_cert.restype = ctypes.c_void_p

        self._verify = verify
        self._provider_data = provider_data
        self._provider_signer = provider_signer
        self._provider_cert = provider_cert

    def win_verify_trust(self, hwnd, action, data) -> int:
        return int(self._verify(hwnd, action, data))

    def provider_data_from_state(self, state) -> int | None:
        return self._provider_data(state)

    def provider_signer_from_chain(self, provider_data, signer_index, counter_signer, counter_index) -> int | None:
        return self._provider_signer(provider_data, signer_index, counter_signer, counter_index)

    def provider_cert_from_chain(self, signer, certificate_index) -> int | None:
        return self._provider_cert(signer, certificate_index)


def _system_handle_from_descriptor(descriptor: int) -> int:
    """Return the existing CRT descriptor's Windows file HANDLE, never reopening it."""
    if os.name != "nt":
        raise PackageSignerUnavailable("native signature verification is unavailable")
    try:
        import msvcrt

        handle = msvcrt.get_osfhandle(descriptor)
    except (ImportError, OSError, ValueError):
        raise PackageSignerUnavailable("native signature verification is unavailable") from None
    if handle in (-1, 0):
        raise PackageSignerUnavailable("native signature verification is unavailable")
    return int(handle)


class WindowsMsixSigner:
    """Return the SHA-256 pin of the trusted primary signer's leaf certificate.

    Non-success trust results are fail-closed.  ``None`` is reserved for status
    codes that conclusively identify an unsigned, altered, or untrusted package;
    any unavailable API, offline/unknown status, malformed provider evidence, or
    failure to close provider state raises :class:`PackageSignerUnavailable`.
    """

    def __init__(
        self,
        *,
        native: _WinTrustNative | None = None,
        handle_from_descriptor: Callable[[int], int] = _system_handle_from_descriptor,
    ) -> None:
        self._native = native
        self._handle_from_descriptor = handle_from_descriptor

    def verify(self, *, path: Path, descriptor: int) -> str | None:
        try:
            native = self._native or _WinTrustDll()
        except PackageSignerUnavailable:
            raise _unavailable() from None
        try:
            file_handle = self._handle_from_descriptor(descriptor)
        except PackageSignerUnavailable:
            raise _unavailable() from None
        except Exception:
            raise _unavailable() from None
        if file_handle in (-1, 0):
            raise _unavailable()

        # Keep the Unicode path object, file-info, and trust-data alive across
        # both calls.  The file HANDLE is for exactly the descriptor supplied by
        # preflight; its separate post-verification observations detect changes
        # rather than claiming an operating-system-wide atomic snapshot.
        path_text = str(path)
        file_info = _WINTRUST_FILE_INFO(
            cbStruct=ctypes.sizeof(_WINTRUST_FILE_INFO),
            pcwszFilePath=path_text,
            hFile=ctypes.c_void_p(file_handle),
            pgKnownSubject=None,
        )
        data = _WINTRUST_DATA(
            cbStruct=ctypes.sizeof(_WINTRUST_DATA),
            pPolicyCallbackData=None,
            pSIPClientData=None,
            dwUIChoice=_WTD_UI_NONE,
            fdwRevocationChecks=_WTD_REVOKE_WHOLECHAIN,
            dwUnionChoice=_WTD_CHOICE_FILE,
            pFile=ctypes.pointer(file_info),
            dwStateAction=_WTD_STATEACTION_VERIFY,
            hWVTStateData=None,
            pwszURLReference=None,
            dwProvFlags=_PROVIDER_FLAGS,
            dwUIContext=0,
            pSignatureSettings=None,
        )

        outcome: str | None | PackageSignerUnavailable
        try:
            status = native.win_verify_trust(
                _INVALID_HANDLE_VALUE,
                ctypes.byref(_GENERIC_VERIFY_V2),
                ctypes.byref(data),
            )
            if int(status) == 0:
                outcome = _leaf_sha256_from_verified_state(native, data.hWVTStateData)
            elif (int(status) & 0xFFFFFFFF) in _INVALID_SIGNATURE_STATUSES:
                outcome = None
            else:
                outcome = _unavailable()
        except PackageSignerUnavailable:
            outcome = _unavailable()
        except Exception:
            outcome = _unavailable()
        finally:
            data.dwStateAction = _WTD_STATEACTION_CLOSE
            try:
                close_status = native.win_verify_trust(
                    _INVALID_HANDLE_VALUE,
                    ctypes.byref(_GENERIC_VERIFY_V2),
                    ctypes.byref(data),
                )
                if int(close_status) != 0:
                    outcome = _unavailable()
            except Exception:
                outcome = _unavailable()

        if isinstance(outcome, PackageSignerUnavailable):
            raise outcome
        return outcome


def _leaf_sha256_from_verified_state(native: _WinTrustNative, state: int | None) -> str:
    if not state:
        raise PackageSignerUnavailable("native signature verification is unavailable")
    try:
        provider_data = native.provider_data_from_state(state)
        if not provider_data:
            raise ValueError
        # fCounterSigner=False intentionally selects the authenticated primary
        # package signer rather than a timestamp countersigner.
        signer = native.provider_signer_from_chain(provider_data, 0, False, 0)
        if not signer:
            raise ValueError
        signer_details = ctypes.cast(signer, ctypes.POINTER(_CRYPT_PROVIDER_SGNR)).contents
        if (
            signer_details.cbStruct < ctypes.sizeof(_CRYPT_PROVIDER_SGNR)
            or signer_details.csCertChain == 0
            or signer_details.csCertChain > _MAX_CHAIN_CERTIFICATES
            or signer_details.dwError != 0
            or signer_details.dwSignerType == _SGNR_TYPE_TIMESTAMP
        ):
            raise ValueError
        provider_cert = native.provider_cert_from_chain(signer, 0)
        if not provider_cert:
            raise ValueError
        provider_cert_details = ctypes.cast(
            provider_cert, ctypes.POINTER(_CRYPT_PROVIDER_CERT)
        ).contents
        if (
            provider_cert_details.cbStruct < ctypes.sizeof(_CRYPT_PROVIDER_CERT)
            or provider_cert_details.dwError != 0
            or provider_cert_details.dwRevokedReason != 0
            or provider_cert_details.fTestCert != 0
        ):
            raise ValueError
        cert = provider_cert_details.pCert
        if not cert:
            raise ValueError
        encoded = cert.contents
        size = int(encoded.cbCertEncoded)
        encoding = int(encoded.dwCertEncodingType)
        if (
            size <= 0
            or size > _MAX_LEAF_DER_BYTES
            or not encoded.pbCertEncoded
            or (encoding & _X509_ASN_ENCODING) == 0
            or (encoding & ~_KNOWN_CERT_ENCODINGS) != 0
        ):
            raise ValueError
        der = ctypes.string_at(encoded.pbCertEncoded, size)
    except Exception:
        raise PackageSignerUnavailable("native signature verification is unavailable") from None
    if not _is_single_der_value(der):
        raise PackageSignerUnavailable("native signature verification is unavailable")
    return hashlib.sha256(der).hexdigest()


def _unavailable() -> PackageSignerUnavailable:
    """Avoid exposing a native/fake exception or provider detail to callers."""
    return PackageSignerUnavailable("native signature verification is unavailable")


def _is_single_der_value(value: bytes) -> bool:
    """Require a bounded canonical outer DER SEQUENCE before pinning it."""
    if len(value) < 2 or value[0] != 0x30:
        return False
    first_length = value[1]
    if first_length < 0x80:
        return len(value) == 2 + first_length
    count = first_length & 0x7F
    if count == 0 or count > 4 or len(value) < 2 + count or value[2] == 0:
        return False
    length = int.from_bytes(value[2:2 + count], "big")
    if length < 0x80:
        return False
    return len(value) == 2 + count + length


__all__ = ("WindowsMsixSigner",)
