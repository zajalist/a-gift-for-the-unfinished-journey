"""The scoped CIN_25 widget patch must use the existing ending's authored content."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "Tools/GameFlow"))
import gen_caption_specs as captions  # noqa: E402


def test_endcard_source_and_scoped_specs_match():
    story = json.loads((ROOT / "docs/story/story-events.json").read_text(encoding="utf8"))
    ending = story["cinematics"]["CIN_25_END_CARD"]
    cues = [c for c in ending["cues"] if c["type"] == "ShowEndCard"]
    assert [(c["id"], c["at_s"]) for c in cues] == [
        ("Title", 2.0), ("Credits", 10.0), ("CreditsRoll", 17.0)]
    assert ending["final_state"] == [{"type": "OpenLevel", "id": "Title"}]
    short, roll, duration = captions.endcard_content()
    assert short == cues[1]["text"]
    credit_source = (ROOT / "docs/story/CREDITS_SCREEN.md").read_text(encoding="utf8")
    credit_block = credit_source.split("<!-- ROLL:BEGIN -->", 1)[1].split("<!-- ROLL:END -->", 1)[0]
    assert roll.splitlines() == credit_block.strip("\n").splitlines()[1:-1]
    assert len(roll.splitlines()) == 104 and duration == cues[2]["duration_s"] == 82.0

    scoped_tree = captions.endcard_tree()
    scoped_graph = captions.endcard_graph()
    assert [node["name"] for node in scoped_tree["tree"]] == ["EndCard"]
    assert scoped_tree["tree"][0]["properties"]["Visibility"] == "Collapsed"
    assert [g["graph"] for g in scoped_graph["graphs"]] == [
        "HideEndCard", "ShowEndCard", "ScrollCreditsStep"]
    full_tree = captions.tree()
    full_graph = captions.build()
    assert full_tree["tree"][-1] == scoped_tree["tree"][0]
    assert full_graph["graphs"][-3:] == scoped_graph["graphs"]
    for suffix, expected in (("tree", scoped_tree), ("graph", scoped_graph)):
        path = ROOT / f"Tools/GameFlow/specs/WBP_Saskarta_Caption.endcard.{suffix}.json"
        assert json.loads(path.read_text(encoding="utf8")) == expected


def test_generic_endcard_has_no_route_or_name_completion_display():
    tree = captions.endcard_tree()
    def names(items):
        for item in items:
            yield item['name']
            yield from names(item.get('children', []))
    assert set(names(tree['tree'])) == {
        'EndCard', 'EndCardBlack', 'EndCardTitle', 'EndCardCreditsShort',
        'EndCardRollViewport', 'EndCardRollScroll', 'EndCardRollLead',
        'EndCardCreditsRoll', 'EndCardRollTail', 'EndCardSafeScale', 'EndCardStage',
        'EndCardContent', 'EndCardOverline',
        *(f'EndCreditRow{i:03d}' for i in range(104))}
    graph = json.dumps(captions.endcard_graph())
    assert all(word not in graph for word in ('NamesLine', 'RouteLog', 'HeardCount', 'MissedCount', 'ModelProgress'))


def test_credits_use_safe_layout_full_contrast_and_measured_scroll():
    def nodes(items):
        for item in items:
            yield item
            yield from nodes(item.get('children', []))
    widgets = {x['name']: x for x in nodes(captions.endcard_tree()['tree'])}
    assert widgets['EndCardBlack']['properties']['ColorAndOpacity'][3] == 1
    assert widgets['EndCardBlack']['properties']['RenderOpacity'] == 1
    assert widgets['EndCardSafeScale']['properties']['Stretch'] == 'ScaleToFit'
    assert widgets['EndCardCreditsRoll']['class'] == 'VerticalBox'
    assert all(x['properties']['WrapTextAt'] == 900 for n, x in widgets.items()
               if n.startswith('EndCreditRow') and x['class'] == 'TextBlock')
    graph = captions.endcard_graph()
    # The October playtest approved a black stage throughout the roll; the
    # Sequencer camera remains hidden for continuity during level teardown.
    assert not any(node.get('get') == 'EndCardBlack' for part in graph['graphs']
                   for node in part['nodes'].values())
    scroll = next(g for g in graph['graphs'] if g['graph'] == 'ScrollCreditsStep')
    calls = [n.get('call') for n in scroll['nodes'].values()]
    assert 'GetScrollOffsetOfEnd' in calls and 'HideEndCard' not in calls
    assert 'FClamp' in calls and 'SetRenderOpacity' in calls
    assert '0.58' not in graph['graphs'][1]['defaults'].values()
    assert captions.tree()['slots']['SkipBox']['z_order'] > captions.endcard_tree()['slots']['EndCard']['z_order']


def _scoped_installer_module():
    sys.path.insert(0, str(ROOT / 'Tools/GameFlow/editor'))
    import install_caption_endcard
    return install_caption_endcard


def test_scoped_installer_plan_is_exact_and_offline():
    install = _scoped_installer_module()
    p, spec = install.plan()
    assert p['widget_count'] == 117
    assert p['functions'] == ['HideEndCard', 'ScrollCreditsStep', 'ShowEndCard']
    assert len(p['plan_sha256']) == 64
    assert set(spec['slots']) == {'EndCard'}
    chunks = install.tree_chunks(spec)
    assert [len(list(install.walk(nodes))) for _, nodes in chunks] == [13, 40, 40, 24]
    assert [n['name'] for parent, nodes in chunks if parent for n in nodes] == [f'EndCreditRow{i:03d}' for i in range(104)]


def test_scoped_installer_preserves_unrelated_descendants(tmp_path):
    install = _scoped_installer_module()
    p, spec = install.plan()
    class FakeConnection:
        owner, token = 'offline-root', None
        rows = {'Root': {'name': 'Root', 'class': 'CanvasPanel', 'parent': ''},
                'Subtitle': {'name': 'Subtitle', 'class': 'TextBlock', 'parent': 'Root', 'guid': 'keep'},
                'EndCard': {'name': 'EndCard', 'class': 'Overlay', 'parent': 'Root'},
                'OldCredits': {'name': 'OldCredits', 'class': 'TextBlock', 'parent': 'EndCard'}}
        calls = []
        def guard(self):
            pass
        def rpc(self, command, params, owner, token, timeout):
            assert timeout == 30 and owner == self.owner
            self.calls.append(command)
            if command == 'ui_layout_snapshot':
                offset, limit = params['offset'], params['limit']
                assert limit <= 50
                rows = list(self.rows.values())[offset:offset+limit]
                return {'widgets': rows, 'widget_count': len(rows), 'total_widget_count': len(self.rows),
                        'matched_widget_count': len(self.rows), 'offset': offset,
                        'has_more': offset+len(rows) < len(self.rows), 'next_offset': offset+len(rows)}
            if command == 'ui_mutate_tree':
                assert params == {'widget_blueprint_path': install.ASSET,
                                  'operation': 'remove', 'widget_name': 'EndCard'}
                for name in install.branch_names(self.rows):
                    del self.rows[name]
            elif command == 'ui_build_tree':
                def add(nodes, parent):
                    for node in nodes:
                        self.rows[node['name']] = {'name': node['name'], 'class': node['class'], 'parent': parent}
                        add(node.get('children', []), node['name'])
                add(params['tree'], params['parent_widget_name'])
                names = [n['name'] for n in install.walk(params['tree'])]
                return {'created': len(names), 'names': names}
            return {}
    connection = FakeConnection()
    state = {'plan': p, 'events': []}
    journal = tmp_path / 'journal.json'
    install.Installer(connection, journal, state).tree(spec)
    assert state['phase'] == 'tree-staged'
    assert connection.rows['Subtitle']['guid'] == 'keep'
    assert len(install.branch_names(connection.rows)) == 117
    assert not {'ui_save_widget', 'ui_compile_widget', 'python_run'} & set(connection.calls)


def test_scoped_installer_rejects_other_widget_changes():
    import pytest
    install = _scoped_installer_module()
    rows = {'Subtitle': {'name': 'Subtitle', 'parent': 'Root', 'guid': 'changed'}}
    with pytest.raises(ValueError, match='Non-EndCard'):
        install.assert_preserved(rows, {'Subtitle': {'name': 'Subtitle', 'parent': 'Root', 'guid': 'original'}})


def test_scoped_installer_records_ambiguous_native_failure(tmp_path):
    import pytest
    install = _scoped_installer_module()
    class FakeConnection:
        owner, token = 'offline-root', None
        def guard(self):
            pass
        def rpc(self, *args):
            raise TimeoutError('ambiguous deadline')
    journal = tmp_path / 'journal.json'
    state = {'plan': install.plan()[0], 'events': []}
    with pytest.raises(TimeoutError):
        install.Installer(FakeConnection(), journal, state).call('ui_build_tree', {})
    saved = json.loads(journal.read_text())
    assert len(saved['events']) == 1
    assert saved['events'][0]['status'] == 'failed'


def test_scoped_installer_rejects_native_response_shaping(tmp_path):
    import pytest
    install = _scoped_installer_module()
    class FakeConnection:
        owner, token = 'offline-root', None
        def guard(self):
            pass
        def rpc(self, *args):
            return {'widget_count': 117, 'widgets': [], '_truncated': [{'path': 'widgets', 'kind': 'array', 'removed': 67}]}
    state = {'plan': install.plan()[0], 'events': []}
    with pytest.raises(RuntimeError, match='truncated correctness'):
        install.Installer(FakeConnection(), tmp_path / 'journal.json', state).read()
    assert state['events'][0]['status'] == 'failed'


def test_scoped_installer_recovers_only_observed_legacy_long_text(tmp_path):
    install = _scoped_installer_module()
    full = 'The old credits\n' * 190
    clipped = full[:509] + '...'
    page = {'widgets': [{'name': 'EndCardCreditsRoll', 'class': 'TextBlock',
                         'parent': 'EndCardRollScroll', 'text_info': {'text': clipped}}],
            '_truncated': [{'path': 'widgets[0].text_info.text', 'kind': 'string',
                            'removed': len(full)-len(clipped)}]}
    path = install.ASSET + '.WBP_Saskarta_Caption:WidgetTree.EndCardCreditsRoll'
    class FakeConnection:
        owner, token = 'offline-root', None
        commands = []
        def guard(self):
            pass
        def rpc(self, command, params, *args):
            self.commands.append(command)
            if command == 'ui_layout_snapshot':
                return page
            if command == 'ui_query':
                assert params['include_properties'] is False
                return {'match_count': 1, 'matches': [{**page['widgets'][0], 'object_path': path}]}
            assert command == 'python_run' and path in params['script']
            assert 'set_' not in params['script'] and 'save_' not in params['script']
            return {'ok': True, 'stdout': 'ENDCARD_LEGACY_TEXT ' + json.dumps(full)}
    state = {'plan': install.plan()[0], 'events': []}
    connection = FakeConnection()
    result = install.Installer(connection, tmp_path / 'journal.json', state).call(
        'ui_layout_snapshot', {}, allow_legacy_roll_text=True)
    assert result['widgets'][0]['text_info']['text'] == full
    assert '_truncated' not in result
    assert state['events'][0]['raw_result'] == page
    assert connection.commands == ['ui_layout_snapshot', 'ui_query', 'python_run']


def test_scoped_installer_never_recovers_unrelated_or_changed_text(tmp_path):
    import pytest
    install = _scoped_installer_module()
    page = {'widgets': [{'name': 'Subtitle', 'class': 'TextBlock', 'parent': 'Root',
                         'text_info': {'text': 'text...'}}],
            '_truncated': [{'path': 'widgets[0].text_info.text', 'kind': 'string', 'removed': 2}]}
    instance = install.Installer(None, tmp_path / 'journal.json', {})
    with pytest.raises(RuntimeError, match='Only the observed legacy'):
        instance.recover_legacy_roll_text(page)
