"""Focused Windows private-update-root tests using only pytest temporary paths."""

from __future__ import annotations

import ctypes
import os
from pathlib import Path, PureWindowsPath
from types import SimpleNamespace

import pytest

from prompt_enhancer.application.paths import HardeningState, PathRejection
from prompt_enhancer.infrastructure.paths import LocalPrivatePathHardener
from prompt_enhancer.infrastructure.paths import windows_private_directory as native_module


class _PrivateDirectoryFake:
    def __init__(self, *, inspection: PathRejection | None = None) -> None:
        self.inspection = inspection
        self.created: list[Path] = []
        self.inspected: list[Path] = []

    def inspect(self, path: Path) -> PathRejection | None:
        self.inspected.append(path)
        return self.inspection

    def create_then_inspect(self, path: Path) -> PathRejection | None:
        self.created.append(path)
        return self.inspection


_USER_SID = bytes((1, 1)) + b"\x00" * 6 + b"\x01\x00\x00\x00"
_SYSTEM_SID = bytes((1, 1)) + b"\x00" * 6 + b"\x02\x00\x00\x00"


def _pointer_value(value: object) -> int:
    if isinstance(value, ctypes.c_void_p):
        assert value.value is not None
        return value.value
    assert isinstance(value, int)
    return value


class _SyntheticAclApi:
    def __init__(self, *, addresses: list[int], bytes_in_use: int, ace_count: int) -> None:
        self.addresses = addresses
        self.bytes_in_use = bytes_in_use
        self.ace_count = ace_count

    def GetAclInformation(self, _dacl: object, out: object, _size: int, _kind: int) -> bool:
        information = ctypes.cast(
            out,
            ctypes.POINTER(native_module._AclSizeInformation),
        ).contents
        information.AceCount = self.ace_count
        information.AclBytesInUse = self.bytes_in_use
        return True

    def GetAce(self, _dacl: object, index: int, out: object) -> bool:
        if index >= len(self.addresses):
            return False
        ctypes.cast(out, ctypes.POINTER(ctypes.c_void_p)).contents.value = self.addresses[index]
        return True

    def IsValidSid(self, _sid: object) -> bool:
        return True

    def GetLengthSid(self, sid: object) -> int:
        address = _pointer_value(sid)
        return native_module._MIN_SID_SIZE + 4 * ctypes.c_ubyte.from_address(
            address + 1
        ).value

    def EqualSid(self, left: object, right: object) -> bool:
        return ctypes.string_at(_pointer_value(left), len(_USER_SID)) == ctypes.string_at(
            _pointer_value(right), len(_USER_SID)
        )


def _synthetic_dacl() -> tuple[ctypes.Array[ctypes.c_char], list[int]]:
    ace_size = native_module._AccessAllowedAce.SidStart.offset + len(_USER_SID)
    buffer = ctypes.create_string_buffer(native_module._MIN_ACL_SIZE + 2 * ace_size)
    addresses: list[int] = []
    for index, sid in enumerate((_USER_SID, _SYSTEM_SID)):
        offset = native_module._MIN_ACL_SIZE + index * ace_size
        ace = native_module._AccessAllowedAce.from_buffer(buffer, offset)
        ace.Header.AceType = native_module._ACCESS_ALLOWED_ACE_TYPE
        ace.Header.AceFlags = (
            native_module._CONTAINER_INHERIT_ACE | native_module._OBJECT_INHERIT_ACE
        )
        ace.Header.AceSize = ace_size
        ace.Mask = native_module._FILE_ALL_ACCESS
        ctypes.memmove(
            ctypes.addressof(buffer) + offset + native_module._AccessAllowedAce.SidStart.offset,
            sid,
            len(sid),
        )
        addresses.append(ctypes.addressof(buffer) + offset)
    return buffer, addresses


def _dacl_verifier(api: _SyntheticAclApi) -> native_module._WindowsPrivateDirectorySecurity:
    verifier = object.__new__(native_module._WindowsPrivateDirectorySecurity)
    verifier._advapi = api
    return verifier


def test_preparer_refuses_any_nonfixed_leaf_without_native_mutation(
    tmp_path: Path,
) -> None:
    native = _PrivateDirectoryFake()
    hardener = LocalPrivatePathHardener(
        platform_name="nt",
        windows_private_directory=native,
    )

    result = hardener.prepare_private_update_staging_root(tmp_path / "other-cache")

    assert result.state is HardeningState.REJECTED
    assert result.reason is PathRejection.OUTSIDE_PRIVATE_ROOT
    assert native.created == []
    assert native.inspected == []


@pytest.mark.parametrize(
    ("target", "reason"),
    [
        (Path("application-updates"), PathRejection.OUTSIDE_PRIVATE_ROOT),
        (Path("..") / "application-updates", PathRejection.TRAVERSAL_COMPONENT),
        (PureWindowsPath("C:application-updates"), PathRejection.DRIVE_RELATIVE),
    ],
)
def test_preparer_rejects_raw_ambiguous_input_before_native_creation(
    tmp_path: Path,
    target: Path | PureWindowsPath,
    reason: PathRejection,
) -> None:
    native = _PrivateDirectoryFake()
    hardener = LocalPrivatePathHardener(
        platform_name="nt",
        windows_private_directory=native,
    )

    result = hardener.prepare_private_update_staging_root(target)

    assert result.state is HardeningState.REJECTED
    assert result.reason is reason
    assert native.created == []
    assert native.inspected == []


