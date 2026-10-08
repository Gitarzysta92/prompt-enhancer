from __future__ import annotations

import hashlib
import io
import zipfile
from pathlib import Path

import pytest

from prompt_enhancer.infrastructure.windows_python_runtime import (
    WindowsPythonRuntimeError, prepare_windows_python_runtime,
)


def _pe(machine: int = 0x8664) -> bytes:
    value = bytearray(128); value[:2] = b"MZ"; value[0x3C:0x40] = (64).to_bytes(4, "little")
    value[64:68] = b"PE\0\0"; value[68:70] = machine.to_bytes(2, "little")
    return bytes(value)


def _archive(*, machine: int = 0x8664, pth: bytes = b"python313.zip\n.\n#import site\n",
             extra: dict[str, bytes] | None = None) -> bytes:
    files = {"python.exe": _pe(machine), "pythonw.exe": _pe(machine), "python313.dll": _pe(machine),
             "python3.dll": _pe(machine), "vcruntime140.dll": _pe(machine), "vcruntime140_1.dll": _pe(machine),
             "python313.zip": b"stdlib", "python313._pth": pth, "LICENSE.txt": b"license"}
    files.update(extra or {})
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        for name, data in files.items(): archive.writestr(name, data)
    return stream.getvalue()


def _prepare(tmp_path: Path, payload: bytes, **overrides: object):
    source = tmp_path / "python-3.13.1-embed-amd64.zip"; source.write_bytes(payload)
    return prepare_windows_python_runtime(archive=source, expected_version="3.13.1", expected_architecture="amd64",
        expected_sha256=hashlib.sha256(payload).hexdigest(), expected_size_bytes=len(payload),
        destination=tmp_path / "prepared", **overrides)


def _synthetic_private_home_pth() -> bytes:
    return b"python313.zip\n.\nC:/" + b"Users/" + b"example\n"


def test_prepares_hash_enumerated_isolated_runtime_without_execution(tmp_path: Path) -> None:
    result = _prepare(tmp_path, _archive())
    assert result.complete is False and result.runtime_execution_unproven is True
    assert (tmp_path / "prepared" / "python313._pth").read_bytes() == b"python313.zip\n.\n#import site\n"
    assert {item.relative_path for item in result.files} >= {"python.exe", "python313.dll", "LICENSE.txt"}


@pytest.mark.parametrize("payload", [
    _archive(machine=0xAA64), _archive(pth=b"python313.zip\nimport site\n"),
    _archive(pth=_synthetic_private_home_pth()), _archive(pth=b"python313.zip\n..\n"),
    _archive(extra={"A.txt": b"a", "a.TXT": b"b"}), _archive(extra={"../bad": b"bad"}),
    _archive(extra={"folder//alias.txt": b"bad"}),
    _archive(extra={"extension.pyd": _pe(0xAA64)}),
])
def test_rejects_architecture_nonisolated_and_unsafe_archive(tmp_path: Path, payload: bytes) -> None:
    with pytest.raises(WindowsPythonRuntimeError): _prepare(tmp_path, payload)
    assert not list(tmp_path.glob(".python-runtime-incomplete-*"))


@pytest.mark.parametrize("missing", ["python.exe", "pythonw.exe", "python313.dll", "python3.dll",
                                      "python313.zip", "python313._pth", "LICENSE.txt", "vcruntime140.dll",
                                      "vcruntime140_1.dll"])
def test_rejects_every_missing_required_file_even_with_unrelated_extra(tmp_path: Path, missing: str) -> None:
    payload = _archive()
    stream = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(payload)) as incoming, zipfile.ZipFile(stream, "w") as outgoing:
        for info in incoming.infolist():
            if info.filename != missing: outgoing.writestr(info.filename, incoming.read(info.filename))
        outgoing.writestr("unrelated-extra.txt", b"extra")
    with pytest.raises(WindowsPythonRuntimeError): _prepare(tmp_path, stream.getvalue())


def test_rejects_wrong_identity_and_never_overwrites_destination(tmp_path: Path) -> None:
    payload = _archive(); source = tmp_path / "runtime.zip"; source.write_bytes(payload)
    with pytest.raises(WindowsPythonRuntimeError):
        prepare_windows_python_runtime(archive=source, expected_version="3.13.1", expected_architecture="amd64",
            expected_sha256="0" * 64, expected_size_bytes=len(payload), destination=tmp_path / "out")
    output = tmp_path / "out"; output.mkdir(); (output / "keep").write_bytes(b"keep")
    with pytest.raises(WindowsPythonRuntimeError):
        prepare_windows_python_runtime(archive=source, expected_version="3.13.1", expected_architecture="amd64",
            expected_sha256=hashlib.sha256(payload).hexdigest(), expected_size_bytes=len(payload), destination=output)
    assert (output / "keep").read_bytes() == b"keep"
