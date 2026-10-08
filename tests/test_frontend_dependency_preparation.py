import base64
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from prompt_enhancer.infrastructure import frontend_dependency_preparation as p
from prompt_enhancer.infrastructure.frontend_dashboard_preparation import _REQUIRED_SOURCE


def raw(value):
    return json.dumps(value).encode()


def lock():
    root = {"name": "example-dashboard", "version": "1.0.0", "devDependencies": {"vite": "1.0.0", "typescript": "1.0.0"}}
    packages = {"": root}
    for name in ("vite", "typescript", "example-optional"):
        packages["node_modules/" + name] = {"version": "1.0.0", "resolved": "https://registry.npmjs.org/" + name + "/-/" + name + "-1.0.0.tgz",
            "integrity": "sha512-" + base64.b64encode(bytes(64)).decode(), "optional": name == "example-optional"}
    return root, {"lockfileVersion": 3, "packages": packages}


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path / "unused-home"))
    source, npm = tmp_path / "source", tmp_path / "npm"
    source.mkdir(); (npm / "bin").mkdir(parents=True)
    package, locked = lock()
    for name in _REQUIRED_SOURCE:
        target = source / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"{}")
    (source / "package.json").write_bytes(raw(package))
    (source / "package-lock.json").write_bytes(raw(locked))
    (npm / "package.json").write_bytes(raw({"name": "npm", "version": "11.6.2"}))
    (npm / "bin/npm-cli.js").write_bytes(b"// synthetic fixture only\n")
    (tmp_path / "node-input").mkdir()
    node = tmp_path / "node-input/node.exe"; node.write_bytes(b"synthetic node")
    sm, nm = tmp_path / "source.json", tmp_path / "npm.json"
    sm.write_bytes(p._normalized_manifest(p.inventory(source)))
    nm.write_bytes(p._normalized_manifest(p.inventory(npm)))
    args = dict(frontend_root=source, source_manifest=sm, source_manifest_size=sm.stat().st_size,
        source_manifest_sha256=p.digest(sm.read_bytes()), node_executable=node, node_size=node.stat().st_size,
        node_sha256=p.digest(node.read_bytes()), node_version="v22.0.0", npm_root=npm, npm_manifest=nm,
        npm_manifest_size=nm.stat().st_size, npm_manifest_sha256=p.digest(nm.read_bytes()), npm_version="11.6.2", destination=tmp_path / "result")
    calls = []
    def run(argv, **kw):
        calls.append((argv, kw))
        if "--version" in argv:
            return SimpleNamespace(returncode=0, stdout=b"v22.0.0\n", stderr=b"")
        for name, script in (("vite", "vite.js"), ("typescript", "tsc")):
            directory = kw["cwd"] / "node_modules" / name
            (directory / "bin").mkdir(parents=True)
            (directory / "package.json").write_bytes(raw({"name": name, "version": "1.0.0"}))
            (directory / "bin" / script).write_bytes(b"// synthetic only")
        return SimpleNamespace(returncode=0, stdout=b"", stderr=b"")
    monkeypatch.setattr(p, "run_owned_process", run)
    return args, calls, run


def test_success_closed_provenance_and_exact_safety_flags(setup, monkeypatch):
    args, calls, _ = setup
    monkeypatch.setenv("NPM_TOKEN", "synthetic-not-forwarded")
    monkeypatch.setenv("HTTP_PROXY", "http://example.invalid")
    (args["frontend_root"] / ".npmrc").write_text("synthetic ignored config")
    receipt = p.prepare_frontend_dependencies(**args)
    assert len(calls) == 2 and receipt["missing_optional_packages"] == 1
    argv, kw = calls[1]
    assert argv[:3] == [str(args["node_executable"]), str(args["npm_root"] / "bin/npm-cli.js"), "ci"]
    assert {"--ignore-scripts", "--no-audit", "--no-fund", "--bin-links=false", "--install-strategy=hoisted", "--include=optional"} <= set(argv)
    assert (kw["timeout"], kw["maximum_active_processes"], kw["stdout_limit"], kw["stderr_limit"]) == (180, 1, 32768, 32768)
    assert "NPM_TOKEN" not in kw["env"] and "HTTP_PROXY" not in kw["env"] and kw["env"]["PATH"] == ""
    assert not (args["destination"] / "private").exists()
    assert not (args["destination"] / "frontend/.npmrc").exists()
    assert not receipt["release_accepted"] and not receipt["independent_tarball_byte_proof"]
    assert str(args["destination"]) not in json.dumps(receipt)


