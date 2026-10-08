"""Prepare a reviewed, offline Vite dashboard for inclusion in an application wheel."""
from __future__ import annotations
import hashlib,json,os,re,stat,tempfile
from dataclasses import dataclass
from pathlib import Path,PurePosixPath
from typing import Any
from ..application.owned_process import OwnedProcessRunError,run_owned_process
from .application_wheel_preparation import ApplicationWheelPreparationError,_assert_link_free_ancestors,_normalized_manifest,_read,_remove_owned,_same,_same_open_file
from .frontend_module_inventory import FrontendModuleInventoryError,verify_frontend_module_inventory
from .frontend_package_bindings import FrontendPackageBindingError,collect_frontend_package_bindings

_MAX_FILE=16*1024*1024;_MAX_MANIFEST=2*1024*1024;_MAX_SOURCE_FILES=4096;_MAX_SOURCE_TOTAL=128*1024*1024;_MAX_OUTPUT_FILES=4096;_MAX_OUTPUT_TOTAL=128*1024*1024
_REQUIRED_SOURCE=frozenset({'index.html','package.json','package-lock.json','vite.config.ts','tsconfig.json','tsconfig.app.json','tsconfig.node.json','playwright.config.ts','src/build/viteModuleInputInventory.ts'})
_REQUIRED_TOOLS=frozenset({'node_modules/typescript/bin/tsc','node_modules/vite/bin/vite.js'})
_SOURCE_SUFFIXES=frozenset({'.ts','.tsx','.css','.json','.svg','.png','.jpg','.jpeg','.webp','.woff','.woff2'})
_BUILD_FAILURE_CODES=frozenset({'module_input_binding_invalid','module_input_code_oversize',
 'module_input_count_invalid','module_input_graph_oversize','module_input_identity_duplicate',
 'module_input_lock_invalid','module_input_output_invalid','module_input_output_oversize',
 'module_input_physical_binding_missing','module_input_logical_owner_mismatch','module_input_logical_binding_missing',
 'module_input_path_unsafe','module_input_query_unknown',
 'module_input_runtime_invalid','module_input_transform_conflict','module_input_virtual_unknown'})
class FrontendDashboardPreparationError(RuntimeError): pass
def _fail(message:str,cause:Exception|None=None)->None:
    if cause is None: raise FrontendDashboardPreparationError(message)
    raise FrontendDashboardPreparationError(message) from cause
def _sha(data:bytes)->str:return hashlib.sha256(data).hexdigest()

def _build_failure_code(stdout:bytes,stderr:bytes)->str|None:
    """Recognize only whole fixed plugin error lines, never captured messages.

    Vite's getErrorMessage emits ``Error: <message>``; plugin-labelled forms
    are accepted only for this exact owned plugin. Ambiguous codes stay generic.
    """
    codes=set()
    prefixes=('', 'Error: ', '[plugin prompt-enhancer:module-input-inventory] ',
              'Error: [plugin prompt-enhancer:module-input-inventory] ')
    for output in (stdout,stderr):
        if not isinstance(output,bytes) or len(output)>32768:return None
        try:text=output.decode('utf-8',errors='strict')
        except UnicodeError:return None
        for line in text.split('\n'):
            line=re.sub(r'\x1b\[[0-9;]{0,24}m','',line).strip(' \t\r')
            for code in _BUILD_FAILURE_CODES:
                if any(line==prefix+code for prefix in prefixes):codes.add(code)
    return next(iter(codes)) if len(codes)==1 else None
def _unique_object(pairs:list[tuple[object,object]])->dict[object,object]:
    result={}
    for key,value in pairs:
        if key in result:raise ValueError('duplicate JSON key')
        result[key]=value
    return result
def _safe_name(name:object)->PurePosixPath:
    if not isinstance(name,str) or not name:_fail('frontend dashboard manifest is invalid')
    path=PurePosixPath(name)
    if '\\' in name or path.is_absolute() or any(part in {'','.','..'} or ':' in part for part in name.split('/')):_fail('frontend dashboard manifest is invalid')
    return path
