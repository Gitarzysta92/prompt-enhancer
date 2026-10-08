"""Synthetic contract tests for the bounded native MSIX signer.

No test opens a package installer, contacts a trust endpoint, or consults the
real certificate store.  The fake below models only documented Wintrust calls.
"""

from __future__ import annotations

import ctypes
import hashlib
import os
from pathlib import Path
import zipfile

import pytest

from prompt_enhancer.infrastructure.updates.msix_preflight import PackageSignerUnavailable
from prompt_enhancer.infrastructure.updates.windows_msix_signer import (
    WindowsMsixSigner,
    _BYTE,
    _CERT_CONTEXT,
    _CRYPT_PROVIDER_CERT,
    _CRYPT_PROVIDER_SGNR,
    _GENERIC_VERIFY_V2,
    _MAX_CHAIN_CERTIFICATES,
    _MAX_LEAF_DER_BYTES,
    _WINTRUST_DATA,
    _WINTRUST_FILE_INFO,
    _WinTrustDll,
    _WTD_CACHE_ONLY_URL_RETRIEVAL,
    _WTD_REVOCATION_CHECK_CHAIN_EXCLUDE_ROOT,
    _WTD_STATEACTION_CLOSE,
    _WTD_STATEACTION_VERIFY,
)


_DER = b"\x30\x03\x02\x01\x01"


class _FakeWinTrust:
    def __init__(
        self,
        *,
        verify_status: int = 0,
        close_status: int = 0,
        verify_error: Exception | None = None,
        close_error: Exception | None = None,
        der: bytes = _DER,
        include_evidence: bool = True,
    ) -> None:
        self.verify_status = verify_status
        self.close_status = close_status
        self.verify_error = verify_error
        self.close_error = close_error
        self.include_evidence = include_evidence
        self.calls: list[dict[str, int]] = []
        self.signer_calls: list[tuple[int, int, bool, int]] = []
        self._der = (_BYTE * len(der)).from_buffer_copy(der)
        self._context = _CERT_CONTEXT(
            dwCertEncodingType=1,
            pbCertEncoded=ctypes.cast(self._der, ctypes.POINTER(_BYTE)),
            cbCertEncoded=len(der),
            pCertInfo=None,
            hCertStore=None,
        )
        self._provider_cert = _CRYPT_PROVIDER_CERT(
            cbStruct=ctypes.sizeof(_CRYPT_PROVIDER_CERT),
            pCert=ctypes.pointer(self._context),
        )
        self._provider_signer = _CRYPT_PROVIDER_SGNR(
            cbStruct=ctypes.sizeof(_CRYPT_PROVIDER_SGNR),
            csCertChain=1,
            dwSignerType=0,
            dwError=0,
        )

    def win_verify_trust(self, hwnd, action, data) -> int:
        trust_data = ctypes.cast(data, ctypes.POINTER(_WINTRUST_DATA)).contents
        guid = ctypes.cast(action, ctypes.POINTER(type(_GENERIC_VERIFY_V2))).contents
        file_info = ctypes.cast(trust_data.pFile, ctypes.POINTER(_WINTRUST_FILE_INFO)).contents
        self.calls.append({
            "action": trust_data.dwStateAction,
            "hwnd": int(hwnd),
            "guid_data1": guid.Data1,
            "guid_data2": guid.Data2,
            "guid_data3": guid.Data3,
            "guid_data4": bytes(guid.Data4),
            "ui": trust_data.dwUIChoice,
            "file_choice": trust_data.dwUnionChoice,
            "handle": int(file_info.hFile),
            "flags": trust_data.dwProvFlags,
            "revoke": trust_data.fdwRevocationChecks,
        })
        if trust_data.dwStateAction == _WTD_STATEACTION_VERIFY:
            if self.verify_error is not None:
                raise self.verify_error
            trust_data.hWVTStateData = 73
            return self.verify_status
        assert trust_data.dwStateAction == _WTD_STATEACTION_CLOSE
        if self.close_error is not None:
            raise self.close_error
        return self.close_status

    def provider_data_from_state(self, state: int) -> int | None:
        return 101 if self.include_evidence and state == 73 else None

    def provider_signer_from_chain(
        self, provider_data: int, signer_index: int, counter_signer: bool, counter_index: int
    ) -> int | None:
        self.signer_calls.append((provider_data, signer_index, counter_signer, counter_index))
        if not self.include_evidence or provider_data != 101:
            return None
        return ctypes.addressof(self._provider_signer)

    def provider_cert_from_chain(self, signer: int, certificate_index: int) -> int | None:
        if (
            not self.include_evidence
            or signer != ctypes.addressof(self._provider_signer)
            or certificate_index != 0
        ):
            return None
        return ctypes.addressof(self._provider_cert)


