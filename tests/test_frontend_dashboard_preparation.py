import hashlib,json
from pathlib import Path
from types import SimpleNamespace
import pytest
from prompt_enhancer.infrastructure import frontend_dashboard_preparation as prep
from tests.test_frontend_module_inventory import emit_inventory,lock_bytes

def h(b): return hashlib.sha256(b).hexdigest()
def write_manifest(path,root,names): path.write_text(json.dumps({n:{'sha256':h((root/n).read_bytes()),'size_bytes':(root/n).stat().st_size} for n in names}))
def inputs(tmp):
 root=tmp/'front';(root/'src').mkdir(parents=True);(root/'node_modules/typescript/bin').mkdir(parents=True);(root/'node_modules/vite/bin').mkdir(parents=True)
 (root/'src/build').mkdir()
 names=['index.html','package.json','package-lock.json','vite.config.ts','tsconfig.json','tsconfig.app.json','tsconfig.node.json','playwright.config.ts','src/main.tsx','src/build/viteModuleInputInventory.ts']
 for n in names:(root/n).write_text('{}')
 (root/'package-lock.json').write_bytes(lock_bytes())
 tools=['node_modules/typescript/bin/tsc','node_modules/vite/bin/vite.js']
 for n in tools:(root/n).write_text('tool')
 (root/'node_modules/vite/package.json').write_text(json.dumps({'name':'vite','version':'8.1.5'}))
 node=tmp/'node.exe';node.write_bytes(b'node');source=tmp/'source.json';tool=tmp/'tools.json';write_manifest(source,root,names);write_manifest(tool,root,tools)
 return root,source,tool,node,names
def emit(out,manifest=None):
 (out/'.vite').mkdir(parents=True);(out/'assets').mkdir();(out/'index.html').write_text('x');(out/'assets/main.js').write_text('x');(out/'assets/main.css').write_text('x')
 (out/'.vite/manifest.json').write_text(manifest or json.dumps({'index.html':{'file':'assets/main.js','isEntry':True,'css':['assets/main.css'],'imports':['chunk']},'chunk':{'file':'assets/main.js','assets':[]} }))
def prepare(monkeypatch,tmp,manifest=None,mutate=None):
 root,source,tool,node,names=inputs(tmp);calls=[]
 def run(argv,**kw):
  calls.append(argv)
  if '--version' in argv:return SimpleNamespace(returncode=0,stdout=b'v1.2.3\n')
  if mutate and len(calls)==2:mutate(root,node)
  if 'vite.js' in str(argv[1]):
   wrapper=Path(argv[argv.index('--config')+1]);assert 'envDir: false' in wrapper.read_text() and 'publicDir: false' in wrapper.read_text();emit(wrapper.parent/'dashboard',manifest)
   source_entries=prep._manifest(source)[0];tool_entries=prep._manifest(tool)[0]
   assert kw['env']['PROMPT_ENHANCER_FRONTEND_SOURCE_MANIFEST_SHA256']==h(prep._normalized_manifest(source_entries))
   assert kw['env']['PROMPT_ENHANCER_FRONTEND_TOOLING_MANIFEST_SHA256']==h(prep._normalized_manifest(tool_entries))
   assert kw['timeout']==180 and kw['maximum_active_processes']==1 and kw['stdout_limit']==32768 and kw['stderr_limit']==32768
   emit_inventory(wrapper.parent/'dashboard',source_entries,tool_entries,(root/'package-lock.json').read_bytes())
  return SimpleNamespace(returncode=0,stdout=b'')
 monkeypatch.setattr(prep,'run_owned_process',run)
 return root,source,tool,node,names,calls
def call(root,s,t,node,out): return prep.prepare_frontend_dashboard(frontend_root=root,source_manifest=s,tooling_manifest=t,node_executable=node,node_sha256=h(b'node'),node_size_bytes=4,node_version='1.2.3',destination=out)

@pytest.mark.parametrize('code', ['owned_process_timeout', 'owned_process_stdout_limit', 'owned_process_stderr_limit', 'owned_process_cleanup_unconfirmed'])
def test_owned_failure_preserves_stage_only_when_cleanup_unconfirmed(monkeypatch,tmp_path,code):
 root,s,t,node,_=inputs(tmp_path);out=tmp_path/'out';removed=[];original=prep._remove_owned
 def remove(directory,parent):
  removed.append(directory)
  return original(directory,parent)
 def run(*args,**kwargs):raise prep.OwnedProcessRunError(code)
 monkeypatch.setattr(prep,'run_owned_process',run);monkeypatch.setattr(prep,'_remove_owned',remove)
 with pytest.raises(prep.FrontendDashboardPreparationError) as caught:call(root,s,t,node,out)
 assert not out.exists() and caught.value.__cause__.code==code
 retained=list(tmp_path.glob('.frontend-dashboard-*'))
 if code=='owned_process_cleanup_unconfirmed':
  assert str(caught.value)=='frontend dashboard cleanup unconfirmed' and len(retained)==1 and not removed
 else:
  assert str(caught.value)=='frontend dashboard command failed' and not retained and len(removed)==1

