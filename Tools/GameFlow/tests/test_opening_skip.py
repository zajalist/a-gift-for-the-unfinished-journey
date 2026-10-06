import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "Tools" / "GameFlow"))


def load_spec(name):
    return json.loads((ROOT / "Tools" / "GameFlow" / "specs" / name).read_text(encoding="utf-8"))


def graph(spec, name):
    return next(item for item in spec["graphs"] if item["graph"] == name)


def has_link(g, a, b):
    return [a, b] in g["links"]


def exec_path(g):
    outgoing = {link[0]: link[1] for link in g["links"] if link[0].endswith(".then")}
    current = "entry.then"
    order = []
    seen = set()
    while current in outgoing and current not in seen:
        seen.add(current)
        target = outgoing[current]
        node, pin = target.split(".", 1)
        order.append(node)
        current = f"{node}.then"
    return order


def opening_action(flow, phase, physical_skip, latched_skip):
    """Pure contract model for the generated graph's high-level state routing."""
    request = latched_skip or (flow == "None" and physical_skip)
    if flow == "None" and request:
        return request, {0: "intro", 1: "event", 2: "hayba"}.get(phase)
    if flow == "Booting" and (physical_skip or request):
        return request, "boot"
    return request, None


class OpeningSkipSpecsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pc = load_spec("PC_Saskarta.json")
        cls.pc_loading = load_spec("PC_Saskarta.loading.json")
        cls.pc_p3 = load_spec("PC_Saskarta.p3.json")
        cls.carrier = load_spec("BPC_CarrierVision.opening_skip.json")
        cls.intro_widget = load_spec("WBP_Saskarta_Intro.graph.json")
        cls.event_card = load_spec("WBP_Saskarta_EventCard.graph.json")
        cls.hayba_card = load_spec("WBP_Saskarta_HaybaCard.graph.json")
        cls.events = json.loads((ROOT / "docs/story/story-events.json").read_text(encoding="utf-8"))

    def test_poll_routes_one_latched_request_through_cards_and_boot_only(self):
        poll = graph(self.pc, "PollOpeningSkip")
        self.assertEqual(poll["nodes"]["space"]["call"], "IsInputKeyDown")
        self.assertEqual(poll["defaults"]["space.Key"], "SpaceBar")
        self.assertEqual(poll["defaults"]["right.Key"], "Gamepad_FaceButton_Right")
        self.assertTrue(has_link(poll, "setRequested.then", "fireBranch.execute"))
        self.assertTrue(has_link(poll, "fireBranch.then", "skipFire.execute"))
        self.assertTrue(has_link(poll, "eventBranch.then", "skipEvent.execute"))
        self.assertTrue(has_link(poll, "eventBranch.else", "haybaBranch.execute"))
        self.assertTrue(has_link(poll, "haybaBranch.then", "skipHayba.execute"))
        self.assertTrue(has_link(poll, "bootBranch.then", "skipBoot.execute"))
        self.assertFalse(any(node.get("call") == "StartGame" for node in poll["nodes"].values()))
        skip_event = graph(self.intro_widget, "EventGraph")
        self.assertTrue(has_link(skip_event, "ownerPC.AsPC Saskarta", "requestOpeningSkip.self"))
        self.assertTrue(has_link(skip_event, "skipSteps.then_1", "hold.execute"))
        for card_spec in (self.event_card, self.hayba_card):
            card_event = graph(card_spec, "EventGraph")
            self.assertTrue(has_link(card_event, "ownerPC.AsPC Saskarta", "requestOpeningSkip.self"))
            self.assertTrue(has_link(card_event, "skipSteps.then_1", "skip.execute"))

        request = False
        actions = []
        for phase in range(4):
            request, action = opening_action("None", phase, physical_skip=(phase == 0), latched_skip=request)
            actions.append(action)
        request, boot_action = opening_action("Booting", 3, False, request)
        self.assertEqual(actions, ["intro", "event", "hayba", None])
        self.assertEqual(boot_action, "boot")
        self.assertEqual(opening_action("Title", 0, True, False)[1], None)

    def test_skip_waives_only_presentation_delays_not_readiness(self):
        road = graph(self.pc, "PollRoad")
        title = graph(self.pc, "PollTitle")
        self.assertTrue(has_link(road, "skipOrMin.ReturnValue", "ready.B"))
        self.assertTrue(has_link(road, "met.ReturnValue", "ready.A"))
        self.assertTrue(has_link(title, "met.ReturnValue", "metAndMin.A"))
        self.assertTrue(has_link(title, "skipOrMin.ReturnValue", "metAndMin.B"))
        self.assertTrue(has_link(title, "shown.ReturnValue", "ready.B"))

        def road_ready(readiness_met, min_time_met, skip):
            return readiness_met and (min_time_met or skip)

        def title_ready(readiness_met, phase_min, intro_revealed, loading_min, skip):
            return readiness_met and (phase_min or skip) and intro_revealed and (loading_min or skip)

        self.assertFalse(road_ready(False, False, True))
        self.assertTrue(road_ready(True, False, True))
        self.assertFalse(title_ready(False, False, True, False, True))
        self.assertFalse(title_ready(True, False, False, False, True))
        self.assertTrue(title_ready(True, False, True, False, True))

    def test_boot_skip_is_firstboot_only_one_shot_and_keeps_normal_poweron(self):
        skip = graph(self.carrier, "SkipBoot")
        self.assertTrue(has_link(skip, "firstBoot.ReturnValue", "eligible.A"))
        self.assertTrue(has_link(skip, "notApplied.ReturnValue", "eligible.B"))
        self.assertTrue(has_link(skip, "branch.then", "sequence.execute"))
        self.assertTrue(has_link(skip, "lineTimer.LineTimer", "clearLine.Handle"))
        self.assertTrue(has_link(skip, "sequence.then_3", "powerOn.execute"))
        self.assertEqual(skip["defaults"]["firstBoot.B"], "FirstBoot")
        self.assertEqual(skip["defaults"]["markApplied.bSkipBootApplied"], "true")
        self.assertFalse(any(node.get("call") in {"EnterPlaying", "ReportFlow"} for node in skip["nodes"].values()))

    def test_skip_timer_stops_at_enterplaying_and_beginintro_keeps_game_input_safe(self):
        intro = graph(self.pc, "BeginIntro")
        self.assertEqual(intro["nodes"]["uiOnly"]["call"], "SetInputMode_GameAndUIEx")
        self.assertTrue(has_link(intro, "openingSkipTimer.ReturnValue", "setOpeningSkipTimer.OpeningSkipTimer"))
        self.assertTrue(has_link(intro, "freeze.then", "ignoreMove.execute"))
        self.assertTrue(has_link(intro, "ignoreLook.then", "findCamera.execute"))
        for spec in (self.pc, self.pc_p3):
            enter = graph(spec, "EnterPlaying")
            self.assertTrue(has_link(enter, "openingSkipGet.OpeningSkipTimer", "stopOpeningSkip.Handle"))
            order = exec_path(enter)
            self.assertLess(order.index("stopOpeningSkip"), order.index("timer"))

    def test_scoped_p3_graphs_and_variables_match_full_pc_source(self):
        full_graphs = {item["graph"]: item for item in self.pc["graphs"]}
        for item in self.pc_p3["graphs"]:
            self.assertEqual(item, full_graphs[item["graph"]], item["graph"])
        self.assertEqual(self.pc_p3["variables"], self.pc["variables"])

    def test_cin01_is_skippable_first_time_and_final_handoff_is_unchanged(self):
        cin = self.events["cinematics"]["CIN_01_DIRECTIVE"]
        self.assertEqual(cin["skip"], "HoldAlways")
        self.assertEqual(cin["skip_min_s"], 1.0)
        actions = cin["final_state"]
        self.assertTrue(any(action.get("type") == "CallHook" and action.get("id") == "EnterPlaying" for action in actions))
        self.assertTrue(any(action.get("type") == "Checkpoint" and action.get("id") == "CP0_DOCK" for action in actions))

    def test_opening_control_icons_repeat_after_completed_runs_and_skip(self):
        # Controls belong to the native gameplay overlay after actual handback.
        actions = self.events["cinematics"]["CIN_01_DIRECTIVE"]["final_state"]
        controls = [a for a in actions if a.get("type") == "ShowCaption"
                    and a.get("text", "").startswith("W / RT")]
        self.assertEqual(controls, [])
        native = (ROOT / 'Plugins/SaskartaCore/Source/SaskartaCore/Private/SaskartaOnboarding.cpp').read_text()
        self.assertIn('OnCinematicFinished.AddDynamic', native)
        self.assertIn('bGameplayReady && Pawn', native)
        self.assertIn('USaskartaGameplayHintWidget', native)
        self.assertIn('AddToPlayerScreen', native)
        self.assertNotIn('UWidgetComponent', native)
        self.assertNotIn('MI_UI_RadioCRT', native)
        self.assertIn('FTSTicker::GetCoreTicker().AddTicker', native)
        self.assertIn('UGameplayStatics::IsGamePaused(World)', native)
        finish = native.split('void USaskartaOnboarding::HandleCinematicFinished', 1)[1].split('void USaskartaOnboarding::HandleRestoredRun', 1)[0]
        self.assertIn('CIN_01_DIRECTIVE', finish)
        self.assertIn('!bOpeningStarted', finish)
        self.assertIn('bGameplayReady = true', finish)
        self.assertIn('Core.Seen.Remove(SaskartaOnboarding::DriveHint)', native)
        self.assertIn('ActiveHint && ActiveHint->Id == DriveHint', native)
        self.assertIn('F.NowS - Core.ActiveSinceS >= Core.MinReadS', native)
        runner = (ROOT / 'Plugins/SaskartaCore/Source/SaskartaCore/Private/SaskartaEventRunner.cpp').read_text()
        self.assertIn('A.Text.ToString().StartsWith(TEXT("W / RT"))', runner)

    def test_progressive_controls_use_actual_actions_and_context(self):
        data = json.loads((ROOT / 'docs/story/onboarding.json').read_text())
        hints = {h['id']: h for h in data['hints']}
        self.assertEqual(hints['drive']['done_when'], ['drive_controls_used'])
        self.assertIn('charge_needs_rest', hints['recharge_intro']['when'])
        self.assertNotIn('35', hints['recharge_intro']['text'])
        self.assertIn('boost_available', hints['boost']['when'])
        self.assertNotIn('turbo_on', hints['boost']['when'])
        self.assertIn('turbo_used', hints['boost']['done_when'])
        self.assertEqual(hints['radio']['text'], 'R . RADIO')
        self.assertEqual(hints['lamps']['text'], 'F . LAMPS')
        self.assertGreaterEqual(data['gap_s'], 6)
        for name in ('boost', 'radio', 'lamps', 'recharge_intro', 'power_low', 'motor_tuning'):
            self.assertIn('drive', hints[name]['after'])

    def test_scoped_onboarding_installer_requires_exact_saved_graph_evidence(self):
        import importlib.util
        import copy
        sys.path.insert(0, str(ROOT / 'Tools/GameFlow/editor'))
        import install_gameplay_onboarding as install
        spec = json.loads((install.PACKET / 'Loading.onboarding.graph.json').read_text())
        report = {'ok': True, 'reset_graphs': True,
                  'assets': [{'asset': install.LOADING, 'compile_ok': True, 'saved': True}], 'graphs': []}
        for g in spec['graphs']:
            report['graphs'].append(dict(asset=install.LOADING, graph=g['graph'], compile_ok=True,
                nodes=len(g['nodes']), nodes_expected=len(g['nodes']), links_expected=len(g['links']),
                links_found=len(g['links']), defaults_expected=len(g['defaults']), defaults_verified=len(g['defaults'])))
        install.validate_graphs(report)
        for change in ('graph', 'saved', 'warning', 'default'):
            bad = copy.deepcopy(report)
            if change == 'graph': bad['graphs'].pop()
            elif change == 'saved': bad['assets'][0]['saved'] = False
            elif change == 'warning': bad['assets'][0]['warnings'] = ['unexpected']
            else: bad['graphs'][0]['defaults_verified'] -= 1
            with self.assertRaises(AssertionError): install.validate_graphs(bad)

    def test_loading_progress_is_current_readiness_and_only_handoff_completes(self):
        import gen_loading_specs
        widget = gen_loading_specs.loading_widget_spec()
        self.assertEqual(widget, load_spec('WBP_Saskarta_Loading.graph.json'))
        progress = graph(widget, 'SetProgress')
        self.assertLess(float(progress['defaults']['clamp.Max']), 1.0)
        self.assertNotIn('grow', progress['nodes'])
        self.assertTrue(has_link(progress, 'clamp.ReturnValue', 'setTarget.Target'))
        self.assertEqual(graph(widget, 'FadeOut')['defaults']['setTarget.Target'], '1.0')
        self.assertEqual(graph(widget, 'FadeOut')['defaults']['openTitleText.InString'], 'OPENING TITLE')

    def test_loading_named_check_count_uses_same_fraction_as_real_gate(self):
        import gen_loading_specs
        widget = gen_loading_specs.loading_widget_spec()
        status = graph(widget, 'SetReadiness')
        self.assertEqual(status['defaults']['five.B'], '5.0')
        self.assertIn('VIEW CHECKS READY', status['defaults']['suffix.B'])
        for spec in (self.pc, self.pc_loading, self.pc_p3, load_spec('PC_Saskarta.loading_presentation.json')):
            for name, flag in (('PollRoad', 'false'), ('PollTitle', 'true')):
                matches = [g for g in spec['graphs'] if g['graph'] == name]
                if not matches:
                    continue
                item = matches[0]
                self.assertTrue(has_link(item, 'fraction.ReturnValue', 'readinessText.Fraction'))
                self.assertTrue(has_link(item, 'fraction.ReturnValue', 'met.A'))
                self.assertEqual(item['defaults']['readinessText.bTitle'], flag)
        scoped = load_spec('PC_Saskarta.loading_presentation.json')
        self.assertEqual({g['graph'] for g in scoped['graphs']}, {'PollRoad', 'PollTitle'})

    def test_loading_rotates_hints_only_when_index_changes_and_clears_timer(self):
        import gen_loading_specs
        from gen_loading_presentation import HINTS
        widget = gen_loading_specs.loading_widget_spec()
        event, roll = graph(widget, 'EventGraph'), graph(widget, 'RollHint')
        self.assertTrue(has_link(event, 'destruct.then', 'clearStep.execute'))
        self.assertTrue(has_link(event, 'stepHandle.StepTimer', 'clearStep.Handle'))
        self.assertEqual(roll['defaults']['period.B'], '7.0')
        self.assertEqual(roll['defaults']['index.B'], str(len(HINTS)))
        self.assertTrue(has_link(roll, 'ifChanged.then', 'store.execute'))
        self.assertFalse(any(src == 'ifChanged.else' for src, _ in roll['links']))
        self.assertGreaterEqual(len(HINTS), 5)
        self.assertFalse(any(n.get('call') in {'Configure', 'Show'} for n in event['nodes'].values()))
        self.assertEqual(event['defaults']['hideControls.InVisibility'], 'Collapsed')
        for text in HINTS:
            self.assertFalse(any(token in text for token in ('W /', 'Tab /', 'Tap E', 'Stop to recharge', 'Look with')))

    def test_loading_tree_has_safe_scaling_and_existing_font_effect_glyphs(self):
        from gen_loading_presentation import tree, CONTROLS
        spec = tree()
        self.assertEqual(spec, load_spec('WBP_Saskarta_Loading.tree.json'))
        def walk(nodes):
            for node in nodes:
                yield node
                yield from walk(node.get('children', []))
        widgets = {n['name']: n for n in walk(spec['tree'])}
        self.assertLessEqual(len(widgets), 40)
        self.assertEqual(widgets['LoadingSafeScale']['properties']['StretchDirection'], 'DownOnly')
        self.assertTrue(widgets['LoadingHint']['properties']['AutoWrapText'])
        self.assertEqual(widgets['LoadingControls']['properties']['Visibility'], 'Collapsed')
        for name, *_ in CONTROLS:
            self.assertIn('WBP_Saskarta_KeyPrompt', widgets[name]['class'])
        for node in widgets.values():
            props = node.get('properties', {})
            for asset in (props.get('EffectMaterial'), props.get('Font', {}).get('FontObject'), props.get('Brush', {}).get('ResourceObject')):
                if asset:
                    package = asset.split('.')[0]
                    self.assertTrue((ROOT / 'Content' / (package.removeprefix('/Game/') + '.uasset')).is_file(), asset)

    def test_loading_finish_requires_every_pinned_graph_readback(self):
        import copy
        sys.path.insert(0, str(ROOT / 'Tools/GameFlow/editor'))
        import install_loading_presentation as install
        report = {'ok': True, 'reset_graphs': True, 'assets': [], 'graphs': []}
        for filename in ('WBP_Saskarta_Loading.graph.json', 'PC_Saskarta.loading_presentation.json'):
            spec = load_spec(filename)
            report['assets'].append({'asset': spec['asset'], 'compile_ok': True, 'saved': True})
            for item in spec['graphs']:
                report['graphs'].append({'asset': spec['asset'], 'graph': item['graph'], 'compile_ok': True,
                    'nodes': len(item['nodes']), 'nodes_expected': len(item['nodes']),
                    'links_expected': len(item['links']), 'links_found': len(item['links']),
                    'defaults_expected': len(item['defaults']), 'defaults_verified': len(item['defaults']), 'missing': []})
        install.validate_graph_report(report)
        absent = copy.deepcopy(report)
        absent['graphs'].pop()
        with self.assertRaisesRegex(ValueError, 'omits'):
            install.validate_graph_report(absent)
        stale = copy.deepcopy(report)
        next(g for g in stale['graphs'] if g['graph'] == 'RollHint')['defaults_verified'] -= 1
        with self.assertRaisesRegex(ValueError, 'fully verified'):
            install.validate_graph_report(stale)
        unsaved = copy.deepcopy(report)
        unsaved['assets'][1]['saved'] = False
        with self.assertRaisesRegex(ValueError, 'compile/save'):
            install.validate_graph_report(unsaved)

    def test_loading_migration_recovery_is_exact_and_keeps_original_report(self):
        import copy
        sys.path.insert(0, str(ROOT / 'Tools/GameFlow/editor'))
        import finish_loading_migration as recovery
        report = {'ok': True, 'reset_graphs': True, 'assets': [], 'graphs': []}
        for filename in ('WBP_Saskarta_Loading.graph.json', 'PC_Saskarta.loading_presentation.json'):
            spec = load_spec(filename)
            report['assets'].append({'asset': spec['asset'], 'compile_ok': True, 'saved': True,
                                    'warnings': [recovery.WARNING] if spec['asset'] == recovery.original.ASSET else []})
            for item in spec['graphs']:
                report['graphs'].append({'asset': spec['asset'], 'graph': item['graph'], 'compile_ok': True,
                    'nodes': len(item['nodes']), 'nodes_expected': len(item['nodes']),
                    'links_expected': len(item['links']), 'links_found': len(item['links']),
                    'defaults_expected': len(item['defaults']), 'defaults_verified': len(item['defaults']), 'missing': []})
        untouched = copy.deepcopy(report)
        recovery.validate_observed_report(report)
        self.assertEqual(report, untouched)
        for change in ('unknown_warning', 'current_warning', 'unsaved', 'missing_graph', 'unverified_link'):
            with self.subTest(change=change):
                bad = copy.deepcopy(report)
                if change == 'unknown_warning':
                    bad['assets'][0]['warnings'].append('another warning')
                elif change == 'current_warning':
                    bad['assets'][0]['compile_warnings'] = ['new final compile warning']
                elif change == 'unsaved':
                    bad['assets'][1]['saved'] = False
                elif change == 'missing_graph':
                    bad['graphs'].pop()
                else:
                    bad['graphs'][-1]['links_found'] -= 1
                with self.assertRaises(ValueError):
                    recovery.validate_observed_report(bad)


if __name__ == "__main__":
    unittest.main()
