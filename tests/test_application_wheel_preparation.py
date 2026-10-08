import hashlib,json,os,sys,zipfile
from pathlib import Path
import pytest
from prompt_enhancer.application.owned_process import run_owned_process
from prompt_enhancer.infrastructure.application_wheel_preparation import ApplicationWheelPreparationError,_BUILD_PROGRAM,_environment,prepare_application_wheel,review_application_wheel_inputs

_REVIEWED_SETUPTOOLS_SHA256="51a52592b3b99e102b609654876bd65f19f999935166d1352678931132b0c670"

def _hash(value):return hashlib.sha256(value).hexdigest()
def _manifest(root,names):return {name:{"size_bytes":len((root/name).read_bytes()),"sha256":_hash((root/name).read_bytes())} for name in names}
def _inputs(tmp_path):
    root=tmp_path/"synthetic-project";(root/"src/prompt_enhancer/_resources/dashboard/.vite").mkdir(parents=True)
    (root/"pyproject.toml").write_text("[build-system]\nrequires=['setuptools']\nbuild-backend='setuptools.build_meta'\n[project]\nname='prompt-enhancer'\nversion='0.1.0'\n[tool.setuptools]\ninclude-package-data=true\n[tool.setuptools.package-data]\nprompt_enhancer=['_resources/dashboard/*','_resources/dashboard/.vite/manifest.json']\n")
    (root/"src/prompt_enhancer/__init__.py").write_text("VALUE='synthetic'\n");(root/"src/prompt_enhancer/_resources/__init__.py").write_text("");(root/"src/prompt_enhancer/_resources/dashboard/index.html").write_text("<p>synthetic dashboard</p>");(root/"src/prompt_enhancer/_resources/dashboard/.vite/manifest.json").write_text('{"index.html":{}}')
    source=tmp_path/"source.json";dashboard=tmp_path/"dashboard.json";source.write_text(json.dumps(_manifest(root,["pyproject.toml","src/prompt_enhancer/__init__.py","src/prompt_enhancer/_resources/__init__.py"])));dashboard.write_text(json.dumps(_manifest(root,["src/prompt_enhancer/_resources/dashboard/index.html","src/prompt_enhancer/_resources/dashboard/.vite/manifest.json"])))
    fake=tmp_path/"unreviewed-setuptools.whl";fake.write_bytes(b"synthetic")
    return root,source,dashboard,fake,Path(sys.executable)
def _reviewed_setuptools() -> Path:
    value=os.environ.get("PROMPT_ENHANCER_REVIEWED_SETUPTOOLS_WHEEL")
    if not value: pytest.skip("set PROMPT_ENHANCER_REVIEWED_SETUPTOOLS_WHEEL for the reviewed-tool integration build")
    path=Path(value)
    if _hash(path.read_bytes())!=_REVIEWED_SETUPTOOLS_SHA256: pytest.fail("reviewed setuptools integration input has the wrong digest")
    return path
def _reviewed_python() -> Path:
    value=os.environ.get("PROMPT_ENHANCER_REVIEWED_PYTHON_EXECUTABLE")
    if not value: pytest.skip("set PROMPT_ENHANCER_REVIEWED_PYTHON_EXECUTABLE to a reviewed base interpreter for the integration build")
    path=Path(value)
    if not path.is_file(): pytest.fail("reviewed Python integration input is unavailable")
    return path
def _build(tmp_path,destination):
    root,source,dashboard,_fake,_runner_python=_inputs(tmp_path);wheel=_reviewed_setuptools();python=_reviewed_python()
    return prepare_application_wheel(project_root=root,source_manifest=source,dashboard_manifest=dashboard,source_tree_dirty=True,python_executable=python,python_sha256=_hash(python.read_bytes()),python_size_bytes=python.stat().st_size,python_version=".".join(map(str,sys.version_info[:3])),setuptools_wheel=wheel,setuptools_sha256=_hash(wheel.read_bytes()),setuptools_size_bytes=wheel.stat().st_size,setuptools_version="84.0.0",destination=destination)