def _manifest(path:Path)->tuple[dict[str,tuple[int,str]],bytes]:
    try:
        raw=_read(path,maximum=_MAX_MANIFEST);value=json.loads(raw.decode('utf-8'),object_pairs_hook=_unique_object)
        if not isinstance(value,dict) or not value:raise ValueError()
    except (ApplicationWheelPreparationError,OSError,UnicodeDecodeError,ValueError,json.JSONDecodeError) as error:_fail('frontend dashboard manifest is invalid',error)
    result={}
    for name,entry in value.items():
        _safe_name(name)
        if (not isinstance(entry,dict) or set(entry)!={'sha256','size_bytes'} or isinstance(entry['size_bytes'],bool) or not isinstance(entry['size_bytes'],int) or not 0<=entry['size_bytes']<=_MAX_FILE or not isinstance(entry['sha256'],str) or len(entry['sha256'])!=64 or any(c not in '0123456789abcdef' for c in entry['sha256'])):_fail('frontend dashboard manifest is invalid')
        result[name]=(entry['size_bytes'],entry['sha256'])
    return result,raw
def _is_source_name(name:str)->bool:
    path=PurePosixPath(name)
    return name in _REQUIRED_SOURCE or (path.parts[:1]==('src',) and path.suffix.lower() in _SOURCE_SUFFIXES)
def _assert_source_inventory(root:Path,manifest:dict[str,tuple[int,str]])->None:
    if not _REQUIRED_SOURCE.issubset(manifest) or any(not _is_source_name(name) for name in manifest):_fail('frontend dashboard manifest is incomplete')
    actual=set();stack=[root];entries_seen=0
    while stack:
        current=stack.pop()
        try:
            info=current.lstat()
            if stat.S_ISLNK(info.st_mode) or getattr(info,'st_file_attributes',0)&0x400:raise ValueError()
            with os.scandir(current) as entries:
                for entry in entries:
                    entries_seen+=1
                    if entries_seen>_MAX_SOURCE_FILES*8:_fail('frontend dashboard source manifest is too large')
                    child=Path(entry.path);info=entry.stat(follow_symlinks=False)
                    if stat.S_ISLNK(info.st_mode) or getattr(info,'st_file_attributes',0)&0x400:raise ValueError()
                    relative=child.relative_to(root).as_posix()
                    if stat.S_ISDIR(info.st_mode):
                        if relative not in {'node_modules','dist','.git'}:stack.append(child)
                    elif stat.S_ISREG(info.st_mode) and _is_source_name(relative):actual.add(relative)
                    elif not stat.S_ISREG(info.st_mode):raise ValueError()
        except (OSError,ValueError) as error:_fail('frontend dashboard source unavailable',error)
        if len(actual)>_MAX_SOURCE_FILES:_fail('frontend dashboard source manifest is too large')
    if not any(name.startswith('src/') for name in actual):_fail('frontend dashboard manifest is incomplete')
    if actual!=set(manifest) or sum(size for size,_ in manifest.values())>_MAX_SOURCE_TOTAL:_fail('frontend dashboard manifest is incomplete')
def _read_root_file(root:Path,name:str,size:int,digest:str)->bytes:
    target=root.joinpath(*PurePosixPath(name).parts)
    try:target.resolve(strict=True).relative_to(root.resolve(strict=True))
    except (OSError,ValueError) as error:_fail('frontend dashboard source changed',error)
    try:return _read(target,size=size,sha256=digest)
    except ApplicationWheelPreparationError as error:_fail('frontend dashboard source changed',error)
def _verify_tree(root:Path,manifest:dict[str,tuple[int,str]])->None:
    for name,(size,digest) in manifest.items():_read_root_file(root,name,size,digest)
def _bind_tool(root:Path,name:str,size:int,digest:str)->Path:
    """Bind a package-manager logical path to its reviewed physical tool file.

    pnpm exposes packages through directory junctions on Windows.  They are not
    accepted for source or output trees, but a declared tooling entry can use
    one when its resolved regular file remains inside ``node_modules``.
    """
    logical=root.joinpath(*PurePosixPath(name).parts)
    try:
        tooling_root=(root/'node_modules').resolve(strict=True)
        canonical=logical.resolve(strict=True)
        canonical.relative_to(tooling_root)
    except (OSError,ValueError) as error:_fail('frontend dashboard tooling is unsafe',error)
    _read_physical_tool(canonical,size,digest)
    return canonical