def test_existing_fixed_leaf_is_inspected_without_acl_creation(tmp_path: Path) -> None:
    target = tmp_path / "application-updates"
    target.mkdir()
    native = _PrivateDirectoryFake()
    hardener = LocalPrivatePathHardener(
        platform_name="nt",
        windows_private_directory=native,
    )

    result = hardener.prepare_private_update_staging_root(target)

    assert result.state is HardeningState.HARDENED
    assert native.created == []
    assert native.inspected == [target]


def test_existing_nonprivate_leaf_is_refused_without_acl_rewrite(tmp_path: Path) -> None:
    target = tmp_path / "application-updates"
    target.mkdir()
    native = _PrivateDirectoryFake(inspection=PathRejection.PERMISSIONS_UNVERIFIED)
    hardener = LocalPrivatePathHardener(
        platform_name="nt",
        windows_private_directory=native,
    )

    result = hardener.prepare_private_update_staging_root(target)

    assert result.state is HardeningState.REJECTED
    assert result.reason is PathRejection.PERMISSIONS_UNVERIFIED
    assert native.created == []


def test_preparer_never_creates_missing_parent_directories(tmp_path: Path) -> None:
    native = _PrivateDirectoryFake()
    hardener = LocalPrivatePathHardener(
        platform_name="nt",
        windows_private_directory=native,
    )
    target = tmp_path / "missing-parent" / "application-updates"

    result = hardener.prepare_private_update_staging_root(target)

    assert result.state is HardeningState.REJECTED
    assert result.reason is PathRejection.INSPECTION_FAILED
    assert native.created == []
    assert not target.parent.exists()


def test_create_failure_never_claims_hardened(tmp_path: Path) -> None:
    native = _PrivateDirectoryFake(inspection=PathRejection.INSPECTION_FAILED)
    hardener = LocalPrivatePathHardener(
        platform_name="nt",
        windows_private_directory=native,
    )
    target = tmp_path / "application-updates"

    result = hardener.prepare_private_update_staging_root(target)

    assert result.state is HardeningState.REJECTED
    assert result.reason is PathRejection.INSPECTION_FAILED
    assert native.created == [target]


def test_dacl_verifier_accepts_only_the_two_bounded_exact_aces() -> None:
    buffer, addresses = _synthetic_dacl()
    api = _SyntheticAclApi(
        addresses=addresses,
        bytes_in_use=ctypes.sizeof(buffer),
        ace_count=2,
    )
    verifier = _dacl_verifier(api)
    user, system = ctypes.create_string_buffer(_USER_SID), ctypes.create_string_buffer(_SYSTEM_SID)

    result = verifier._verify_exact_dacl(
        ctypes.c_void_p(ctypes.addressof(buffer)),
        user,
        system,
    )

    assert result is None


@pytest.mark.parametrize("ace_count", [0, 1, 3])
def test_dacl_verifier_rejects_missing_or_extra_aces(ace_count: int) -> None:
    buffer, addresses = _synthetic_dacl()
    verifier = _dacl_verifier(
        _SyntheticAclApi(
            addresses=addresses,
            bytes_in_use=ctypes.sizeof(buffer),
            ace_count=ace_count,
        )
    )
    user, system = ctypes.create_string_buffer(_USER_SID), ctypes.create_string_buffer(_SYSTEM_SID)

    result = verifier._verify_exact_dacl(
        ctypes.c_void_p(ctypes.addressof(buffer)),
        user,
        system,
    )

    assert result is PathRejection.PERMISSIONS_UNVERIFIED


def test_dacl_verifier_rejects_out_of_range_ace_before_dereference() -> None:
    buffer, _ = _synthetic_dacl()
    verifier = _dacl_verifier(
        _SyntheticAclApi(
            addresses=[ctypes.addressof(buffer) + ctypes.sizeof(buffer)],
            bytes_in_use=ctypes.sizeof(buffer),
            ace_count=2,
        )
    )
    user, system = ctypes.create_string_buffer(_USER_SID), ctypes.create_string_buffer(_SYSTEM_SID)

    result = verifier._verify_exact_dacl(
        ctypes.c_void_p(ctypes.addressof(buffer)),
        user,
        system,
    )

    assert result is PathRejection.PERMISSIONS_UNVERIFIED