def test_success_vite_graph_provenance_and_owned_commands(monkeypatch,tmp_path):
 root,s,t,node,_,calls=prepare(monkeypatch,tmp_path);result=call(root,s,t,node,tmp_path/'out')
 assert result.root.joinpath('index.html').exists() and len(calls)==4
 assert result.source_manifest_sha256==h(prep._normalized_manifest(prep._manifest(s)[0]))
 assert result.tooling_manifest_sha256==h(prep._normalized_manifest(prep._manifest(t)[0]))
 assert result.node_modules_closure_not_pinned and result.network_isolation_not_proven
 assert len(result.module_inventory_sha256)==64 and result.module_inventory_size_bytes>0
 assert not result.module_inventory_complete and not result.frontend_licence_closure_verified
 assert len(result.package_binding_sha256)==64 and result.package_bindings_present==1 and result.package_bindings_missing==2
 assert not (result.root.parent/'package-bindings.private.json').exists()
 assert not any(path.name=='package-bindings.private.json' for path in result.root.rglob('*'))

@pytest.mark.parametrize('kind',["missing-source","duplicate","bad-hash","raw-dot"])
def test_rejects_manifest_adversaries(tmp_path,kind):
 root,s,t,node,names=inputs(tmp_path)
 if kind=='missing-source':write_manifest(s,root,names[:-1])
 elif kind=='duplicate':s.write_text('{"index.html":{"sha256":"'+'0'*64+'","size_bytes":1},"index.html":{"sha256":"'+'0'*64+'","size_bytes":1}}')
 elif kind=='bad-hash':data=json.loads(s.read_text());data['index.html']['sha256']='0'*64;s.write_text(json.dumps(data))
 else:data=json.loads(s.read_text());data['src//main.tsx']=data.pop('src/main.tsx');s.write_text(json.dumps(data))
 with pytest.raises(prep.FrontendDashboardPreparationError):call(root,s,t,node,tmp_path/'out')

@pytest.mark.parametrize('failure',["app","node"])
def test_typechecks_fail_closed(monkeypatch,tmp_path,failure):
 root,s,t,node,_,_=prepare(monkeypatch,tmp_path)
 def run(argv,**kw):
  if '--version' in argv:return SimpleNamespace(returncode=0,stdout=b'v1.2.3\n')
  return SimpleNamespace(returncode=1 if failure in ('app' if any('tsconfig.app' in str(value) for value in argv) else 'node') else 0,stdout=b'')
 monkeypatch.setattr(prep,'run_owned_process',run)
 with pytest.raises(prep.FrontendDashboardPreparationError,match='typecheck'):call(root,s,t,node,tmp_path/'out')

@pytest.mark.parametrize('target',["source","tool","node"])
def test_rejects_input_mutation_after_command(monkeypatch,tmp_path,target):
 def mutate(root,node): {'source':root/'src/main.tsx','tool':root/'node_modules/typescript/bin/tsc','node':node}[target].write_text('changed')
 root,s,t,node,_,_=prepare(monkeypatch,tmp_path,mutate=mutate)
 with pytest.raises(prep.FrontendDashboardPreparationError):call(root,s,t,node,tmp_path/'out')

@pytest.mark.parametrize('manifest',[json.dumps({'index.html':{'file':'missing.js','isEntry':True}}),json.dumps({'index.html':{'file':'assets/main.js','isEntry':True,'imports':['missing']}}),'{"x":{},"x":{}}'])
def test_rejects_invalid_or_duplicate_vite_graph(monkeypatch,tmp_path,manifest):
 root,s,t,node,_,_=prepare(monkeypatch,tmp_path,manifest=manifest)
 with pytest.raises(prep.FrontendDashboardPreparationError):call(root,s,t,node,tmp_path/'out')

