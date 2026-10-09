"""Render the reviewed architecture catalog and SVGs; no application imports.

Use --check in review/CI. PNG rendering is a separate Windows documentation step.
The source observation is intentionally frozen; this tool never inspects provider
data or guesses readiness from file existence.
"""
from __future__ import annotations

import argparse
from collections import Counter
import html
import json
import re
from pathlib import Path
import textwrap

ROOT = Path(__file__).resolve().parents[1]
COLORS = {'ready': '#d4efdf', 'partial': '#fff0b3', 'absent': '#ffd8d8', 'mock': '#e1e5ea'}
LABELS = {'ready': 'READY (bounded)', 'partial': 'PARTIAL', 'absent': 'NOT IMPLEMENTED', 'mock': 'MOCK / DEMO'}


def outputs(root: Path) -> dict[str, str]:
    atlas = json.loads((root/'docs/architecture/atlas.json').read_text(encoding='utf-8'))
    observation = json.loads((root/'docs/architecture/source-observation.json').read_text(encoding='utf-8'))
    nodes = atlas['nodes']
    by_id = {n['id']: n for n in nodes}
    if len(by_id) != len(nodes):
        raise ValueError('duplicate_node_id')
    for n in nodes:
        if not re.fullmatch(r'[A-Z]+[0-9]+',n['id']):
            raise ValueError('invalid_node_id')
        if n['status'] not in COLORS or not set(n['depends_on']) <= by_id.keys():
            raise ValueError('invalid_status_or_dependency')
        if len(set(n['depends_on'])) != len(n['depends_on']):
            raise ValueError('duplicate_dependency')
        for ref in n['sources'] + n['tests']:
            if ref.split('::')[0] not in observation['bindings']:
                raise ValueError('missing_source_binding')

    def refs(items: list[str]) -> str:
        result = []
        for ref in items:
            path = ref.split('::')[0]
            bound = observation['bindings'][path]
            label = f'`{ref}`'
            if bound['publication'] != 'absent-on-main':
                label = f'[{label}](../../{path})'
            result.append(label + ' — ' + bound['publication'])
        return '<br>'.join(result) or 'No executable test/implementation at this level.'

    counts = Counter(n['status'] for n in nodes)
    md = ['# Feature and component catalog', '',
          'Generated from `atlas.json`; audit 2026-10-08. Read [scope and colors](README.md) first.', '',
          f'{len(nodes)} components: ' + ', '.join(f'{counts[s]} {s}' for s in COLORS) + '.', '',
          'These are component counts, not a beta-completion percentage. All status claims are scoped below.', '',
          '| ID | Component | Status | Scope | Gate |', '| --- | --- | --- | --- | --- |']
    for n in nodes:
        md.append(f"| [{n['id']}](#{n['id'].lower()}) | {n['label']} | {n.get('status_label',LABELS[n['status']])} | {n['scope']} | {n['gate']} |")
    for n in nodes:
        md += ['', f"## {n['id']}", '', f"**{n['label']}** — {n.get('status_label',LABELS[n['status']])}; {n['scope']}; gates `{n['gate']}`.", '',
               f"Dependencies: {', '.join(n['depends_on']) or 'Entry/boundary component; see system map.'}", '',
               '**Source:** ' + refs(n['sources']), '', '**Tests:** ' + refs(n['tests']), '',
               '**Evidence:** ' + n['evidence'], '', '**Gap:** ' + n['gap'], '', '**Next:** ' + n['next']]

    surfaces = ['# Route, feature and source inventory', '',
                'This census covers the inspected source tree, not every runtime state or every button.', '',
                f"{len(observation['source_files'])} Python/TypeScript/TSX/CSS source files; "
                f"{len(observation['routes'])} route families; {len(observation['feature_directories'])} frontend feature directories; "
                f"{len(observation['http_route_modules'])} HTTP route modules.", '',
                '## Route families', '', '| Route family | Title | Beta classification |', '| --- | --- | --- |']
    surfaces += [f"| `{r['id']}` | {r['title']} | {r['classification']} |" for r in observation['routes']]
    surfaces += ['', 'Route source: `frontend/src/app/appRouteManifest.ts` (development observation).', '',
                 '`project_automation` is the existing scheduling surface, not the absent multimodel builder.',
                 'Imported Projects/Sessions are analytics catalogs; authored Agent projects/chats use a different store.', '',
                 '## Frontend feature slices', '', '| Directory | Architectural lane |', '| --- | --- |']
    for name in observation['feature_directories']:
        lane = 'Agent' if name == 'agent' else 'Deferred product' if name in {'social','team-analytics'} else 'Runtime' if name == 'local-models' else 'Analytics / application UI'
        surfaces.append(f'| `frontend/src/features/{name}/` | {lane} |')
    surfaces += ['', '## Largest source files', '',
                 'Physical lines, including comments and blanks. Generated clients and append-only migrations need different treatment from hand-written coordinators.', '',
                 '| File | Lines |', '| --- | --- |']
    surfaces += [f"| `{f['path']}` | {f['lines']} |" for f in sorted(observation['source_files'],key=lambda f:f['lines'],reverse=True)[:20]]
    surfaces += ['', '## Static dependency pressure', '',
                 f"Python AST parse errors: {len(observation['parse_errors'])}. Absolute application imports pointing at infrastructure/interfaces: {len(observation['absolute_application_outward_imports'])}.", '',
                 'This is a narrow syntactic indicator. Relative/dynamic imports, calls and runtime wiring are not comprehensively analyzed. Each listed edge needs review before deciding it violates an intended boundary.', '',
                 '| Caller | Line | Imported module |', '| --- | --- | --- |']
    surfaces += [f"| `{r['path']}` | {r['line']} | `{r['target']}` |" for r in observation['absolute_application_outward_imports']]
    surfaces += ['', '## HTTP route modules', ''] + [f"- `{p}`" for p in observation['http_route_modules']]

    groups = [
        ('architecture-overview','System and delivery map',['MA01','MA02','MA05','MA06','MA12','MA16','A02','A06','A08','A13','A14','W02','W05','R21','R17','R25','MA19']),
        ('architecture-metrics','Analytics and live metrics',[n['id'] for n in nodes if n['domain']=='metrics']),
        ('architecture-contracts','Twenty canonical metric contracts',['MA07']+[n['id'] for n in nodes if n['domain']=='metric-contracts']),
        ('architecture-agent','Agent chat, tools and MCP',[n['id'] for n in nodes if n['domain']=='agent']),
        ('architecture-workflows','Planned workflow engine and model families',[n['id'] for n in nodes if n['id'].startswith('W') and not n['id'].startswith('WP')]),
        ('architecture-composer','Planned workflow composer integration',['W02','W04','W05']+[n['id'] for n in nodes if n['id'].startswith('WP')]),
        ('architecture-release','Native lifecycle and release',[n['id'] for n in nodes if n['domain']=='release']),
    ]
    rendered = {'docs/architecture/feature-catalog.md':'\n'.join(md)+'\n',
                'docs/architecture/surfaces.md':'\n'.join(surfaces)+'\n'}
    layouts = []
    for slug,title,ids in groups:
        width, card_w, card_h, pitch_y = 1800, 520, 166, 210
        height = 208 + ((len(ids)+2)//3)*pitch_y
        positions = {key:(70+(i%3)*570,150+(i//3)*pitch_y) for i,key in enumerate(ids)}
        cards, edges = [], []
        for key in ids:
            n = by_id[key]; x,y = positions[key]
            display_label = n['label'].replace('.', '. ').replace('_',' ') if key.startswith('MC') else n['label']
            if key in {'MC13','MC17'}:
                display_label += ' (measured adapter)'
            title_lines = textwrap.wrap(display_label,37,break_long_words=True)[:3]
            dep = ', '.join(n['depends_on']) or 'entry / shared boundary'
            cards.append(dict(id=key,x=x,y=y,w=card_w,h=card_h,color=COLORS[n['status']],
                lines=[f"{key}  |  {n.get('status_label',LABELS[n['status']])}",*title_lines],
                footer=('Needs: '+dep)[:78],scope=n['scope']))
            for parent in n['depends_on']:
                if parent not in positions:
                    continue
                px,py = positions[parent]
                edges.append(dict(source=parent,target=key,x1=px+card_w/2,y1=py+card_h,
                                  x2=x+card_w/2,y2=y,dashed=n['status']=='absent'))
        if slug == 'architecture-overview':
            # Selected architectural data/dependency edges, not a runtime trace.
            pairs=[('MA01','MA02'),('MA02','MA05'),('MA05','MA06'),('MA06','MA12'),('MA12','MA16'),
                   ('A02','A06'),('A08','A06'),('A13','A14'),('W02','W05'),('R21','R17'),('R25','R21')]
            edges=[]
            for a,b in pairs:
                ax,ay=positions[a]; bx,by=positions[b]
                edges.append(dict(source=a,target=b,x1=ax+card_w/2,y1=ay+card_h,
                                  x2=bx+card_w/2,y2=by,dashed=by_id[b]['status']=='absent'))
        for edge_index,e in enumerate(edges):
            sx,sy=positions[e['source']]; tx,ty=positions[e['target']]
            if sy == ty and abs(tx-sx)==570:
                right=tx>sx
                e.update(x1=sx+card_w if right else sx,y1=sy+card_h/2,
                         x2=tx if right else tx+card_w,y2=ty+card_h/2)
                e['points']=[[e['x1'],e['y1']],[e['x2'],e['y2']]]
            else:
                e.update(y1=sy+card_h,y2=ty)
                gutter=24+(edge_index%7)*5
                e['points']=[[e['x1'],e['y1']],[e['x1'],sy+card_h+16],
                             [gutter,sy+card_h+16],[gutter,ty-16],
                             [e['x2'],ty-16],[e['x2'],ty]]
        layout=dict(slug=slug,title=title,width=width,height=height,cards=cards,edges=edges)
        layouts.append(layout)
        svg=[f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
             '<rect width="100%" height="100%" fill="#f7f9fc"/>',
             '<defs><marker id="arrow" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8" fill="#8493a5"/></marker></defs>',
             f'<text x="70" y="48" font-family="Arial,sans-serif" font-size="30" fill="#172b46">{html.escape(title)}</text>',
             '<text x="70" y="82" font-family="Arial,sans-serif" font-size="18" fill="#42556b">2026-10-08 | Development observation + published baseline comparison | See catalog for evidence</text>']
        for j,s in enumerate(COLORS):
            lx=70+j*410
            svg += [f'<rect x="{lx}" y="104" width="20" height="20" fill="{COLORS[s]}" stroke="#748398"/>',
                    f'<text x="{lx+30}" y="120" font-family="Arial,sans-serif" font-size="17">{LABELS[s]}</text>']
        for e in edges:
            dash=' stroke-dasharray="8 5"' if e['dashed'] else ''
            points=' '.join(f'{x},{y}' for x,y in e['points'])
            svg.append(f'<polyline points="{points}" fill="none" stroke="#8493a5" stroke-width="2" marker-end="url(#arrow)"{dash}/>')
        for c in cards:
            x,y=c['x'],c['y']
            svg.append(f'<a href="../architecture/feature-catalog.md#{c["id"].lower()}"><rect x="{x}" y="{y}" width="{card_w}" height="{card_h}" rx="12" fill="{c["color"]}" stroke="#748398"/>')
            for j,line in enumerate(c['lines']):
                size=16 if j==0 else 23
                svg.append(f'<text x="{x+18}" y="{y+26+j*29}" font-family="Arial,sans-serif" font-size="{size}" fill="#172b46">{html.escape(line)}</text>')
            svg += [f'<text x="{x+18}" y="{y+145}" font-family="Arial,sans-serif" font-size="12" fill="#42556b">{html.escape(c["footer"])}</text>','</a>']
        svg += [f'<text x="70" y="{height-28}" font-family="Arial,sans-serif" font-size="17" fill="#42556b">Arrows = dependencies / data flow. Dashed = planned. Cross-page dependencies use catalog IDs. Colors do not certify beta.</text>','</svg>']
        rendered[f'docs/images/{slug}.svg']='\n'.join(svg)+'\n'
    rendered['docs/architecture/diagram-layouts.json']=json.dumps(layouts,indent=2)+'\n'
    return rendered


def main() -> int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check',action='store_true')
    args=parser.parse_args()
    failed=[]
    for ref,content in outputs(ROOT).items():
        path=ROOT/ref
        if args.check:
            if not path.is_file() or path.read_text(encoding='utf-8') != content:
                failed.append(ref)
        else:
            path.parent.mkdir(parents=True,exist_ok=True)
            path.write_text(content,encoding='utf-8')
    if failed:
        print('architecture_outputs_stale: '+', '.join(failed))
        return 1
    print('architecture outputs checked' if args.check else 'architecture outputs generated')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