def _signer(fake: _FakeWinTrust, *, handle: int = 919) -> WindowsMsixSigner:
    return WindowsMsixSigner(native=fake, handle_from_descriptor=lambda descriptor: handle)


def test_success_pins_primary_authenticated_leaf_and_uses_no_ui_network_flags() -> None:
    fake = _FakeWinTrust()

    result = _signer(fake).verify(path=Path("C:/synthetic/release.msix"), descriptor=41)

    assert result == hashlib.sha256(_DER).hexdigest()
    assert [call["action"] for call in fake.calls] == [
        _WTD_STATEACTION_VERIFY,
        _WTD_STATEACTION_CLOSE,
    ]
    verify, close = fake.calls
    assert verify["hwnd"] == ctypes.c_void_p(-1).value
    assert verify["handle"] == 919 == close["handle"]
    assert verify["ui"] == 2
    assert verify["file_choice"] == 1
    assert verify["revoke"] == 1
    assert verify["flags"] == (
        _WTD_CACHE_ONLY_URL_RETRIEVAL | _WTD_REVOCATION_CHECK_CHAIN_EXCLUDE_ROOT
    )
    assert (verify["guid_data1"], verify["guid_data2"], verify["guid_data3"], verify["guid_data4"]) == (
        0x00AAC56B,
        0xCD44,
        0x11D0,
        b"\x8c\xc2\x00\xc0\x4f\xc2\x95\xee",
    )
    assert fake.signer_calls == [(101, 0, False, 0)]


@pytest.mark.parametrize("status", [0x800B0100, 0x80096010, 0x800B0109])
def test_known_unsigned_bad_digest_or_untrusted_status_returns_none_and_closes(status: int) -> None:
    fake = _FakeWinTrust(verify_status=status)

    assert _signer(fake).verify(path=Path("C:/synthetic/release.msix"), descriptor=3) is None
    assert [call["action"] for call in fake.calls] == [1, 2]


def test_nonzero_positive_long_is_never_treated_as_success() -> None:
    fake = _FakeWinTrust(verify_status=1)

    with pytest.raises(PackageSignerUnavailable):
        _signer(fake).verify(path=Path("C:/synthetic/release.msix"), descriptor=3)

    assert [call["action"] for call in fake.calls] == [1, 2]


@pytest.mark.parametrize("status", [-1, 0x80092013, 0x800B010A])
def test_negative_or_offline_revocation_status_is_unavailable_not_unsigned(status: int) -> None:
    fake = _FakeWinTrust(verify_status=status)

    with pytest.raises(PackageSignerUnavailable):
        _signer(fake).verify(path=Path("C:/synthetic/release.msix"), descriptor=3)

    assert [call["action"] for call in fake.calls] == [1, 2]


def test_verify_exception_still_closes_provider_state_and_fails_closed() -> None:
    fake = _FakeWinTrust(verify_error=RuntimeError("synthetic native failure"))

    with pytest.raises(PackageSignerUnavailable):
        _signer(fake).verify(path=Path("C:/synthetic/release.msix"), descriptor=3)

    assert [call["action"] for call in fake.calls] == [1, 2]


@pytest.mark.parametrize("close_status", [1, 0x80004005])
def test_close_failure_overrides_any_result_and_fails_closed(close_status: int) -> None:
    fake = _FakeWinTrust(close_status=close_status)

    with pytest.raises(PackageSignerUnavailable):
        _signer(fake).verify(path=Path("C:/synthetic/release.msix"), descriptor=3)

    assert [call["action"] for call in fake.calls] == [1, 2]