def test_builds_actual_wheel_twice_and_records_uncertainty(tmp_path):
    first=_build(tmp_path/"one",tmp_path/"out-one");second=_build(tmp_path/"two",tmp_path/"out-two")
    assert first.sha256==second.sha256 and first.source_tree_dirty and first.runtime_closure_not_pinned
    assert (tmp_path/"out-one"/"provenance.json").exists()
    with zipfile.ZipFile(tmp_path/"out-one"/first.filename) as wheel:
        assert wheel.read("prompt_enhancer/_resources/dashboard/index.html")==b"<p>synthetic dashboard</p>"
        assert wheel.read("prompt_enhancer/_resources/dashboard/.vite/manifest.json")==b'{"index.html":{}}'
def test_missing_manifest_member_does_not_publish(tmp_path):
    root,source,dashboard,wheel,python=_inputs(tmp_path);data=json.loads(source.read_text());data["src/prompt_enhancer/missing.py"]={"size_bytes":1,"sha256":"0"*64};source.write_text(json.dumps(data))
    with pytest.raises(ApplicationWheelPreparationError):prepare_application_wheel(project_root=root,source_manifest=source,dashboard_manifest=dashboard,source_tree_dirty=False,python_executable=python,python_sha256=_hash(python.read_bytes()),python_size_bytes=python.stat().st_size,python_version=".".join(map(str,sys.version_info[:3])),setuptools_wheel=wheel,setuptools_sha256=_hash(wheel.read_bytes()),setuptools_size_bytes=wheel.stat().st_size,setuptools_version="84.0.0",destination=tmp_path/"never")
    assert not (tmp_path/"never").exists()
def test_changed_manifest_member_is_rejected_before_build(tmp_path):
    root,source,dashboard,wheel,python=_inputs(tmp_path);(root/"src/prompt_enhancer/_resources/dashboard/index.html").write_text("changed")
    with pytest.raises(ApplicationWheelPreparationError):prepare_application_wheel(project_root=root,source_manifest=source,dashboard_manifest=dashboard,source_tree_dirty=False,python_executable=python,python_sha256=_hash(python.read_bytes()),python_size_bytes=python.stat().st_size,python_version=".".join(map(str,sys.version_info[:3])),setuptools_wheel=wheel,setuptools_sha256=_hash(wheel.read_bytes()),setuptools_size_bytes=wheel.stat().st_size,setuptools_version="84.0.0",destination=tmp_path/"never")
    assert not (tmp_path/"never").exists()
def test_unreviewed_setuptools_is_rejected_before_extraction(tmp_path):
    root,source,dashboard,wheel,python=_inputs(tmp_path)
    with pytest.raises(ApplicationWheelPreparationError):prepare_application_wheel(project_root=root,source_manifest=source,dashboard_manifest=dashboard,source_tree_dirty=False,python_executable=python,python_sha256=_hash(python.read_bytes()),python_size_bytes=python.stat().st_size,python_version=".".join(map(str,sys.version_info[:3])),setuptools_wheel=wheel,setuptools_sha256="0"*64,setuptools_size_bytes=wheel.stat().st_size,setuptools_version="84.0.0",destination=tmp_path/"never")
    assert not (tmp_path/"never").exists()

@pytest.mark.parametrize('failure_build',[1,2])
@pytest.mark.parametrize('code',['owned_process_timeout','owned_process_cleanup_unconfirmed'])
def test_cleanup_preserves_only_unconfirmed_build(monkeypatch,tmp_path,failure_build,code):
    from types import SimpleNamespace
    from prompt_enhancer.infrastructure import application_wheel_preparation as prep
    root,source,dashboard,_fake,python=_inputs(tmp_path)
    wheel=tmp_path/'setuptools-84.0.0-py3-none-any.whl';wheel.write_bytes(b'synthetic')
    monkeypatch.setattr(prep,'_verify_python',lambda *args:None)
    monkeypatch.setattr(prep,'_extract_setuptools',lambda *args:None)
    monkeypatch.setattr(prep,'_wheel',lambda *args:('prompt_enhancer-0.1.0-py3-none-any.whl',b'synthetic wheel'))
    calls=[]
    def run(*args,**kwargs):
        calls.append(kwargs['cwd'].parent)
        if len(calls)==failure_build:raise prep.OwnedProcessRunError(code)
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(prep,'run_owned_process',run)
    with pytest.raises(ApplicationWheelPreparationError) as caught:
        prep.prepare_application_wheel(project_root=root,source_manifest=source,dashboard_manifest=dashboard,source_tree_dirty=True,
            python_executable=python,python_sha256=_hash(python.read_bytes()),python_size_bytes=python.stat().st_size,python_version='3.11.0',
            setuptools_wheel=wheel,setuptools_sha256=_hash(wheel.read_bytes()),setuptools_size_bytes=wheel.stat().st_size,setuptools_version='84.0.0',destination=tmp_path/'never')
    assert caught.value.__cause__.code==code and not (tmp_path/'never').exists()
    assert all(not path.exists() for path in calls[:-1])
    assert calls[-1].exists()==(code=='owned_process_cleanup_unconfirmed')