@pytest.mark.parametrize("kind", ["source", "node", "npm", "manifest"])
def test_tampering_after_process_fails_without_publish(setup, monkeypatch, kind):
    args, _, run = setup
    def mutate(argv, **kw):
        result = run(argv, **kw)
        if "ci" in argv:
            target = {"source": args["frontend_root"] / "index.html", "node": args["node_executable"],
                      "npm": args["npm_root"] / "bin/npm-cli.js", "manifest": args["npm_manifest"]}[kind]
            target.write_bytes(b"changed synthetic fixture")
        return result
    monkeypatch.setattr(p, "run_owned_process", mutate)
    with pytest.raises(p.FrontendDependencyPreparationError):
        p.prepare_frontend_dependencies(**args)
    assert not args["destination"].exists()


@pytest.mark.parametrize("failure", ["nonzero", "owned_process_timeout", "owned_process_stdout_limit", "owned_process_cleanup_unconfirmed"])
def test_process_failure_never_publishes(setup, monkeypatch, failure):
    args, _, run = setup
    def fail(argv, **kw):
        if "ci" not in argv: return run(argv, **kw)
        (kw["cwd"] / "partial.txt").write_text("synthetic")
        if failure == "nonzero": return SimpleNamespace(returncode=1, stdout=b"private-like text must not escape", stderr=b"")
        raise p.OwnedProcessRunError(failure)
    monkeypatch.setattr(p, "run_owned_process", fail)
    with pytest.raises(p.FrontendDependencyPreparationError) as caught:
        p.prepare_frontend_dependencies(**args)
    assert "private-like" not in str(caught.value) and not args["destination"].exists()


def test_required_missing_and_private_cleanup_failure(setup, monkeypatch):
    args, _, _ = setup
    monkeypatch.setattr(p, "run_owned_process", lambda *a, **k: SimpleNamespace(returncode=0, stdout=b"v22.0.0\n", stderr=b""))
    with pytest.raises(p.FrontendDependencyPreparationError, match="required_missing"):
        p.prepare_frontend_dependencies(**args)
    monkeypatch.setattr(p, "_remove_owned", lambda *a: (_ for _ in ()).throw(ValueError()))
    with pytest.raises(p.FrontendDependencyPreparationError, match="cleanup_unconfirmed"):
        p.prepare_frontend_dependencies(**args)


@pytest.mark.parametrize("kind", ["http", "foreign", "credentials", "traversal", "link", "sri", "root-mismatch"])
def test_lock_adversaries(kind):
    package, locked = lock(); item = locked["packages"]["node_modules/vite"]
    if kind == "http": item["resolved"] = "http://registry.npmjs.org/vite.tgz"
    if kind == "foreign": item["resolved"] = "https://example.invalid/vite.tgz"
    if kind == "credentials": item["resolved"] = "@".join(("https://example", "registry.npmjs.org/vite.tgz"))
    if kind == "traversal": item["resolved"] = "https://registry.npmjs.org/../vite.tgz"
    if kind == "link": item["link"] = True
    if kind == "sri": item["integrity"] = "sha512-invalid"
    if kind == "root-mismatch": package = dict(package, version="2.0.0")
    with pytest.raises((p.FrontendDependencyPreparationError, ValueError)):
        p.registry_lock(raw(package), raw(locked))


@pytest.mark.parametrize("path", [r"\\example.invalid\share", r"C:relative", r"C:\safe\file:stream", r"C:\safe\..\escape"])
def test_unsafe_lexical_paths_refused_before_filesystem(monkeypatch, path):
    monkeypatch.setattr(p, "_assert_link_free_ancestors", lambda *a: pytest.fail("filesystem touched"))
    with pytest.raises(p.FrontendDependencyPreparationError): p.absolute(path)


