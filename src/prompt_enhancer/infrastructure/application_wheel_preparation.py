"""Offline reproducible application wheel preparation from reviewed local inputs."""
from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import stat
import tempfile
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath

from packaging.utils import canonicalize_name, parse_wheel_filename
from ..application.owned_process import OwnedProcessRunError, run_owned_process

_MAX_FILE = 16 * 1024 * 1024
_MAX_WHEEL = 128 * 1024 * 1024
_MAX_MANIFEST = 2 * 1024 * 1024
_MAX_SOURCE_TOTAL = 128 * 1024 * 1024
_EPOCH = "1399328544"
_VERSION_PROGRAM = "import sys;print('.'.join(map(str,sys.version_info[:3])))"
_BUILD_PROGRAM = ("import contextlib,os,sys\n"
                  "site,root,dist=sys.argv[1:]\n"
                  "sys.path.insert(0,site)\n"
                  "os.chdir(root)\n"
                  "from setuptools.build_meta import build_wheel\n"
                  "with open(os.devnull,'w',encoding='utf-8') as routine_output,contextlib.redirect_stdout(routine_output):\n"
                  " filename=build_wheel(dist,{})\n"
                  "print(filename)")

class ApplicationWheelPreparationError(RuntimeError): pass

@dataclass(frozen=True, slots=True)
class ApplicationWheelPreparation:
    filename: str
    sha256: str
    size_bytes: int
    source_manifest_sha256: str
    source_manifest_size_bytes: int
    dashboard_manifest_sha256: str
    dashboard_manifest_size_bytes: int
    python_sha256: str
    python_size_bytes: int
    python_version: str
    setuptools_sha256: str
    setuptools_size_bytes: int
    setuptools_version: str
    source_tree_dirty: bool
    runtime_closure_not_pinned: bool = True
    network_isolation_not_proven: bool = True
    source_date_epoch: str = _EPOCH

def _fail(message: str, cause: Exception | None = None) -> None:
    if cause is None: raise ApplicationWheelPreparationError(message)
    raise ApplicationWheelPreparationError(message) from cause
def _sha(data: bytes) -> str: return hashlib.sha256(data).hexdigest()
def _safe_relative(name: str, dashboard: bool) -> PurePosixPath:
    path = PurePosixPath(name); prefix = "src/prompt_enhancer/_resources/dashboard/"
    reserved={"con","prn","aux","nul",*(f"com{x}" for x in range(1,10)),*(f"lpt{x}" for x in range(1,10))}
    if (not isinstance(name,str) or not name or "\\" in name or path.is_absolute() or "__pycache__" in path.parts
        or any(x in {"",".",".."} or ":" in x or x!=x.rstrip(". ") or x.rstrip(". ").split(".",1)[0].casefold() in reserved for x in name.split("/"))
        or (dashboard and not name.startswith(prefix))
        or (not dashboard and not (name in {"pyproject.toml","README.md"} or name.startswith("src/prompt_enhancer/")))):
        _fail("application wheel manifest is invalid")
    return path
def _unique_object(pairs: list[tuple[object,object]]) -> dict[object,object]:
    value: dict[object,object]={}
    for key,item in pairs:
        if key in value: raise ValueError("duplicate JSON key")
        value[key]=item
    return value
def _manifest(path: Path, dashboard: bool) -> tuple[dict[str,tuple[int,str]],bytes]:
    try:
        raw=_read(path,maximum=_MAX_MANIFEST); value=json.loads(raw.decode("utf-8"),object_pairs_hook=_unique_object)
        if not raw or not isinstance(value,dict) or not value: raise ValueError()
    except (OSError,UnicodeDecodeError,ValueError,json.JSONDecodeError) as error: _fail("application wheel manifest is invalid",error)
    result={}
    for name,entry in value.items():
        _safe_relative(name,dashboard)
        if (not isinstance(entry,dict) or set(entry)!={"sha256","size_bytes"} or isinstance(entry["size_bytes"],bool)
            or not isinstance(entry["size_bytes"],int) or not 0<=entry["size_bytes"]<=_MAX_FILE
            or not isinstance(entry["sha256"],str) or len(entry["sha256"])!=64 or any(c not in "0123456789abcdef" for c in entry["sha256"])): _fail("application wheel manifest is invalid")
        result[name]=(entry["size_bytes"],entry["sha256"])
    return result,raw