@pytest.mark.parametrize("mutation", ["inherited", "truncated"])
def test_dacl_verifier_rejects_inherited_or_malformed_ace(mutation: str) -> None:
    buffer, addresses = _synthetic_dacl()
    ace = native_module._AccessAllowedAce.from_address(addresses[0])
    if mutation == "inherited":
        ace.Header.AceFlags |= native_module._INHERITED_ACE
    else:
        ace.Header.AceSize = native_module._AccessAllowedAce.SidStart.offset
    verifier = _dacl_verifier(
        _SyntheticAclApi(
            addresses=addresses,
            bytes_in_use=ctypes.sizeof(buffer),
            ace_count=2,
        )
    )
    user, system = ctypes.create_string_buffer(_USER_SID), ctypes.create_string_buffer(_SYSTEM_SID)

    result = verifier._verify_exact_dacl(
        ctypes.c_void_p(ctypes.addressof(buffer)),
        user,
        system,
    )

    assert result is PathRejection.PERMISSIONS_UNVERIFIED


class _SyntheticDescriptorApi:
    def __init__(self, *, control: int, owner: int, dacl: int | None) -> None:
        self.control = control
        self.owner = owner
        self.dacl = dacl
        self.descriptor = ctypes.create_string_buffer(32)

    def GetSecurityInfo(
        self,
        _handle: object,
        _kind: int,
        _information: int,
        owner: object,
        _group: object,
        dacl: object,
        _sacl: object,
        descriptor: object,
    ) -> int:
        ctypes.cast(owner, ctypes.POINTER(ctypes.c_void_p)).contents.value = self.owner
        ctypes.cast(dacl, ctypes.POINTER(ctypes.c_void_p)).contents.value = self.dacl
        ctypes.cast(descriptor, ctypes.POINTER(ctypes.c_void_p)).contents.value = ctypes.addressof(
            self.descriptor
        )
        return 0

    def GetSecurityDescriptorControl(self, _descriptor: object, control: object, _revision: object) -> bool:
        ctypes.cast(control, ctypes.POINTER(ctypes.c_ushort)).contents.value = self.control
        return True

    def GetSecurityDescriptorDacl(
        self,
        _descriptor: object,
        present: object,
        dacl: object,
        _defaulted: object,
    ) -> bool:
        ctypes.cast(present, ctypes.POINTER(ctypes.c_int)).contents.value = int(
            self.dacl is not None
        )
        ctypes.cast(dacl, ctypes.POINTER(ctypes.c_void_p)).contents.value = self.dacl
        return True

    def EqualSid(self, left: object, right: object) -> bool:
        return ctypes.string_at(_pointer_value(left), len(_USER_SID)) == ctypes.string_at(
            _pointer_value(right), len(_USER_SID)
        )


@pytest.mark.parametrize(
    ("control", "owner_kind", "dacl_present"),
    [
        (0, "user", True),
        (native_module._SE_DACL_PROTECTED, "system", True),
        (native_module._SE_DACL_PROTECTED, "user", False),
    ],
)
def test_descriptor_verifier_rejects_nonprotected_wrong_owner_or_null_dacl(
    control: int,
    owner_kind: str,
    dacl_present: bool,
) -> None:
    user, system = ctypes.create_string_buffer(_USER_SID), ctypes.create_string_buffer(_SYSTEM_SID)
    dacl = ctypes.create_string_buffer(32)
    api = _SyntheticDescriptorApi(
        control=control,
        owner=ctypes.addressof(user if owner_kind == "user" else system),
        dacl=ctypes.addressof(dacl) if dacl_present else None,
    )
    verifier = object.__new__(native_module._WindowsPrivateDirectorySecurity)
    verifier._advapi = api
    verifier._kernel = SimpleNamespace(LocalFree=lambda _value: None)
    verifier._current_process_user_sid = lambda: _USER_SID
    verifier._local_system_sid = lambda: _SYSTEM_SID
    verifier._verify_exact_dacl = lambda *_args: None

    result = verifier._verify_descriptor(ctypes.c_void_p(1))

    assert result is PathRejection.PERMISSIONS_UNVERIFIED


def test_unavailable_native_loader_is_typed_and_never_hardened(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    target = tmp_path / "application-updates"
    target.mkdir()
    monkeypatch.setattr(
        native_module.ctypes,
        "WinDLL",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("synthetic unavailable")),
        raising=False,
    )
    hardener = LocalPrivatePathHardener(platform_name="nt")

    result = hardener.inspect(target)

    assert result.state is HardeningState.UNVERIFIED
    assert result.reason is PathRejection.WINDOWS_DACL_UNAVAILABLE


@pytest.mark.skipif(os.name != "nt", reason="Win32 DACL inspection is Windows-only")
def test_windows_preparer_creates_and_rechecks_private_temp_child(tmp_path: Path) -> None:
    target = tmp_path / "application-updates"
    hardener = LocalPrivatePathHardener()

    created = hardener.prepare_private_update_staging_root(target)
    inspected = hardener.inspect(target)

    assert created.state is HardeningState.HARDENED
    assert inspected.state is HardeningState.HARDENED
    assert target.is_dir()


@pytest.mark.skipif(os.name != "nt", reason="Win32 DACL inspection is Windows-only")
def test_windows_default_inherited_temp_directory_is_not_claimed_private(
    tmp_path: Path,
) -> None:
    target = tmp_path / "application-updates"
    target.mkdir()

    result = LocalPrivatePathHardener().inspect(target)

    assert result.state is not HardeningState.HARDENED