def _read_physical_tool(path:Path,size:int,digest:str)->None:
    """Read a resolved tool safely while allowing package-manager hardlinked files."""
    try:
        _assert_link_free_ancestors(path);before=path.lstat()
        if not stat.S_ISREG(before.st_mode) or stat.S_ISLNK(before.st_mode) or getattr(before,'st_file_attributes',0)&0x400 or before.st_size>_MAX_FILE:raise ValueError()
        with path.open('rb') as handle:
            opened=os.fstat(handle.fileno())
            if not _same_open_file(before,opened):raise ValueError()
            data=handle.read(_MAX_FILE+1)
            if not _same_open_file(opened,os.fstat(handle.fileno())):raise ValueError()
        _assert_link_free_ancestors(path)
        if len(data)!=size or len(data)>_MAX_FILE or _sha(data)!=digest or not _same(before,path.lstat()):raise ValueError()
    except (ApplicationWheelPreparationError,OSError,ValueError) as error:_fail('frontend dashboard tooling changed',error)
def _verify_tools(root:Path,manifest:dict[str,tuple[int,str]],bindings:dict[str,Path])->None:
    for name,(size,digest) in manifest.items():
        try:
            tooling_root=(root/'node_modules').resolve(strict=True)
            canonical=root.joinpath(*PurePosixPath(name).parts).resolve(strict=True)
            canonical.relative_to(tooling_root)
        except (OSError,ValueError) as error:_fail('frontend dashboard tooling changed',error)
        if canonical!=bindings.get(name):_fail('frontend dashboard tooling changed')
        _read_physical_tool(canonical,size,digest)
def _verify_node(path:Path,size:int,digest:str)->None:
    try:_read(path,size=size,sha256=digest,maximum=512*1024*1024)
    except ApplicationWheelPreparationError as error:_fail('frontend dashboard node identity is invalid',error)
def _environment(work:Path)->dict[str,str]:
    return {'PATH':'','SYSTEMROOT':os.environ.get('SYSTEMROOT',os.environ.get('SystemRoot','')),'TEMP':str(work),'TMP':str(work),'NODE_OPTIONS':'--no-warnings','HOME':str(work),'USERPROFILE':str(work),'npm_config_offline':'true','npm_config_ignore_scripts':'true','NO_PROXY':'*'}
def _wrapper_config(work:Path,root:Path,out:Path)->Path:
    wrapper=work/'vite.release-wrapper.mts';config=root.joinpath('vite.config.ts').resolve(strict=True).as_uri();destination=out.resolve(strict=False).as_posix().replace("'","\\'")
    wrapper.write_text("import config from "+json.dumps(config)+";\nexport default async (env) => { const base = typeof config === 'function' ? await config(env) : config; return { ...base, envDir: false, publicDir: false, build: { ...(base.build ?? {}), outDir: '"+destination+"', emptyOutDir: true, manifest: true } }; };\n",encoding='utf-8')
    return wrapper
def _output_files(root:Path)->list[Path]:
    files=[];total=0;stack=[root];entries_seen=0
    while stack:
        current=stack.pop()
        try:
            info=current.lstat()
            if stat.S_ISLNK(info.st_mode) or getattr(info,'st_file_attributes',0)&0x400 or not stat.S_ISDIR(info.st_mode):raise ValueError()
            with os.scandir(current) as entries:
                for entry in entries:
                    entries_seen+=1
                    if entries_seen>_MAX_OUTPUT_FILES*8:_fail('frontend dashboard output is invalid')
                    info=entry.stat(follow_symlinks=False);path=Path(entry.path)
                    if stat.S_ISLNK(info.st_mode) or getattr(info,'st_file_attributes',0)&0x400:raise ValueError()
                    if stat.S_ISDIR(info.st_mode):stack.append(path)
                    elif stat.S_ISREG(info.st_mode):
                        total+=info.st_size;files.append(path)
                        if len(files)>_MAX_OUTPUT_FILES or total>_MAX_OUTPUT_TOTAL:_fail('frontend dashboard output is invalid')
                    else:raise ValueError()
        except (OSError,ValueError) as error:_fail('frontend dashboard output is invalid',error)
    if not files:_fail('frontend dashboard output is invalid')
    return files