def _normalized_manifest(value: dict[str,tuple[int,str]]) -> bytes:
    """Bind provenance to a canonical, content-free path/hash/size document."""
    return json.dumps({name:{"sha256":digest,"size_bytes":size} for name,(size,digest) in value.items()},sort_keys=True,separators=(",",":")).encode("utf-8")
def _regular(path:Path,maximum:int)->os.stat_result:
    try: info=path.lstat()
    except OSError as error: _fail("application wheel input unavailable",error)
    if (not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode) or getattr(info,"st_file_attributes",0)&0x400 or info.st_nlink!=1 or not 0<=info.st_size<=maximum): _fail("application wheel input unsafe")
    return info
def _same(a:os.stat_result,b:os.stat_result)->bool:
    return (a.st_dev,a.st_ino,a.st_mode,a.st_nlink,a.st_size,a.st_mtime_ns,a.st_ctime_ns,getattr(a,"st_file_attributes",0))==(b.st_dev,b.st_ino,b.st_mode,b.st_nlink,b.st_size,b.st_mtime_ns,b.st_ctime_ns,getattr(b,"st_file_attributes",0))
def _same_open_file(path_info: os.stat_result, descriptor_info: os.stat_result) -> bool:
    """Windows may report a different device id for ``fstat`` and ``lstat``."""
    if (path_info.st_nlink,path_info.st_size,path_info.st_mtime_ns,path_info.st_ctime_ns)!=(descriptor_info.st_nlink,descriptor_info.st_size,descriptor_info.st_mtime_ns,descriptor_info.st_ctime_ns): return False
    return not (path_info.st_ino and descriptor_info.st_ino) or path_info.st_ino==descriptor_info.st_ino
def _assert_link_free_ancestors(path: Path) -> None:
    """Audit every existing ancestor, not merely the terminal file."""
    try:
        current=path.parent
        while True:
            info=current.lstat()
            if stat.S_ISLNK(info.st_mode) or getattr(info,"st_file_attributes",0)&0x400: raise ValueError()
            parent=current.parent
            if parent==current: return
            current=parent
    except (OSError,ValueError) as error: _fail("application wheel input unsafe",error)
def _read(path:Path,*,size:int|None=None,sha256:str|None=None,maximum:int=_MAX_FILE)->bytes:
    _assert_link_free_ancestors(path);before=_regular(path,maximum)
    try:
        with path.open("rb") as handle:
            opened=os.fstat(handle.fileno())
            if not _same_open_file(before,opened): _fail("application wheel input does not match review")
            data=handle.read(maximum+1)
            if not _same_open_file(opened,os.fstat(handle.fileno())): _fail("application wheel input does not match review")
    except OSError as error: _fail("application wheel input unavailable",error)
    _assert_link_free_ancestors(path)
    if len(data)>maximum or not _same(before,_regular(path,maximum)) or len(data)!=before.st_size or (size is not None and len(data)!=size) or (sha256 is not None and _sha(data)!=sha256): _fail("application wheel input does not match review")
    return data
def _archive_path(name:str)->PurePosixPath:
    path=PurePosixPath(name)
    reserved={"con","prn","aux","nul",*(f"com{x}" for x in range(1,10)),*(f"lpt{x}" for x in range(1,10))}
    if not name or "\\" in name or path.is_absolute() or any(x in {"",".",".."} or ":" in x or x!=x.rstrip(". ") or x.rstrip(". ").split(".",1)[0].casefold() in reserved for x in name.split("/")): _fail("application wheel builder is invalid")
    return path