def test_existing_destination_and_npm_extra_refuse_before_process(setup, monkeypatch):
    args, _, _ = setup
    monkeypatch.setattr(p, "run_owned_process", lambda *a, **k: pytest.fail("launched"))
    (args["npm_root"] / "extra.txt").write_text("synthetic")
    with pytest.raises(p.FrontendDependencyPreparationError): p.prepare_frontend_dependencies(**args)
    args["destination"].mkdir()
    with pytest.raises(p.FrontendDependencyPreparationError): p.prepare_frontend_dependencies(**args)


@pytest.mark.parametrize("target", ["npm", "config", "source", "node"])
def test_version_probe_tamper_refuses_before_install(setup, monkeypatch, target):
    args, calls, run = setup
    def mutate(argv, **kw):
        assert "ci" not in argv
        result = run(argv, **kw)
        path = {"npm": args["npm_root"] / "bin/npm-cli.js", "config": Path(kw["env"]["NPM_CONFIG_USERCONFIG"]),
                "source": kw["cwd"] / "index.html", "node": args["node_executable"]}[target]
        path.write_bytes(b"synthetic change")
        return result
    monkeypatch.setattr(p, "run_owned_process", mutate)
    with pytest.raises(p.FrontendDependencyPreparationError): p.prepare_frontend_dependencies(**args)
    assert len(calls) == 1 and not args["destination"].exists()


def test_unexpected_installed_root_file_refused(setup, monkeypatch):
    args, _, run = setup
    def mutate(argv, **kw):
        result = run(argv, **kw)
        if "ci" in argv: (kw["cwd"] / ".npmrc").write_text("synthetic unexpected")
        return result
    monkeypatch.setattr(p, "run_owned_process", mutate)
    with pytest.raises(p.FrontendDependencyPreparationError, match="source_output_changed"):
        p.prepare_frontend_dependencies(**args)


def test_unconfirmed_process_cleanup_preserves_unpublished_stage(setup, monkeypatch):
    args, _, _ = setup
    monkeypatch.setattr(p, "run_owned_process", lambda *a, **k: (_ for _ in ()).throw(p.OwnedProcessRunError("owned_process_cleanup_unconfirmed")))
    monkeypatch.setattr(p, "_remove_owned", lambda *a: pytest.fail("must not remove possible live workspace"))
    with pytest.raises(p.FrontendDependencyPreparationError, match="owned_process_cleanup_unconfirmed"):
        p.prepare_frontend_dependencies(**args)
    assert not args["destination"].exists()
    assert len(list(args["destination"].parent.glob(".frontend-dependencies-*"))) == 1


@pytest.mark.parametrize("spec", ["file:../other", "git+https://example.invalid/repo", "https://registry.npmjs.org/a.tgz", "workspace:*", "@".join(("npm:other", "1.0.0"))])
def test_nested_nonregistry_specs_refused(spec):
    package, locked = lock()
    locked["packages"]["node_modules/vite"]["optionalDependencies"] = {"example-dependency": spec}
    with pytest.raises(p.FrontendDependencyPreparationError): p.registry_lock(raw(package), raw(locked))


def test_overrides_refused():
    package, locked = lock()
    package["overrides"] = {"vite": "1.0.0"}
    with pytest.raises(p.FrontendDependencyPreparationError): p.registry_lock(raw(package), raw(locked))


def test_package_only_git_peer_refused():
    package, locked = lock()
    package = dict(package, peerDependencies={"example-peer": "git+https://example.invalid/repo"})
    with pytest.raises(p.FrontendDependencyPreparationError): p.registry_lock(raw(package), raw(locked))


@pytest.mark.parametrize("kind", ["extra", "manifest"])
def test_late_publication_tamper_refused(setup, monkeypatch, kind):
    args, _, _ = setup
    original = p._remove_owned
    def cleanup(directory, parent):
        original(directory, parent)
        if directory.name == "private":
            (parent / ("unexpected.txt" if kind == "extra" else "provenance.json")).write_bytes(b"synthetic tamper")
    monkeypatch.setattr(p, "_remove_owned", cleanup)
    with pytest.raises(p.FrontendDependencyPreparationError): p.prepare_frontend_dependencies(**args)
    assert not args["destination"].exists()
