"""Offline, synthetic regression tests for the reviewed proxy-tools builder."""

from __future__ import annotations

import csv
import hashlib
import io
import tarfile
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from prompt_enhancer.infrastructure import proxy_tools_wheel_preparation as prep


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _source_archive(files: dict[str, bytes]) -> bytes:
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w:gz") as archive:
        for directory in ("proxy_tools-0.1.0", "proxy_tools-0.1.0/proxy_tools"):
            info = tarfile.TarInfo(directory)
            info.type = tarfile.DIRTYPE
            archive.addfile(info)
        for name, data in files.items():
            info = tarfile.TarInfo(f"proxy_tools-0.1.0/{name}")
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
    return stream.getvalue()


def _wheel(module: bytes, *, extra_file: bool = False) -> bytes:
    files = {
        "proxy_tools/__init__.py": module,
        "proxy_tools-0.1.0.dist-info/METADATA": b"Metadata-Version: 2.4\nName: proxy-tools\nVersion: 0.1.0\nLicense: MIT\n",
        "proxy_tools-0.1.0.dist-info/WHEEL": b"Wheel-Version: 1.0\nRoot-Is-Purelib: true\nTag: py3-none-any\n",
        "proxy_tools-0.1.0.dist-info/top_level.txt": b"proxy_tools\n",
    }
    if extra_file:
        files["unexpected.py"] = b"x"
    record_name = "proxy_tools-0.1.0.dist-info/RECORD"
    record = []
    for name, data in files.items():
        record.append([name, prep._record_digest(data), str(len(data))])
    record.append([record_name, "", ""])
    files[record_name] = "\n".join(",".join(row) for row in record).encode("utf-8") + b"\n"
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_STORED) as archive:
        for name, data in files.items():
            info = zipfile.ZipInfo(name, date_time=(2020, 1, 1, 0, 0, 0))
            info.external_attr = 0o100644 << 16
            archive.writestr(info, data)
    return stream.getvalue()


@pytest.fixture
def synthetic_inputs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, object]:
    module = b"__version__ = '0.1.0'\n"
    source_files = {"proxy_tools/__init__.py": module, "setup.py": b"from setuptools import setup\n"}
    source = _source_archive(source_files)
    source_path = tmp_path / "reviewed-source.tar.gz"
    source_path.write_bytes(source)
    setuptools = io.BytesIO()
    with zipfile.ZipFile(setuptools, "w") as archive:
        archive.writestr("setuptools/__init__.py", b"")
    setuptools_path = tmp_path / "setuptools-84.0.0-py3-none-any.whl"
    setuptools_path.write_bytes(setuptools.getvalue())
    python = tmp_path / "python.exe"
    python.write_bytes(b"synthetic-python")
    monkeypatch.setattr(prep, "_SOURCE_MEMBERS", {
        name: (len(data), _sha256(data)) for name, data in source_files.items()
    })
    monkeypatch.setattr(prep, "_SOURCE_SIZE", len(source))
    monkeypatch.setattr(prep, "_SOURCE_SHA", _sha256(source))
    monkeypatch.setattr(prep, "_SETUPTOOLS_SIZE", len(setuptools.getvalue()))
    monkeypatch.setattr(prep, "_SETUPTOOLS_SHA", _sha256(setuptools.getvalue()))
    return {"module": module, "source": source_path, "setuptools": setuptools_path, "python": python}


def test_checked_input_fails_closed_for_wrong_digest(tmp_path: Path) -> None:
    input_file = tmp_path / "input"
    input_file.write_bytes(b"wrong")
    with pytest.raises(prep.ProxyToolsWheelPreparationError):
        prep._read_verified_file(input_file, size=5, sha256="0" * 64, maximum_size=10)


def test_checked_ordinary_executable_allows_windows_handle_mode_difference(tmp_path: Path) -> None:
    executable = tmp_path / "python.exe"
    data = b"synthetic-python"
    executable.write_bytes(data)
    assert prep._read_verified_file(
        executable, size=len(data), sha256=_sha256(data), maximum_size=32
    ) == data