def _extract_setuptools(data:bytes,target:Path)->str:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            infos=archive.infolist()
            if not 1<=len(infos)<=8192 or "setuptools/__init__.py" not in archive.namelist(): raise ValueError()
            for info in infos:
                relative=_archive_path(info.filename)
                if info.is_dir() or stat.S_ISLNK(info.external_attr>>16) or info.file_size>_MAX_FILE: raise ValueError()
                out=target.joinpath(*relative.parts); out.parent.mkdir(parents=True,exist_ok=True)
                with archive.open(info) as source,out.open("xb") as destination: shutil.copyfileobj(source,destination,64*1024)
        return "unknown" # filename validation is performed by caller
    except (OSError,ValueError,zipfile.BadZipFile) as error: _fail("application wheel builder is invalid",error)
def _environment(root:Path)->dict[str,str]:
    return {"PATH":"","PYTHONNOUSERSITE":"1","PYTHONDONTWRITEBYTECODE":"1","SOURCE_DATE_EPOCH":_EPOCH,"SYSTEMROOT":os.environ.get("SYSTEMROOT",os.environ.get("SystemRoot","")),"TEMP":str(root),"TMP":str(root)}
def _verify_python(executable:Path,digest:str,size:int,version:str,root:Path)->None:
    _read(executable,size=size,sha256=digest,maximum=512*1024*1024); before=_regular(executable,512*1024*1024)
    try: result=run_owned_process((str(executable),"-I","-c",_VERSION_PROGRAM),cwd=root,env=_environment(root),stdout_limit=128,stderr_limit=1024,timeout=20,maximum_active_processes=1)
    except OwnedProcessRunError as error:
        _fail("application wheel cleanup unconfirmed" if error.code=="owned_process_cleanup_unconfirmed" else "application wheel builder version is invalid",error)
    if not _same(before,_regular(executable,512*1024*1024)) or result.returncode or result.stdout.strip()!=version.encode("ascii"): _fail("application wheel builder version is invalid")
def _write_tree(files:dict[str,bytes],root:Path)->None:
    for name,data in files.items():
        target=root.joinpath(*PurePosixPath(name).parts);target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(data)
def _wheel(dist:Path,expected:dict[str,bytes])->tuple[str,bytes]:
    outputs=list(dist.iterdir())
    if len(outputs)!=1 or not outputs[0].is_file() or outputs[0].suffix!=".whl": _fail("application wheel build output is invalid")
    data=_read(outputs[0],maximum=_MAX_WHEEL)
    try:
        distribution,version,_,_=parse_wheel_filename(outputs[0].name)
        if canonicalize_name(distribution)!="prompt-enhancer": raise ValueError()
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            names=archive.namelist()
            if len(names)!=len(set(names)) or len(names)>20000: raise ValueError()
            for name in names:_archive_path(name)
            payload={name.removeprefix("src/") for name in expected if name.startswith("src/")}
            dist_info=f"prompt_enhancer-{version}.dist-info/"
            required=payload|{dist_info+name for name in ("METADATA","WHEEL","RECORD","top_level.txt")}
            allowed=required|{dist_info+"entry_points.txt"}
            if not required.issubset(names) or not set(names).issubset(allowed): raise ValueError()
            for name,content in expected.items():
                if name.startswith("src/") and (name.removeprefix("src/") not in names or archive.read(name.removeprefix("src/"))!=content): raise ValueError()
    except (KeyError,ValueError,zipfile.BadZipFile) as error:_fail("application wheel output is invalid",error)
    return outputs[0].name,data