def test_version_probe_cleanup_uncertainty_is_closed(monkeypatch,tmp_path):
    from prompt_enhancer.infrastructure import application_wheel_preparation as prep
    executable=tmp_path/'python.exe';executable.write_bytes(b'synthetic')
    monkeypatch.setattr(prep,'run_owned_process',lambda *a,**k:(_ for _ in ()).throw(prep.OwnedProcessRunError('owned_process_cleanup_unconfirmed')))
    with pytest.raises(ApplicationWheelPreparationError,match='^application wheel cleanup unconfirmed$'):
        prep._verify_python(executable,_hash(executable.read_bytes()),executable.stat().st_size,'3.11.0',tmp_path)
    assert executable.exists()
def test_rejects_unsafe_manifest_path(tmp_path):
    source=tmp_path/"s";dashboard=tmp_path/"d";source.write_text(json.dumps({"../secret":{"size_bytes":1,"sha256":"a"*64}}));dashboard.write_text(json.dumps({"src/prompt_enhancer/_resources/dashboard/index.html":{"size_bytes":1,"sha256":"b"*64}}))
    with pytest.raises(ApplicationWheelPreparationError):review_application_wheel_inputs(source_manifest=source,dashboard_manifest=dashboard,source_tree_dirty=False)
def test_rejects_duplicate_or_windows_ambiguous_manifest_paths(tmp_path):
    source=tmp_path/"s";dashboard=tmp_path/"d";dashboard.write_text(json.dumps({"src/prompt_enhancer/_resources/dashboard/index.html":{"size_bytes":1,"sha256":"b"*64}}))
    source.write_text('{"pyproject.toml":{"sha256":"a"*64,"size_bytes":1},"pyproject.toml":{"sha256":"a"*64,"size_bytes":1}}'.replace('"a"*64','"'+'a'*64+'"'))
    with pytest.raises(ApplicationWheelPreparationError):review_application_wheel_inputs(source_manifest=source,dashboard_manifest=dashboard,source_tree_dirty=False)
    source.write_text(json.dumps({"src/prompt_enhancer/aux.py":{"size_bytes":1,"sha256":"a"*64}}))
    with pytest.raises(ApplicationWheelPreparationError):review_application_wheel_inputs(source_manifest=source,dashboard_manifest=dashboard,source_tree_dirty=False)

@pytest.mark.parametrize("failure",[False,True])
def test_build_program_silences_noisy_backend_but_preserves_failure(tmp_path,failure):
    site=tmp_path/'site/setuptools';site.mkdir(parents=True);(site/'__init__.py').write_text('')
    body="from pathlib import Path\nPath(dist, 'backend-ran').write_text('ran')\nprint('routine-copy-' * 5000)\n"
    body+="raise RuntimeError('synthetic failure')\n" if failure else "return 'synthetic.whl'\n"
    (site/'build_meta.py').write_text('def build_wheel(dist,config):\n '+body.replace('\n','\n ') )
    root=tmp_path/'root';root.mkdir();dist=tmp_path/'dist';dist.mkdir()
    base_python=Path(getattr(sys,'_base_executable',sys.executable))
    result=run_owned_process((str(base_python),'-c',_BUILD_PROGRAM,str(site.parent),str(root),str(dist)),cwd=root,env=_environment(tmp_path),stdout_limit=128,stderr_limit=4096,timeout=20,maximum_active_processes=1)
    assert (dist/'backend-ran').read_text()=='ran'
    if failure:
        assert result.returncode!=0
    else:
        assert result.returncode==0 and result.stdout.strip()==b'synthetic.whl'