def _output_name(value:object)->str:return _safe_name(value).as_posix()
def _validate_vite_graph(root:Path,files:list[Path])->None:
    names={path.relative_to(root).as_posix() for path in files}
    if 'index.html' not in names or '.vite/manifest.json' not in names:_fail('frontend dashboard output is invalid')
    try:manifest=json.loads(_read(root/'.vite/manifest.json',maximum=_MAX_FILE).decode('utf-8'),object_pairs_hook=_unique_object)
    except (ApplicationWheelPreparationError,UnicodeDecodeError,ValueError,json.JSONDecodeError) as error:_fail('frontend dashboard output is invalid',error)
    if not isinstance(manifest,dict) or not manifest or not isinstance(manifest.get('index.html'),dict) or manifest['index.html'].get('isEntry') is not True:_fail('frontend dashboard output is invalid')
    for key,item in manifest.items():
        _safe_name(key)
        if not isinstance(item,dict) or not isinstance(item.get('file'),str) or _output_name(item['file']) not in names:_fail('frontend dashboard output is invalid')
        for field in ('css','assets'):
            values=item.get(field,[])
            if not isinstance(values,list) or any(not isinstance(value,str) or _output_name(value) not in names for value in values):_fail('frontend dashboard output is invalid')
        for field in ('imports','dynamicImports'):
            values=item.get(field,[])
            if not isinstance(values,list) or any(not isinstance(value,str) or value not in manifest for value in values):_fail('frontend dashboard output is invalid')
@dataclass(frozen=True,slots=True)
class PreparedFrontendDashboard:
    root:Path;manifest_path:Path;manifest_sha256:str;manifest_size_bytes:int;source_manifest_sha256:str;source_manifest_size_bytes:int;tooling_manifest_sha256:str;tooling_manifest_size_bytes:int;node_sha256:str;node_size_bytes:int;node_version:str;package_lock_sha256:str;package_lock_size_bytes:int;node_modules_closure_not_pinned:bool=True;network_isolation_not_proven:bool=True
    module_inventory_sha256:str='';module_inventory_size_bytes:int=0;module_inventory_complete:bool=False;frontend_licence_closure_verified:bool=False
    package_binding_sha256:str='';package_bindings_present:int=0;package_bindings_missing:int=0