def review_application_wheel_inputs(*,source_manifest:Path,dashboard_manifest:Path,source_tree_dirty:bool)->ApplicationWheelPreparation:
    if not isinstance(source_tree_dirty,bool): _fail("application wheel source tree state is invalid")
    source,_=_manifest(source_manifest,False); dashboard,_=_manifest(dashboard_manifest,True); source_raw=_normalized_manifest(source);dashboard_raw=_normalized_manifest(dashboard)
    return ApplicationWheelPreparation("","",0,_sha(source_raw),len(source_raw),_sha(dashboard_raw),len(dashboard_raw),"",0,"","",0,"",bool(source_tree_dirty))

def _read_project_file(root: Path, name: str, size: int, digest: str) -> bytes:
    """Reject both final-file and intermediate reparse points beneath the reviewed root."""
    try: physical_root=root.resolve(strict=True)
    except OSError as error: _fail("application wheel source unavailable",error)
    current=root
    for part in PurePosixPath(name).parts:
        current=current / part
        try: info=current.lstat()
        except OSError as error: _fail("application wheel input unavailable",error)
        if stat.S_ISLNK(info.st_mode) or getattr(info,"st_file_attributes",0)&0x400: _fail("application wheel input unsafe")
    try: current.resolve(strict=True).relative_to(physical_root)
    except (OSError,ValueError) as error: _fail("application wheel input unsafe",error)
    return _read(current,size=size,sha256=digest)
def _remove_owned(directory: Path, parent: Path) -> None:
    try:
        if directory.parent.resolve(strict=True)!=parent.resolve(strict=True): raise ValueError()
        stack=[directory]
        while stack:
            current=stack.pop(); info=current.lstat()
            if stat.S_ISLNK(info.st_mode) or getattr(info,"st_file_attributes",0)&0x400 or not stat.S_ISDIR(info.st_mode): raise ValueError()
            with os.scandir(current) as entries:
                for entry in entries:
                    child=entry.stat(follow_symlinks=False)
                    if stat.S_ISLNK(child.st_mode) or getattr(child,"st_file_attributes",0)&0x400: raise ValueError()
                    if stat.S_ISDIR(child.st_mode): stack.append(Path(entry.path))
                    elif not stat.S_ISREG(child.st_mode): raise ValueError()
        shutil.rmtree(directory)
        if directory.exists(): raise ValueError()
    except (OSError,ValueError) as error: _fail("application wheel cleanup unconfirmed",error)

