"""Generate frontend tokens from the exact, bounded Figma token export."""
import json,re
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent
source=json.loads((ROOT/'design-system/smena-token-source.json').read_text())
records=source['tokens'];by_id={v['id']:v for v in records}
def css_name(v):
 syntax=v['web']
 if not re.fullmatch(r'var\(--[a-zA-Z0-9-]+\)',syntax): raise ValueError('Invalid WEB syntax: '+syntax)
 return syntax[4:-1]
def resolved(v,seen=()):
 if v['id'] in seen: raise ValueError('Alias cycle')
 value=v['value']
 return resolved(by_id[value['id']],(*seen,v['id'])) if isinstance(value,dict) and value.get('type')=='VARIABLE_ALIAS' else value
def hex_color(c): return '#'+''.join(f'{round(c[k]*255):02X}' for k in ['r','g','b'])
def css_value(v):
 value=v['value']
 if isinstance(value,dict) and value.get('type')=='VARIABLE_ALIAS': return 'var('+css_name(by_id[value['id']])+')'
 if v['type']=='COLOR': return hex_color(value)
 if v['type']=='FLOAT': return f'{value:g}px'
 return json.dumps(value)
collections={c['id']:c['name'] for c in source['collections']}
lines=[f"/* Смена Design System v{source['version']} · Light. Generated from Figma token IDs. */",':root {']
for c in source['collections']:
 lines.append('  /* '+c['name']+' */')
 for v in records:
  if v['collectionId']==c['id']: lines.append('  '+css_name(v)+': '+css_value(v)+';')
lines.append('  --sm-font-family: "Inter", system-ui, -apple-system, "Segoe UI", sans-serif;')
for name,t in source['type'].items():
 key=re.sub(r'([A-Z])',r'-\1',name).lower()
 for field,value in [('size',str(t['size'])+'px'),('line-height',str(t['lineHeight'])+'px'),('weight',str(t['weight']))]: lines.append(f'  --sm-type-{key}-{field}: {value};')
lines+=['  --sm-motion-fast: 150ms;','}','']
(ROOT/'design-system/smena-design-tokens.css').write_text('\n'.join(lines))
result={k:v for k,v in source.items() if k not in ['tokens','collections']}
result.update(note='Own design system based on the Smena flow and public Notion patterns; not an official Notion token export.',primitives={},semantic={},component={},spacing=[],radius=[],layout={},figma={})
for v in records:
 name=v['name'];group=collections[v['collectionId']];value=v['value']
 if 'Primitives' in group: result['primitives'][name.removeprefix('color/')]=hex_color(resolved(v))
 elif name.startswith('color/'):
  target=by_id[value['id']]['name'].removeprefix('color/') if value.get('type')=='VARIABLE_ALIAS' else hex_color(value)
  result['semantic'][name.removeprefix('color/')]=target
 elif name.startswith('space/'): result['spacing'].append(value)
 elif name.startswith('radius/'): result['radius'].append(value)
 elif name.startswith('layout/'): result['layout'][name.removeprefix('layout/')]=value
 else: result['component'][name]=by_id[value['id']]['name'].removeprefix('color/')
 result['figma'][name]={'id':v['id'],'css':css_name(v),'resolved':hex_color(resolved(v)) if v['type']=='COLOR' else resolved(v)}
(ROOT/'design-system/smena-design-tokens.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
print(f'Generated {len(records)} tokens, {len(source["type"])} type styles.')

(ROOT/'src/design-tokens.css').write_text((ROOT/'design-system/smena-design-tokens.css').read_text())