def test_no_clobber_and_env_wrapper_are_safe(monkeypatch,tmp_path):
 root,s,t,node,names=inputs(tmp_path);(root/'.env.local').write_text('never read');out=tmp_path/'out';out.mkdir()
 monkeypatch.setattr(prep,'run_owned_process',lambda *a,**k:pytest.fail('commands must not run'))
 with pytest.raises(prep.FrontendDashboardPreparationError):call(root,s,t,node,out)
 assert out.exists()

def test_output_bound_cleans_owned_staging(monkeypatch,tmp_path):
 root,s,t,node,_,_=prepare(monkeypatch,tmp_path)
 monkeypatch.setattr(prep,'_MAX_OUTPUT_FILES',3)
 original=prep._output_files
 def bounded(out):
  (out/'assets/extra.js').write_text('x')
  return original(out)
 monkeypatch.setattr(prep,'_output_files',bounded)
 with pytest.raises(prep.FrontendDashboardPreparationError,match='output is invalid'):call(root,s,t,node,tmp_path/'out')
 assert not (tmp_path/'out').exists() and not list(tmp_path.glob('.frontend-dashboard-*'))

def test_output_root_reparse_point_is_rejected(monkeypatch,tmp_path):
 root=tmp_path/'output';root.mkdir()
 original=Path.lstat
 def reparse(path):
  info=original(path)
  if path==root:
   return SimpleNamespace(st_mode=info.st_mode,st_file_attributes=0x400)
  return info
 monkeypatch.setattr(Path,'lstat',reparse)
 with pytest.raises(prep.FrontendDashboardPreparationError):prep._output_files(root)

def test_physical_tool_binding_accepts_in_node_modules_target(monkeypatch,tmp_path):
 root=tmp_path/'front';logical=root/'node_modules/typescript/bin/tsc';canonical=root/'node_modules/.store/typescript/bin/tsc'
 canonical.parent.mkdir(parents=True);canonical.write_bytes(b'tool');logical.parent.mkdir(parents=True);logical.write_bytes(b'logical')
 original=Path.resolve
 monkeypatch.setattr(Path,'resolve',lambda path,strict=False: canonical if path==logical else original(path,strict=strict))
 assert prep._bind_tool(root,'node_modules/typescript/bin/tsc',4,h(b'tool'))==canonical

def test_physical_tool_binding_rejects_changed_or_escaping_target(monkeypatch,tmp_path):
 root=tmp_path/'front';logical=root/'node_modules/vite/bin/vite.js';first=root/'node_modules/.store/a/vite.js';second=root/'node_modules/.store/b/vite.js';outside=tmp_path/'outside.js'
 for path in (first,second,outside):path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(b'tool')
 logical.parent.mkdir(parents=True);logical.write_bytes(b'logical');target=[first];original=Path.resolve
 monkeypatch.setattr(Path,'resolve',lambda path,strict=False: target[0] if path==logical else original(path,strict=strict))
 binding=prep._bind_tool(root,'node_modules/vite/bin/vite.js',4,h(b'tool'));target[0]=second
 with pytest.raises(prep.FrontendDashboardPreparationError):prep._verify_tools(root,{'node_modules/vite/bin/vite.js':(4,h(b'tool'))},{'node_modules/vite/bin/vite.js':binding})
 target[0]=outside
 with pytest.raises(prep.FrontendDashboardPreparationError):prep._bind_tool(root,'node_modules/vite/bin/vite.js',4,h(b'tool'))

def test_required_plugin_is_exact_and_cannot_be_missing(monkeypatch,tmp_path):
 root,s,t,node,names=inputs(tmp_path)
 write_manifest(s,root,[name for name in names if name!='src/build/viteModuleInputInventory.ts'])
 monkeypatch.setattr(prep,'run_owned_process',lambda *a,**k:pytest.fail('must refuse before build'))
 with pytest.raises(prep.FrontendDashboardPreparationError,match='incomplete'):call(root,s,t,node,tmp_path/'out')

def test_new_release_requires_graph(monkeypatch,tmp_path):
 root,s,t,node,_,_=prepare(monkeypatch,tmp_path)
 original=prep._output_files
 def files(out):
  (out/'module-input-inventory.json').unlink()
  return original(out)
 monkeypatch.setattr(prep,'_output_files',files)
 with pytest.raises(prep.FrontendDashboardPreparationError,match='module inventory'):call(root,s,t,node,tmp_path/'out')
 assert not (tmp_path/'out').exists()