def test_close_exception_is_cleanup_uncertainty_and_fails_closed() -> None:
    fake = _FakeWinTrust(close_error=RuntimeError("synthetic close failure"))

    with pytest.raises(PackageSignerUnavailable):
        _signer(fake).verify(path=Path("C:/synthetic/release.msix"), descriptor=3)

    assert [call["action"] for call in fake.calls] == [1, 2]


def test_verify_failure_plus_close_failure_remains_unavailable() -> None:
    fake = _FakeWinTrust(verify_status=0x800B0100, close_error=RuntimeError("close"))

    with pytest.raises(PackageSignerUnavailable):
        _signer(fake).verify(path=Path("C:/synthetic/release.msix"), descriptor=3)

    assert [call["action"] for call in fake.calls] == [1, 2]


def test_missing_or_malformed_authenticated_leaf_evidence_fails_closed() -> None:
    missing = _FakeWinTrust(include_evidence=False)
    malformed = _FakeWinTrust(der=b"not-a-certificate")

    with pytest.raises(PackageSignerUnavailable):
        _signer(missing).verify(path=Path("C:/synthetic/release.msix"), descriptor=3)
    with pytest.raises(PackageSignerUnavailable):
        _signer(malformed).verify(path=Path("C:/synthetic/release.msix"), descriptor=3)


def test_oversized_certificate_is_rejected_before_copying(monkeypatch: pytest.MonkeyPatch) -> None:
    # Retain a tiny backing buffer while presenting a huge untrusted length.  A
    # correct verifier rejects the length before calling ctypes.string_at.
    fake = _FakeWinTrust()
    fake._context.cbCertEncoded = _MAX_LEAF_DER_BYTES + 1
    monkeypatch.setattr(
        ctypes,
        "string_at",
        lambda *_args: pytest.fail("certificate bytes must not be copied past the bound"),
    )

    with pytest.raises(PackageSignerUnavailable):
        _signer(fake).verify(path=Path("C:/synthetic/release.msix"), descriptor=3)

    assert [call["action"] for call in fake.calls] == [1, 2]


@pytest.mark.parametrize("handle", [-1, 0])
def test_invalid_descriptor_handle_fails_without_native_trust_call(handle: int) -> None:
    fake = _FakeWinTrust()
    signer = WindowsMsixSigner(native=fake, handle_from_descriptor=lambda _descriptor: handle)

    with pytest.raises(PackageSignerUnavailable):
        signer.verify(path=Path("C:/synthetic/release.msix"), descriptor=3)

    assert fake.calls == []


@pytest.mark.parametrize(
    "change",
    [
        lambda fake: setattr(fake._provider_signer, "cbStruct", 0),
        lambda fake: setattr(fake._provider_signer, "csCertChain", 0),
        lambda fake: setattr(fake._provider_signer, "csCertChain", _MAX_CHAIN_CERTIFICATES + 1),
        lambda fake: setattr(fake._provider_signer, "dwError", 1),
        lambda fake: setattr(fake._provider_signer, "dwSignerType", 0x10),
        lambda fake: setattr(fake._provider_cert, "cbStruct", 0),
        lambda fake: setattr(fake._provider_cert, "dwError", 1),
        lambda fake: setattr(fake._provider_cert, "dwRevokedReason", 1),
        lambda fake: setattr(fake._provider_cert, "fTestCert", 1),
        lambda fake: setattr(fake._context, "pbCertEncoded", None),
        lambda fake: setattr(fake._context, "cbCertEncoded", 0),
        lambda fake: setattr(fake._context, "dwCertEncodingType", 0x20000),
    ],
)
def test_uncertain_signer_or_certificate_evidence_is_rejected_before_pin(
    change,
) -> None:
    fake = _FakeWinTrust()
    change(fake)

    with pytest.raises(PackageSignerUnavailable):
        _signer(fake).verify(path=Path("C:/synthetic/release.msix"), descriptor=3)

    assert [call["action"] for call in fake.calls] == [1, 2]