def _identity_valid(digest:object,size:object)->bool:return isinstance(size,int) and not isinstance(size,bool) and 0<size<=512*1024*1024 and isinstance(digest,str) and len(digest)==64 and all(c in '0123456789abcdef' for c in digest)
def prepare_frontend_dashboard(*,frontend_root:Path,source_manifest:Path,tooling_manifest:Path,node_executable:Path,node_sha256:str,node_size_bytes:int,node_version:str,destination:Path)->PreparedFrontendDashboard:
    source,_=_manifest(Path(source_manifest));tools,_=_manifest(Path(tooling_manifest));root=Path(frontend_root).absolute();output=Path(destination).absolute()
    if not _REQUIRED_TOOLS.issubset(tools) or any(not name.startswith('node_modules/') for name in tools):_fail('frontend dashboard manifest is incomplete')
    _assert_source_inventory(root,source)
    if output.exists() or output.is_symlink() or not output.name or not _identity_valid(node_sha256,node_size_bytes) or not isinstance(node_version,str):_fail('frontend dashboard destination or node identity is invalid')
    _verify_tree(root,source);bindings={name:_bind_tool(root,name,size,digest) for name,(size,digest) in tools.items()}
    _verify_node(Path(node_executable),node_size_bytes,node_sha256)
    output.parent.mkdir(parents=True,exist_ok=True);work=Path(tempfile.mkdtemp(prefix='.frontend-dashboard-',dir=output.parent));dashboard=work/'dashboard';cleanup_safe=True
    try:
        wrapper=_wrapper_config(work,root,dashboard)
        package_size,package_digest=source['package-lock.json']
        package_bindings=collect_frontend_package_bindings(root,_read_root_file(root,'package-lock.json',package_size,package_digest))
        mapping_file=work/'package-bindings.private.json';mapping_digest=package_bindings.write_mapping(mapping_file);mapping_identity=mapping_file.lstat()
        source_provenance=_normalized_manifest(source);tools_provenance=_normalized_manifest(tools)
        environment=_environment(work)
        environment.update(PROMPT_ENHANCER_FRONTEND_SOURCE_MANIFEST_SHA256=_sha(source_provenance),
                           PROMPT_ENHANCER_FRONTEND_TOOLING_MANIFEST_SHA256=_sha(tools_provenance),
                           PROMPT_ENHANCER_FRONTEND_PACKAGE_BINDINGS=str(mapping_file),
                           PROMPT_ENHANCER_FRONTEND_PACKAGE_BINDINGS_SHA256=mapping_digest)
        def run(arguments:tuple[object,...])->Any:
            nonlocal cleanup_safe
            try:return run_owned_process(tuple(map(str,arguments)),cwd=root,env=environment,stdout_limit=32768,stderr_limit=32768,timeout=180,maximum_active_processes=1)
            except OwnedProcessRunError as error:
                if error.code=='owned_process_cleanup_unconfirmed':
                    cleanup_safe=False
                    _fail('frontend dashboard cleanup unconfirmed',error)
                _fail('frontend dashboard command failed',error)
        version=run((node_executable,'--version'))
        if version.returncode or version.stdout.strip()!=('v'+node_version).encode('ascii'):_fail('frontend dashboard node version is invalid')
        for project,message in (('tsconfig.app.json','frontend dashboard typecheck failed'),('tsconfig.node.json','frontend dashboard node-config typecheck failed')):
            checked=run((node_executable,bindings['node_modules/typescript/bin/tsc'],'-p',project,'--incremental','false','--composite','false','--noEmit'));_verify_tree(root,source);_verify_tools(root,tools,bindings);_verify_node(Path(node_executable),node_size_bytes,node_sha256)
            if checked.returncode:_fail(message)
        package_bindings.verify();package_bindings.verify_mapping(mapping_file)
        built=run((node_executable,bindings['node_modules/vite/bin/vite.js'],'build','--config',wrapper,'--configLoader','runner'));_verify_tree(root,source);_verify_tools(root,tools,bindings);_verify_node(Path(node_executable),node_size_bytes,node_sha256)
        package_bindings.verify();package_bindings.verify_mapping(mapping_file)
        if built.returncode:
            code=_build_failure_code(built.stdout,getattr(built,'stderr',b''))
            _fail('frontend dashboard build failed'+(': '+code if code is not None else ''))
        files=_output_files(dashboard);_validate_vite_graph(dashboard,files)
        package_size,package_digest=source['package-lock.json']
        try:
            inventory=verify_frontend_module_inventory(root=dashboard,files=files,source_manifest=source,tooling_manifest=tools,
                package_lock_bytes=_read_root_file(root,'package-lock.json',package_size,package_digest),
                verified_package_keys=package_bindings.available_keys)
        except (FrontendModuleInventoryError,ApplicationWheelPreparationError) as error:_fail('frontend module inventory is invalid',error)
        published={'src/prompt_enhancer/_resources/dashboard/'+path.relative_to(dashboard).as_posix():(path.stat().st_size,_sha(_read(path,maximum=_MAX_FILE))) for path in files}
        relative_published={name.removeprefix('src/prompt_enhancer/_resources/dashboard/'):identity for name,identity in published.items()}
        if _sha(_normalized_manifest(relative_published))!=inventory.output_manifest_sha256:_fail('frontend module inventory output changed')
        if {path.relative_to(dashboard).as_posix() for path in _output_files(dashboard)}!=set(relative_published):_fail('frontend module inventory output changed')
        # Graph assertions are not independently trusted build provenance. Bind
        # inputs again after verification and final byte hashing, before publish.
        _verify_tree(root,source);_verify_tools(root,tools,bindings);_verify_node(Path(node_executable),node_size_bytes,node_sha256)
        package_bindings.verify();package_bindings.verify_mapping(mapping_file)
        if mapping_file.parent!=work or not _same(mapping_identity,mapping_file.lstat()):_fail('frontend package binding changed')
        mapping_file.unlink()  # Exact newly-created private file; never retain physical roots in output group.
        receipt=_normalized_manifest(published);(dashboard/'dashboard-manifest.json').write_bytes(receipt);os.rename(work,output);final=output/'dashboard'
        return PreparedFrontendDashboard(final,final/'dashboard-manifest.json',_sha(receipt),len(receipt),_sha(source_provenance),len(source_provenance),_sha(tools_provenance),len(tools_provenance),node_sha256,node_size_bytes,node_version,package_digest,package_size,
            module_inventory_sha256=inventory.sha256,module_inventory_size_bytes=inventory.size_bytes,
            package_binding_sha256=package_bindings.logical_digest,package_bindings_present=len(package_bindings.available_keys),package_bindings_missing=package_bindings.missing_count)
    except FrontendPackageBindingError as error:_fail('frontend package binding invalid',error)
    except (OSError,ApplicationWheelPreparationError) as error:_fail('frontend dashboard destination is unavailable',error)
    finally:
        if cleanup_safe and work.exists():
            try:_remove_owned(work,output.parent)
            except ApplicationWheelPreparationError as error:_fail('frontend dashboard cleanup unconfirmed',error)
__all__=('FrontendDashboardPreparationError','PreparedFrontendDashboard','prepare_frontend_dashboard')