def test_checked_input_binds_bytes_to_the_opened_file_identity(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    reviewed = tmp_path / "reviewed-input"
    substitute = tmp_path / "substitute-input"
    reviewed.write_bytes(b"reviewed")
    substitute.write_bytes(b"attacker")
    real_open = Path.open

    def redirected_open(path: Path, *args: object, **kwargs: object) -> object:
        return real_open(substitute if path == reviewed else path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", redirected_open)
    with pytest.raises(prep.ProxyToolsWheelPreparationError):
        prep._read_verified_file(
            reviewed,
            size=len(b"attacker"),
            sha256=_sha256(b"attacker"),
            maximum_size=32,
        )


def test_build_output_binds_bytes_to_the_opened_file_identity(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    reviewed = tmp_path / "reviewed-output.whl"
    substitute = tmp_path / "substitute-output.whl"
    reviewed.write_bytes(b"reviewed")
    substitute.write_bytes(b"attacker")
    real_open = Path.open

    def redirected_open(path: Path, *args: object, **kwargs: object) -> object:
        return real_open(substitute if path == reviewed else path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", redirected_open)
    with pytest.raises(prep.ProxyToolsWheelPreparationError):
        prep._read_bounded_regular_file(reviewed, 32)


@pytest.mark.parametrize("output,accepted", [(b"3.13.1\n", True), (b"3.13.1\r\n", True),
                                               (b"3.13.1 \n", False)])
def test_python_version_probe_allows_only_lf_or_crlf(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch, output: bytes, accepted: bool) -> None:
    executable = tmp_path / "python.exe"
    executable.write_bytes(b"synthetic-python")
    monkeypatch.setattr(prep, "run_owned_process", lambda *args, **kwargs: SimpleNamespace(
        returncode=0, stdout=output))
    if accepted:
        prep._verify_python_version(executable, "3.13.1", tmp_path)
    else:
        with pytest.raises(prep.ProxyToolsWheelPreparationError):
            prep._verify_python_version(executable, "3.13.1", tmp_path)


@pytest.mark.parametrize("name", ["../x", "C:/x", "aux/x", "a\\b", "x/COM1.txt", "x/name. "])
def test_archive_paths_reject_windows_ambiguous_names(name: str) -> None:
    with pytest.raises(prep.ProxyToolsWheelPreparationError):
        prep._safe_archive_parts(name)


def test_two_fresh_mocked_builds_publish_only_identical_validated_wheel(
        tmp_path: Path, synthetic_inputs: dict[str, object], monkeypatch: pytest.MonkeyPatch) -> None:
    wheel = _wheel(synthetic_inputs["module"])
    calls: list[tuple[str, ...]] = []

    def fake_run(argv: tuple[str, ...], **kwargs: object) -> SimpleNamespace:
        calls.append(argv)
        assert kwargs["maximum_active_processes"] == 1
        assert kwargs["env"] is not None
        if argv[3] == prep._PYTHON_VERSION_PROGRAM:
            assert kwargs["stdout_limit"] == 128
            return SimpleNamespace(returncode=0, stdout=b"3.13.1\n")
        assert kwargs["stdout_limit"] == 16 * 1024
        Path(argv[-1], "proxy_tools-0.1.0-py3-none-any.whl").write_bytes(wheel)
        return SimpleNamespace(returncode=0, stdout=b"")

    monkeypatch.setattr(prep, "run_owned_process", fake_run)
    python = synthetic_inputs["python"]
    result = prep.prepare_proxy_tools_wheel(
        source_archive=synthetic_inputs["source"], python_executable=python,
        python_sha256=_sha256(Path(python).read_bytes()), python_size_bytes=Path(python).stat().st_size,
        python_version="3.13.1",
        setuptools_wheel=synthetic_inputs["setuptools"], destination=tmp_path / "published")
    assert len(calls) == 3
    assert (tmp_path / "published" / result.filename).read_bytes() == wheel
    assert result.network_isolation_not_proven is True
    assert result.license_discrepancy_review_required is True
    assert not list(tmp_path.glob(".proxy-tools-build-*"))


def test_non_deterministic_second_build_is_rejected_without_publication(
        tmp_path: Path, synthetic_inputs: dict[str, object], monkeypatch: pytest.MonkeyPatch) -> None:
    first = _wheel(synthetic_inputs["module"])
    second = first + b"different"
    count = 0

    def fake_run(argv: tuple[str, ...], **kwargs: object) -> SimpleNamespace:
        nonlocal count
        if argv[3] == prep._PYTHON_VERSION_PROGRAM:
            return SimpleNamespace(returncode=0, stdout=b"3.13.1\n")
        count += 1
        Path(argv[-1], "proxy_tools-0.1.0-py3-none-any.whl").write_bytes(first if count == 1 else second)
        return SimpleNamespace(returncode=0, stdout=b"")

    monkeypatch.setattr(prep, "run_owned_process", fake_run)
    python = synthetic_inputs["python"]
    with pytest.raises(prep.ProxyToolsWheelPreparationError, match="not deterministic"):
        prep.prepare_proxy_tools_wheel(
            source_archive=synthetic_inputs["source"], python_executable=python,
            python_sha256=_sha256(Path(python).read_bytes()), python_size_bytes=Path(python).stat().st_size,
            python_version="3.13.1",
            setuptools_wheel=synthetic_inputs["setuptools"], destination=tmp_path / "published")
    assert not (tmp_path / "published").exists()


def test_wheel_validation_rejects_unlisted_member(synthetic_inputs: dict[str, object]) -> None:
    with pytest.raises(prep.ProxyToolsWheelPreparationError):
        prep._validate_built_wheel(_wheel(synthetic_inputs["module"], extra_file=True),
                                   "proxy_tools-0.1.0-py3-none-any.whl", "0" * 64, 1, "3.13.1")