def test_missing_native_helper_export_fails_closed_after_state_close() -> None:
    fake = _FakeWinTrust()

    class _MissingHelpers:
        win_verify_trust = fake.win_verify_trust

    with pytest.raises(PackageSignerUnavailable):
        WindowsMsixSigner(native=_MissingHelpers(), handle_from_descriptor=lambda _fd: 12).verify(
            path=Path("C:/synthetic/release.msix"), descriptor=3
        )

    assert [call["action"] for call in fake.calls] == [1, 2]


def test_injected_unavailable_detail_is_sanitized() -> None:
    fake = _FakeWinTrust()

    def unavailable_handle(_descriptor: int) -> int:
        raise PackageSignerUnavailable("synthetic provider detail must not escape")

    with pytest.raises(PackageSignerUnavailable, match="^native signature verification is unavailable$"):
        WindowsMsixSigner(native=fake, handle_from_descriptor=unavailable_handle).verify(
            path=Path("C:/synthetic/release.msix"), descriptor=3
        )

    assert fake.calls == []


@pytest.mark.skipif(os.name != "nt", reason="WinVerifyTrust is Windows-only")
def test_native_unsigned_container_fail_closed_smoke(tmp_path: Path) -> None:
    """Exercise actual Wintrust on an unsigned container; this is not package proof."""
    package = tmp_path / "unsigned-synthetic.msix"
    with zipfile.ZipFile(package, "w", compression=zipfile.ZIP_STORED) as archive:
        archive.writestr("AppxManifest.xml", b"<Package />")
        archive.writestr("[Content_Types].xml", b"<Types />")
    descriptor = os.open(package, os.O_RDONLY | getattr(os, "O_BINARY", 0))
    try:
        # Deliberately load the concrete adapter before the verifier.  A missing
        # DLL/export is a test failure, never synthetic acceptance.
        actual = _WinTrustDll()

        class _ObservedNative:
            def __init__(self) -> None:
                self.calls: list[int] = []
                self.verify_status: int | None = None
                self.close_status: int | None = None
                self.verify_exception: type[BaseException] | None = None
                self.close_exception: type[BaseException] | None = None

            def win_verify_trust(self, hwnd, action, data) -> int:
                trust_data = ctypes.cast(data, ctypes.POINTER(_WINTRUST_DATA)).contents
                state_action = int(trust_data.dwStateAction)
                self.calls.append(state_action)
                try:
                    status = actual.win_verify_trust(hwnd, action, data)
                except BaseException as error:
                    if state_action == _WTD_STATEACTION_VERIFY:
                        self.verify_exception = type(error)
                    else:
                        self.close_exception = type(error)
                    raise
                if state_action == _WTD_STATEACTION_VERIFY:
                    self.verify_status = int(status)
                else:
                    self.close_status = int(status)
                return int(status)

            def provider_data_from_state(self, state):
                return actual.provider_data_from_state(state)

            def provider_signer_from_chain(self, provider_data, signer_index, counter_signer, counter_index):
                return actual.provider_signer_from_chain(
                    provider_data, signer_index, counter_signer, counter_index
                )

            def provider_cert_from_chain(self, signer, certificate_index):
                return actual.provider_cert_from_chain(signer, certificate_index)

        observed = _ObservedNative()
        outcome: str
        try:
            result = WindowsMsixSigner(native=observed).verify(path=package, descriptor=descriptor)
        except PackageSignerUnavailable:
            outcome = "unavailable"
        else:
            outcome = "unsigned"
            assert result is None

        assert observed.calls == [_WTD_STATEACTION_VERIFY, _WTD_STATEACTION_CLOSE]
        assert observed.verify_status is not None or observed.verify_exception is not None
        # A rejected unsigned container need not allocate state.  If CLOSE then
        # reports uncertainty, the public verifier must remain unavailable rather
        # than imply a clean signature-verification result.
        if observed.close_status not in (None, 0) or observed.close_exception is not None:
            assert outcome == "unavailable"
    finally:
        os.close(descriptor)