def prepare_application_wheel(*,project_root:Path,source_manifest:Path,dashboard_manifest:Path,source_tree_dirty:bool,python_executable:Path,python_sha256:str,python_size_bytes:int,python_version:str,setuptools_wheel:Path,setuptools_sha256:str,setuptools_size_bytes:int,setuptools_version:str,destination:Path,prepared_dashboard_root:Path|None=None)->ApplicationWheelPreparation:
    source,source_raw=_manifest(source_manifest,False); dashboard,dashboard_raw=_manifest(dashboard_manifest,True)
    source_raw=_normalized_manifest(source);dashboard_raw=_normalized_manifest(dashboard)
    if set(source)&set(dashboard) or "pyproject.toml" not in source: _fail("application wheel source manifest is incomplete")
    if not isinstance(source_tree_dirty,bool): _fail("application wheel source tree state is invalid")
    if sum(size for size,_ in {**source,**dashboard}.values())>_MAX_SOURCE_TOTAL: _fail("application wheel source manifest is too large")
    files={name:_read_project_file(Path(project_root),name,size,digest) for name,(size,digest) in source.items()}
    dashboard_root=Path(project_root) if prepared_dashboard_root is None else Path(prepared_dashboard_root)
    for name,(size,digest) in dashboard.items():
        target=(dashboard_root.joinpath(*PurePosixPath(name.removeprefix('src/prompt_enhancer/_resources/dashboard/')).parts) if prepared_dashboard_root is not None else dashboard_root.joinpath(*PurePosixPath(name).parts))
        files[name]=_read(target,size=size,sha256=digest)
    identity=(python_sha256, setuptools_sha256)
    if (isinstance(python_size_bytes,bool) or isinstance(setuptools_size_bytes,bool) or not isinstance(python_size_bytes,int) or not isinstance(setuptools_size_bytes,int) or python_size_bytes<=0 or setuptools_size_bytes<=0 or any(not isinstance(value,str) or len(value)!=64 or any(c not in "0123456789abcdef" for c in value) for value in identity) or not isinstance(setuptools_version,str)): _fail("application wheel builder identity is invalid")
    setuptools=_read(Path(setuptools_wheel),size=setuptools_size_bytes,sha256=setuptools_sha256,maximum=_MAX_WHEEL)
    try:
        distribution,builder_version,_,tags=parse_wheel_filename(Path(setuptools_wheel).name)
        if canonicalize_name(distribution)!="setuptools" or str(setuptools_version)!=str(builder_version) or {str(tag) for tag in tags}!={"py3-none-any"}: raise ValueError()
    except ValueError as error:_fail("application wheel builder is invalid",error)
    output=Path(destination).absolute()
    if output.exists() or output.is_symlink() or ".." in output.parts or not output.name:_fail("application wheel destination is unavailable")
    output.parent.mkdir(parents=True,exist_ok=True);_verify_python(Path(python_executable),python_sha256,python_size_bytes,python_version,output.parent)
    works=[];unconfirmed_works=set()
    try:
        builds=[]
        for _ in range(2):
            work=Path(tempfile.mkdtemp(prefix=".application-wheel-build-",dir=output.parent));works.append(work); staged,site,dist=work/"source",work/"site",work/"dist";staged.mkdir();site.mkdir();dist.mkdir();_write_tree(files,staged);_extract_setuptools(setuptools,site)
            try: result=run_owned_process((str(python_executable),"-I","-c",_BUILD_PROGRAM,str(site),str(staged),str(dist)),cwd=staged,env=_environment(work),stdout_limit=16384,stderr_limit=16384,timeout=120,maximum_active_processes=1)
            except OwnedProcessRunError as error:
                if error.code=="owned_process_cleanup_unconfirmed":
                    unconfirmed_works.add(work)
                    _fail("application wheel cleanup unconfirmed",error)
                _fail(f"application wheel build failed: {error.code}",error)
            _read(Path(python_executable),size=python_size_bytes,sha256=python_sha256,maximum=512*1024*1024)
            if result.returncode:_fail("application wheel build command failed")
            builds.append(_wheel(dist,files))
        if builds[0]!=builds[1]:_fail("application wheel build is not deterministic")
        filename,wheel=builds[0]; publication=Path(tempfile.mkdtemp(prefix=".application-wheel-publish-",dir=output.parent))
        try:
            (publication/filename).write_bytes(wheel)
            result=ApplicationWheelPreparation(filename,_sha(wheel),len(wheel),_sha(source_raw),len(source_raw),_sha(dashboard_raw),len(dashboard_raw),python_sha256,python_size_bytes,python_version,setuptools_sha256,setuptools_size_bytes,str(setuptools_version),source_tree_dirty)
            (publication/"provenance.json").write_text(json.dumps(asdict(result),sort_keys=True,separators=(",",":")),encoding="utf-8")
            if output.exists(): _fail("application wheel destination is unavailable")
            os.rename(publication,output)
        except OSError as error:_fail("application wheel destination is unavailable",error)
        finally:
            if publication.exists(): _remove_owned(publication,output.parent)
        return result
    finally:
        cleanup_error=None
        for work in works:
            if work in unconfirmed_works:continue
            try: _remove_owned(work,output.parent)
            except ApplicationWheelPreparationError as error: cleanup_error=error
        if cleanup_error is not None: raise cleanup_error

__all__=("ApplicationWheelPreparation","ApplicationWheelPreparationError","prepare_application_wheel","review_application_wheel_inputs")