@pytest.mark.parametrize('mutation',['source','tool','node','output','extra'])
def test_rechecks_inputs_and_outputs_after_graph_verification(monkeypatch,tmp_path,mutation):
 root,s,t,node,_,_=prepare(monkeypatch,tmp_path)
 original=prep.verify_frontend_module_inventory
 def verify(**kwargs):
  result=original(**kwargs)
  target={'source':root/'src/main.tsx','tool':root/'node_modules/vite/bin/vite.js',
          'node':node,'output':kwargs['root']/'assets/main.js','extra':kwargs['root']/'assets/extra.js'}[mutation]
  target.write_bytes(b'changed')
  return result
 monkeypatch.setattr(prep,'verify_frontend_module_inventory',verify)
 with pytest.raises(prep.FrontendDashboardPreparationError):call(root,s,t,node,tmp_path/'out')
 assert not (tmp_path/'out').exists() and not list(tmp_path.glob('.frontend-dashboard-*'))

@pytest.mark.parametrize('prefix',['','Error: ','[plugin prompt-enhancer:module-input-inventory] ',
 'Error: [plugin prompt-enhancer:module-input-inventory] '])
def test_closed_build_diagnostic_whole_fixed_lines(prefix):
 for code in prep._BUILD_FAILURE_CODES:
  assert prep._build_failure_code(b'public build progress\n',('  '+prefix+code+'\r\n').encode())==code
 assert prep._build_failure_code(b'',b'\x1b[31mError: module_input_path_unsafe\x1b[39m\n')=='module_input_path_unsafe'

@pytest.mark.parametrize('output',[
 b'Error: module_input_unknown\n', b'Error: module_input_path_unsafe_extra\n',
 b'prefix module_input_path_unsafe suffix\n', b'fail("module_input_path_unsafe")\n',
 b'Error: module_input_path_unsafe /private/example\n', b'/private/module_input_path_unsafe\n',
 b'[plugin other] module_input_path_unsafe\n', 'Error: module_input_path_unsafe\u200b\n'.encode(),
 'Error: module_input_path_unsa\u0192e\n'.encode(), b'Error: module_input_path_unsafe\xff\n',
 b'Error: module_input_path_unsafe\nError: module_input_lock_invalid\n', b'x'*32769],
 ids=['unknown','suffix','context','source-call','appended-path','path-token','other-plugin','unicode-tail',
      'unicode-lookalike','invalid-utf8','multiple','over-budget'])
def test_closed_build_diagnostic_rejects_unknown_misleading_or_ambiguous(output):
 assert prep._build_failure_code(output,b'') is None

def test_duplicate_same_diagnostic_is_not_ambiguous():
 assert prep._build_failure_code(b'Error: module_input_path_unsafe\n',b'Error: module_input_path_unsafe\n')=='module_input_path_unsafe'

def test_diagnostic_allowlist_matches_owned_plugin_literals():
 import re
 source=(Path(__file__).parents[1]/'frontend/src/build/viteModuleInputInventory.ts').read_text(encoding='utf-8')
 assert set(re.findall(r'fail\("(module_input_[a-z_]+)"\)',source))==prep._BUILD_FAILURE_CODES

def test_nonzero_build_emits_only_closed_diagnostic(monkeypatch,tmp_path):
 root,s,t,node,_,_=prepare(monkeypatch,tmp_path)
 original=prep.run_owned_process
 def run(argv,**kwargs):
  if 'vite.js' in str(argv[1]):return SimpleNamespace(returncode=1,stdout=b'private diagnostic detail\n',stderr=b'Error: module_input_physical_binding_missing\n')
  return original(argv,**kwargs)
 monkeypatch.setattr(prep,'run_owned_process',run)
 with pytest.raises(prep.FrontendDashboardPreparationError) as raised:call(root,s,t,node,tmp_path/'out')
 assert str(raised.value)=='frontend dashboard build failed: module_input_physical_binding_missing'
 assert not (tmp_path/'out').exists() and not list(tmp_path.glob('.frontend-dashboard-*'))

def test_private_mapping_change_after_build_refused(monkeypatch,tmp_path):
 root,s,t,node,_,_=prepare(monkeypatch,tmp_path)
 original=prep.run_owned_process
 def run(argv,**kwargs):
  result=original(argv,**kwargs)
  if 'vite.js' in str(argv[1]):Path(kwargs['env']['PROMPT_ENHANCER_FRONTEND_PACKAGE_BINDINGS']).write_bytes(b'changed')
  return result
 monkeypatch.setattr(prep,'run_owned_process',run)
 with pytest.raises(prep.FrontendDashboardPreparationError):call(root,s,t,node,tmp_path/'out')
 assert not (tmp_path/'out').exists()
