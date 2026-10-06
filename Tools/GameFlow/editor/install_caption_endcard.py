"""Guarded EndCard-only tree replacement; root is the only live caller.

check is offline. tree stages the new branch without compiling/saving. Next run
bpgraph for the scoped endcard.graph.json, then finish to verify, compile and save.
Each live RPC has a 30-second deadline and before/after lease/PIE/fault guards.
An interrupted tree run is never automatically replayed; inspect its journal.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import shutil
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from install_ending_folder import (EditorConnection, ROOT, digest, package_file,
                                   require_writable, save_state)

ASSET = '/Game/SaskartaGaea/GameFlow/UI/WBP_Saskarta_Caption'
TREE = ROOT / 'Tools/GameFlow/specs/WBP_Saskarta_Caption.endcard.tree.json'
GRAPH = ROOT / 'Tools/GameFlow/specs/WBP_Saskarta_Caption.endcard.graph.json'
JOURNAL = ROOT / 'Saved/Verification/credits_20261001/endcard-tree-install-v2.json'
FUNCTIONS = {'ShowEndCard', 'HideEndCard', 'ScrollCreditsStep'}


def walk(nodes):
    for node in nodes:
        yield node
        yield from walk(node.get('children', []))


def plan():
    import hashlib
    spec = json.loads(TREE.read_text(encoding='utf-8'))
    graph = json.loads(GRAPH.read_text(encoding='utf-8'))
    if spec['asset'] != ASSET or graph['asset'] != ASSET:
        raise ValueError('Only the canonical Caption asset is permitted')
    if [n['name'] for n in spec['tree']] != ['EndCard'] or spec.get('parent_widget_name'):
        raise ValueError('Expected exactly the EndCard root branch')
    if set(spec['slots']) != {'EndCard'}:
        raise ValueError('Slot edits must be confined to EndCard')
    names = [n['name'] for n in walk(spec['tree'])]
    if len(names) != len(set(names)) or not all(n.startswith(('EndCard', 'EndCreditRow')) for n in names):
        raise ValueError('Unexpected or duplicate EndCard descendant')
    if not set(spec['variables']) <= set(names):
        raise ValueError('Variable edits escape the EndCard branch')
    if {g['graph'] for g in graph['graphs']} != FUNCTIONS or {f['name'] for f in graph['functions']} != FUNCTIONS:
        raise ValueError('Graph packet must contain only the three EndCard functions')
    chunks = tree_chunks(spec)
    p = {'asset': ASSET, 'sha256': {str(f.relative_to(ROOT)): digest(f)
                                   for f in (TREE, GRAPH, Path(__file__).resolve())},
         'widget_count': len(names), 'functions': sorted(FUNCTIONS),
         'chunk_widget_counts': [len(list(walk(nodes))) for _, nodes in chunks]}
    p['plan_sha256'] = hashlib.sha256(json.dumps(p, sort_keys=True).encode()).hexdigest()
    return p, spec


def inventory(data):
    rows = data.get('widgets')
    if not isinstance(rows, list) or data.get('widget_count') != len(rows):
        raise ValueError('Missing or truncated widget inventory')
    # Geometry is recomputed by the read-only snapshot and is not an authored
    # property. Root child_count changes during the intentional branch removal.
    incidental = {'object_path', 'x', 'y', 'width', 'height', 'depth', 'laid_out', 'child_count'}
    result = {r['name']: {k: v for k, v in r.items() if k not in incidental} for r in rows}
    if len(result) != len(rows):
        raise ValueError('Duplicate widget names')
    return result


def tree_chunks(spec):
    """Stay below the native 50-item result limit; retain authored row order."""
    tree = json.loads(json.dumps(spec['tree']))
    panel = next(n for n in walk(tree) if n['name'] == 'EndCardCreditsRoll')
    rows = panel.pop('children')
    chunks = [(None, tree)] + [('EndCardCreditsRoll', rows[i:i+40]) for i in range(0, len(rows), 40)]
    if any(len(list(walk(nodes))) > 40 for _, nodes in chunks):
        raise ValueError('Tree chunk exceeds bounded native response size')
    return chunks


def branch_names(rows):
    branch = {'EndCard'} if 'EndCard' in rows else set()
    for _ in range(len(rows)):
        added = {n for n, r in rows.items() if r.get('parent') in branch} - branch
        if not added:
            break
        branch |= added
    return branch


def assert_preserved(rows, outside):
    actual = {n: r for n, r in rows.items() if n not in branch_names(rows)}
    if actual != outside:
        raise ValueError('Non-EndCard widgets changed; stop and inspect journal')


class Installer:
    def __init__(self, connection, journal, state):
        self.connection, self.journal, self.state = connection, journal, state

    def call(self, command, params, *, allow_legacy_roll_text=False):
        event = {'command': command, 'params': params, 'status': 'started'}
        self.state['events'].append(event)
        save_state(self.journal, self.state)
        try:
            self.connection.guard()
            if plan()[0] != self.state['plan']:
                raise ValueError('Source changed after reviewed plan')
            result = self.connection.rpc(command, params, self.connection.owner, self.connection.token, 30)
            event['result'] = result
            self.connection.guard()
            if not isinstance(result, dict) or result.get('ok') is False or result.get('error'):
                raise RuntimeError('Native operation did not succeed')
            if result.get('_truncated'):
                if not allow_legacy_roll_text or command != 'ui_layout_snapshot':
                    raise RuntimeError('Native response shaping truncated correctness evidence')
                event['raw_result'] = result
                result = self.recover_legacy_roll_text(result)
                event['result'] = result
                event['recovery'] = 'Complete legacy credits text read through observed widget object path'
            if result.get('stdout_truncated') or result.get('stderr_truncated') or result.get('stderr'):
                raise RuntimeError('Native Python output was truncated or reported stderr')
            if result.get('failed') or result.get('unknown_slot_props') or result.get('warnings') or result.get('errors'):
                raise RuntimeError('Native operation returned failures, warnings or unknown properties')
            event['status'] = 'ok'
        except BaseException as error:
            event.update(status='failed', error=str(error))
            save_state(self.journal, self.state)
            raise
        save_state(self.journal, self.state)
        print('ENDCARD_STEP_OK', command, flush=True)
        return result

    def recover_legacy_roll_text(self, data):
        """One observed legacy long TextBlock; every other truncation is fatal."""
        marks = data.get('_truncated', [])
        if len(marks) != 1:
            raise RuntimeError('Native response shaping truncated correctness evidence')
        mark = marks[0]
        match = re.fullmatch(r'widgets\[(\d+)\]\.text_info\.text', mark.get('path', ''))
        if not match or mark.get('kind') != 'string' or not isinstance(mark.get('removed'), int):
            raise RuntimeError('Native response shaping truncated correctness evidence')
        index = int(match[1])
        rows = data.get('widgets', [])
        if index >= len(rows):
            raise RuntimeError('Truncation points outside the observed page')
        row = rows[index]
        if row.get('name') != 'EndCardCreditsRoll' or row.get('class') != 'TextBlock':
            raise RuntimeError('Only the observed legacy EndCardCreditsRoll text may use full readback')
        query = self.call('ui_query', {'path': ASSET, 'flatten': True,
                                     'name_pattern': 'EndCardCreditsRoll', 'include_properties': False})
        candidates = query.get('matches', [])
        if query.get('match_count') != 1 or len(candidates) != 1:
            raise RuntimeError('Expected exactly one legacy credits widget path')
        observed = candidates[0]
        namespace = ASSET + '.' + ASSET.rsplit('/', 1)[1] + ':'
        path = observed.get('object_path', '')
        if (observed.get('name') != row['name'] or observed.get('class') != 'TextBlock'
                or observed.get('parent') != row.get('parent') or not path.startswith(namespace)):
            raise RuntimeError('Legacy text path does not identify the observed Caption widget')
        script = ('import unreal\nimport json\n'
                  f'widget=unreal.load_object(None,{path!r})\n'
                  'assert isinstance(widget,unreal.TextBlock)\n'
                  "print('ENDCARD_LEGACY_TEXT',json.dumps(str(widget.get_text()),ensure_ascii=True))")
        read = self.call('python_run', {'script': script})
        prefix = 'ENDCARD_LEGACY_TEXT '
        lines = [line[len(prefix):] for line in read.get('stdout', '').splitlines() if line.startswith(prefix)]
        if read.get('ok') is not True or len(lines) != 1:
            raise RuntimeError('Full legacy text read was not confirmed')
        full = json.loads(lines[0])
        clipped = row['text_info']['text']
        # Native response builder measures TCHAR/UTF-16 units, not codepoints.
        units = lambda value: len(value.encode('utf-16-le')) // 2
        if (not isinstance(full, str) or not clipped.endswith('...') or not full.startswith(clipped[:-3])
                or units(full) != units(clipped) + mark['removed']):
            raise RuntimeError('Full legacy text does not match the exact native clipped prefix/length')
        complete = json.loads(json.dumps(data))
        complete['widgets'][index]['text_info']['text'] = full
        del complete['_truncated']
        return complete

    def read(self):
        all_rows, offset, total = {}, 0, None
        for _ in range(10):
            page = self.call('ui_layout_snapshot', {'widget_blueprint_path': ASSET, 'offset': offset, 'limit': 40},
                             allow_legacy_roll_text=True)
            count = page.get('total_widget_count')
            if not isinstance(count, int) or count > 400 or page.get('matched_widget_count') != count:
                raise ValueError('Unbounded or filtered widget inventory')
            if total is not None and total != count:
                raise ValueError('Widget count changed during readback')
            total = count
            if page.get('offset') != offset:
                raise ValueError('Snapshot did not honor requested page offset')
            rows = inventory(page)
            if all_rows.keys() & rows.keys():
                raise ValueError('Repeated widget page')
            all_rows.update(rows)
            if page.get('has_more') is False:
                if len(all_rows) != total:
                    raise ValueError('Incomplete paginated widget inventory')
                return all_rows
            if not rows or page.get('next_offset') != offset + len(rows):
                raise ValueError('Invalid widget pagination cursor')
            offset = page['next_offset']
        raise ValueError('Widget inventory exceeded its bounded page budget')

    def tree(self, spec):
        before = self.read()
        roots = [n for n, r in before.items() if not r.get('parent')]
        if len(roots) != 1 or before[roots[0]]['class'] != 'CanvasPanel':
            raise ValueError('Expected the existing single Caption CanvasPanel root')
        if 'EndCard' not in before or before['EndCard']['parent'] != roots[0]:
            raise ValueError('Expected the existing EndCard branch directly under the root')
        outside = {n: r for n, r in before.items() if n not in branch_names(before)}
        expected = {n['name'] for n in walk(spec['tree'])}
        if expected & outside.keys():
            raise ValueError('New EndCard names collide with another branch')
        self.state.update(before=before, outside=outside, phase='tree-started')
        save_state(self.journal, self.state)
        self.call('ui_mutate_tree', {'widget_blueprint_path': ASSET,
                                   'operation': 'remove', 'widget_name': 'EndCard'})
        remaining = self.read()
        if branch_names(remaining):
            raise ValueError('Old EndCard removal was not confirmed')
        assert_preserved(remaining, outside)
        for parent, nodes in tree_chunks(spec):
            built = self.call('ui_build_tree', {'widget_blueprint_path': ASSET,
                                              'parent_widget_name': parent or roots[0], 'tree': nodes})
            chunk_names = {n['name'] for n in walk(nodes)}
            if built.get('created') != len(chunk_names) or set(built.get('names', [])) != chunk_names:
                raise ValueError('Created widget inventory differs from exact spec')
        for name, slot in spec['slots'].items():
            anchors = slot['anchors']
            props = {k: v for k, v in slot.items() if k != 'anchors'}
            props.update(anchors_min=anchors[:2], anchors_max=anchors[2:])
            self.call('ui_set_widget_properties', {'widget_blueprint_path': ASSET,
                                                 'widget_name': name, 'slot_props': props})
        for name in spec['variables']:
            self.call('ui_set_variable', {'widget_blueprint_path': ASSET,
                                        'widget_name': name, 'is_variable': True})
        rows = self.read()
        assert_preserved(rows, outside)
        if branch_names(rows) != expected:
            raise ValueError('Readback does not contain the exact EndCard descendants')
        self.state.update(phase='tree-staged', staged=rows)
        save_state(self.journal, self.state)
        print('ENDCARD_TREE_STAGED_UNSAVED: run only the scoped endcard graph build, then finish')

    def finish(self, spec):
        rows = self.read()
        assert_preserved(rows, self.state['outside'])
        if branch_names(rows) != {n['name'] for n in walk(spec['tree'])}:
            raise ValueError('EndCard readback inventory changed')
        require_writable(package_file(ASSET, ROOT))
        compiled = self.call('ui_compile_widget', {'widget_blueprint_path': ASSET, 'save_on_success': False})
        if compiled.get('success') is not True or compiled.get('compiled_clean') is not True:
            raise ValueError('Clean widget compile was not confirmed')
        self.call('python_run', {'script': "import unreal\nbp=unreal.load_asset('" + ASSET + "')\nsaved=unreal.EditorAssetLibrary.save_loaded_asset(bp,False)\nassert saved is True\nprint('ENDCARD_SAVED_TRUE')"})
        saved = self.state['events'][-1]['result']
        if saved.get('ok') is not True or 'ENDCARD_SAVED_TRUE' not in saved.get('stdout', ''):
            raise ValueError('Strict saved True was not confirmed')
        assert_preserved(self.read(), self.state['outside'])
        self.state.update(phase='saved', saved_sha256=digest(package_file(ASSET, ROOT)))
        save_state(self.journal, self.state)
        print('ENDCARD_TREE_COMPILED_SAVED_OK')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('check', 'tree', 'finish'))
    parser.add_argument('--owner')
    parser.add_argument('--plan-sha256')
    parser.add_argument('--journal', type=Path, default=JOURNAL)
    args = parser.parse_args()
    p, spec = plan()
    if args.mode == 'check':
        print(json.dumps(p, indent=2))
        return
    if not args.owner or args.plan_sha256 != p['plan_sha256']:
        parser.error('Live operation requires --owner and the exact reviewed check --plan-sha256')
    target = package_file(ASSET, ROOT)
    require_writable(target)
    if not target.is_file():
        raise ValueError('Existing Caption package required')
    if args.mode == 'tree':
        if args.journal.exists():
            raise ValueError('Journal already exists; inspect it before choosing a new run. No automatic replay.')
        backup = args.journal.parent / (args.journal.stem + '-before')
        backup.mkdir(parents=True, exist_ok=False)
        originals = {}
        for suffix in ('.uasset', '.uexp', '.ubulk'):
            source = target.with_suffix(suffix)
            if source.exists():
                require_writable(source)
                shutil.copy2(source, backup / source.name)
                originals[source.name] = digest(source)
        state = {'plan': p, 'phase': 'preflight', 'backup': str(backup), 'original_sha256': originals, 'events': []}
    else:
        state = json.loads(args.journal.read_text(encoding='utf-8'))
        if state['plan'] != p or state['phase'] != 'tree-staged':
            raise ValueError('Finish requires this exact tree-staged journal')
    install = Installer(EditorConnection(args.owner), args.journal, state)
    (install.tree if args.mode == 'tree' else install.finish)(spec)


if __name__ == '__main__':
    main()
