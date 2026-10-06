"""Scoped startup presentation: real readiness counts, field notes and existing glyphs.

Run offline to update only Loading and the two PC readiness-poll graphs. The
native readiness gate, timeout policy, intro order and saved settings are unchanged.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
SPECS = HERE / 'specs'
UI = '/Game/SaskartaGaea/GameFlow/UI'
ASSET = UI + '/WBP_Saskarta_Loading'
KML = '/Script/Engine.KismetMathLibrary'
KSL = '/Script/Engine.KismetSystemLibrary'
KSTR = '/Script/Engine.KismetStringLibrary'
KTXT = '/Script/Engine.KismetTextLibrary'
GPS = '/Script/Engine.GameplayStatics'
WIDGET = '/Script/UMG.Widget'
TEXT = '/Script/UMG.TextBlock'
KEYPROMPT = UI + '/WBP_Saskarta_KeyPrompt.WBP_Saskarta_KeyPrompt_C'
MONO = UI + '/Fonts/Font_Terminal.Font_Terminal'
HINTS = (
    'Beyond the window, the road waits under a sleeping sky.',
    'Every light on the ridge was once a place somebody called home.',
    'The carrier has crossed this dust before. The voices are new.',
    'Somewhere beyond the hills, a transmitter is still warm.',
    'The radio carries voices from far away. Give them time to reach you.',
    'The night is long. There is still someone listening.',
)
CONTROLS = (
    ('LoadingDrive', 'Key_W', 'None', 'Pad_RT', 'Drive'),
    ('LoadingSteer', 'Key_A', 'Key_D', 'Pad_LStick', 'Steer'),
    ('LoadingLook', 'Mouse_Move', 'None', 'Pad_RStick', 'Look'),
)


def call(fn, cls=None):
    return {'call': fn, **({'class': cls} if cls else {})}


def find(spec, name):
    return next(g for g in spec['graphs'] if g['graph'] == name)


def text_set(nodes, links, prefix, widget, source):
    nodes[prefix + 'Widget'] = {'get': widget}
    nodes[prefix + 'Text'] = call('Conv_StringToText', KTXT)
    nodes[prefix + 'Set'] = call('SetText', TEXT)
    links.extend([[source, prefix + 'Text.InString'],
                  [prefix + 'Text.ReturnValue', prefix + 'Set.InText'],
                  [prefix + 'Widget.' + widget, prefix + 'Set.self']])
    return prefix + 'Set'


def enhance_widget(spec):
    """Called by the canonical loading generator, so future regeneration retains this."""
    spec = copy.deepcopy(spec)
    spec['description'] += ' Named road/title readiness checks; no byte/time percentage. Atmospheric field notes rotate every seven seconds. Controls are taught only after gameplay handback.'
    spec['variables'] += [
        {'name': 'HintEpoch', 'type': 'float', 'default': '0.0'},
        {'name': 'HintIndex', 'type': 'int', 'default': '-1'},
        {'name': 'CrankTarget', 'type': 'float', 'default': '0.0'},
        {'name': 'CrankShown', 'type': 'float', 'default': '0.0'},
        {'name': 'SceneEpoch', 'type': 'float', 'default': '0.0'},
    ]
    spec['functions'] += [
        {'name': 'SetReadiness', 'pure': False, 'inputs': [
            {'name': 'bTitle', 'type': 'bool'}, {'name': 'Fraction', 'type': 'float'}], 'outputs': []},
        {'name': 'RollHint', 'pure': False, 'inputs': [], 'outputs': []},
        {'name': 'BeginPresentation', 'pure': False, 'inputs': [], 'outputs': []},
    ]
    # These are current readiness conditions, not irreversible downloaded bytes.
    progress = find(spec, 'SetProgress')
    progress['nodes'].pop('target')
    progress['nodes'].pop('grow')
    progress['links'] = [['entry.then', 'setTarget.execute'], ['entry.Progress', 'clamp.Value'],
                         ['clamp.ReturnValue', 'setTarget.Target']]
    progress['defaults']['clamp.Max'] = '1.0'

    event = find(spec, 'EventGraph')
    n, links, d = event['nodes'], event['links'], event['defaults']
    links.remove(['construct.then', 'timer.execute'])
    n.update({'now': call('GetTimeSeconds', GPS), 'epoch': {'set': 'HintEpoch'},
              'firstHint': call('RollHint'), 'destruct': {'event': 'Destruct'},
              'stepHandle': {'get': 'StepTimer'}, 'clearStep': call('K2_ClearAndInvalidateTimerHandle', KSL)})
    links += [['construct.then', 'epoch.execute'], ['now.ReturnValue', 'epoch.HintEpoch'],
              ['epoch.then', 'firstHint.execute'], ['destruct.then', 'clearStep.execute'],
              ['stepHandle.StepTimer', 'clearStep.Handle']]
    # Hide the retained old row as the first Construct action too, so an already
    # installed tree is safe without destructive rebuilding or deleting glyphs.
    links.remove(['construct.then', 'epoch.execute'])
    tail = 'construct'
    for i, (name, *_) in enumerate(CONTROLS):
        hide = 'hideControls' if i == 0 else 'hideControls' + str(i)
        n[name] = {'get': name}
        n[hide] = call('SetVisibility', WIDGET)
        links += [[tail + '.then', hide + '.execute'], [name + '.' + name, hide + '.self']]
        d[hide + '.InVisibility'] = 'Collapsed'
        tail = hide
    links += [[tail + '.then', 'epoch.execute'], ['firstHint.then', 'timer.execute']]

    step = find(spec, 'Step')
    step['nodes']['rollHint'] = call('RollHint')
    step['links'].remove(['setGlow.then', 'ifFading.execute'])
    step['links'] += [['setGlow.then', 'rollHint.execute'], ['rollHint.then', 'ifFading.execute']]
    step['nodes'].update({
        'crankShown': {'get': 'CrankShown'}, 'crankTarget': {'get': 'CrankTarget'},
        'crankEase': call('FInterpTo', KML), 'setCrankShown': {'set': 'CrankShown'},
        'crankWidget': {'get': 'LoadingCrank'},
        'presentCrank': call('PresentLoading', '/Script/SaskartaCore.SaskartaMotorDiagram')})
    step['links'].remove(['setScale.then', 'setGlow.execute'])
    step['links'] += [
        ['setScale.then', 'setCrankShown.execute'], ['crankShown.CrankShown', 'crankEase.Current'],
        ['crankTarget.CrankTarget', 'crankEase.Target'], ['dt.StepInterval', 'crankEase.DeltaTime'],
        ['rate.FillRate', 'crankEase.InterpSpeed'], ['crankEase.ReturnValue', 'setCrankShown.CrankShown'],
        ['setCrankShown.then', 'presentCrank.execute'], ['crankWidget.LoadingCrank', 'presentCrank.self'],
        ['crankEase.ReturnValue', 'presentCrank.Readiness'], ['presentCrank.then', 'setGlow.execute']]
    # Let the carrier play first, then reveal the already staged Keeper capture.
    # HintEpoch is set on Construct, so this timing belongs to this loading visit.
    scene_nodes = {
        'sceneNow': call('GetTimeSeconds', GPS), 'sceneEpoch': {'get': 'SceneEpoch'},
        'sceneElapsed': call('Subtract_DoubleDouble', KML),
        'sceneAfterCarrier': call('Subtract_DoubleDouble', KML),
        'fadeFraction': call('Divide_DoubleDouble', KML),
        'keeperAlpha': call('FClamp', KML),
        'carrierAlpha': call('Subtract_DoubleDouble', KML),
        'keeperImage': {'get': 'TravellerPointCloud'},
        'carrierImage': {'get': 'LoadingCar'},
        'showKeeper': call('SetRenderOpacity', WIDGET),
        'showCarrier': call('SetRenderOpacity', WIDGET),
    }
    collisions = set(scene_nodes) & set(step['nodes'])
    assert not collisions, f'Keeper crossfade Step node collisions: {sorted(collisions)}'
    step['nodes'].update(scene_nodes)
    step['links'].remove(['presentCrank.then', 'setGlow.execute'])
    step['links'] += [
        ['sceneNow.ReturnValue', 'sceneElapsed.A'], ['sceneEpoch.SceneEpoch', 'sceneElapsed.B'],
        ['sceneElapsed.ReturnValue', 'sceneAfterCarrier.A'], ['sceneAfterCarrier.ReturnValue', 'fadeFraction.A'],
        ['fadeFraction.ReturnValue', 'keeperAlpha.Value'],
        ['keeperAlpha.ReturnValue', 'carrierAlpha.B'],
        ['presentCrank.then', 'showKeeper.execute'],
        ['keeperImage.TravellerPointCloud', 'showKeeper.self'],
        ['keeperAlpha.ReturnValue', 'showKeeper.InOpacity'],
        ['showKeeper.then', 'showCarrier.execute'],
        ['carrierImage.LoadingCar', 'showCarrier.self'],
        ['carrierAlpha.ReturnValue', 'showCarrier.InOpacity'],
        ['showCarrier.then', 'setGlow.execute'],
    ]
    step['defaults'].update({'sceneAfterCarrier.B': '1.5', 'fadeFraction.B': '0.75',
                             'keeperAlpha.Min': '0.0', 'keeperAlpha.Max': '1.0',
                             'carrierAlpha.A': '1.0'})
    missing_step_nodes = sorted({pin.split('.', 1)[0] for edge in step['links'] for pin in edge}
                                - set(step['nodes']))
    assert not missing_step_nodes, f'Loading Step links reference missing nodes: {missing_step_nodes}'
    spec['graphs'].append({'graph': 'BeginPresentation', 'nodes': {
        'entry': {'entry': True}, 'now': call('GetTimeSeconds', GPS),
        'epoch': {'set': 'SceneEpoch'}, 'keeper': {'get': 'TravellerPointCloud'},
        'carrier': {'get': 'LoadingCar'},
        'resetKeeper': call('SetRenderOpacity', WIDGET),
        'resetCarrier': call('SetRenderOpacity', WIDGET),
    }, 'links': [
        ['entry.then', 'epoch.execute'], ['now.ReturnValue', 'epoch.SceneEpoch'],
        ['epoch.then', 'resetKeeper.execute'],
        ['keeper.TravellerPointCloud', 'resetKeeper.self'],
        ['resetKeeper.then', 'resetCarrier.execute'],
        ['carrier.LoadingCar', 'resetCarrier.self'],
    ], 'defaults': {'resetKeeper.InOpacity': '0.0', 'resetCarrier.InOpacity': '1.0'}})
    presentation = find(spec, 'BeginPresentation')
    missing_presentation_nodes = sorted({pin.split('.', 1)[0] for edge in presentation['links'] for pin in edge}
                                        - set(presentation['nodes']))
    assert not missing_presentation_nodes, f'BeginPresentation links reference missing nodes: {missing_presentation_nodes}'
    for edge in (['entry.then', 'epoch.execute'], ['epoch.then', 'resetKeeper.execute'],
                 ['resetKeeper.then', 'resetCarrier.execute']):
        assert presentation['links'].count(edge) == 1, f'BeginPresentation execution edge missing/duplicated: {edge}'
    # Warm the Keeper before the car fades, including editors using an older
    # native capture guard. Release the hold when UMG removes the loading screen.
    guard_class = '/Script/SaskartaCore.SaskartaCaptureGuard'
    presentation['nodes'].update({
        'worldSelf': {'self': True}, 'captureGuard': call('GetCaptureGuard', guard_class),
        'warmKeeper': call('SetLoadingHold', guard_class)})
    presentation['links'].remove(['entry.then', 'epoch.execute'])
    presentation['links'] += [
        ['worldSelf.self', 'captureGuard.WorldContext'],
        ['captureGuard.ReturnValue', 'warmKeeper.self'],
        ['entry.then', 'warmKeeper.execute'], ['warmKeeper.then', 'epoch.execute']]
    presentation['defaults'].update({'warmKeeper.Reason': 'LoadingPresentation', 'warmKeeper.bHold': 'true'})
    event['nodes'].update({
        'captureGuardSelf': {'self': True}, 'captureGuard': call('GetCaptureGuard', guard_class),
        'releaseKeeper': call('SetLoadingHold', guard_class)})
    event['links'] += [
        ['captureGuardSelf.self', 'captureGuard.WorldContext'],
        ['captureGuard.ReturnValue', 'releaseKeeper.self'],
        ['clearStep.then', 'releaseKeeper.execute']]
    event['defaults'].update({'releaseKeeper.Reason': 'LoadingPresentation', 'releaseKeeper.bHold': 'false'})
    fade = find(spec, 'FadeOut')
    # A timeout/transition cannot fabricate completed readiness.
    fade['nodes'].pop('setTarget')
    fade['links'].remove(['entry.then', 'setTarget.execute'])
    fade['links'].remove(['setTarget.then', 'setFading.execute'])
    fade['links'].insert(0, ['entry.then', 'setFading.execute'])
    fade['defaults'].pop('setTarget.Target')
    fade['nodes'].update({'stage': {'get': 'PreparationStage'}, 'openTitle': call('SetText', TEXT),
                          'openTitleText': call('Conv_StringToText', KTXT)})
    fade['links'] += [['setDur.then', 'openTitle.execute'], ['stage.PreparationStage', 'openTitle.self'],
                      ['openTitleText.ReturnValue', 'openTitle.InText']]
    fade['defaults']['openTitleText.InString'] = 'OPENING TITLE'

    n = {'entry': {'entry': True}, 'stageChoice': call('SelectString', KML),
         'clamp': call('FClamp', KML), 'five': call('Multiply_DoubleDouble', KML),
         'count': call('Round', KML), 'number': call('Conv_IntToString', KSTR),
         'suffix': call('Concat_StrStr', KSTR)}
    links = [['entry.bTitle', 'stageChoice.bPickA'], ['entry.Fraction', 'clamp.Value'],
             ['clamp.ReturnValue', 'five.A'], ['five.ReturnValue', 'count.A'],
             ['count.ReturnValue', 'number.InInt'], ['number.ReturnValue', 'suffix.A']]
    stage = text_set(n, links, 'stage', 'PreparationStage', 'stageChoice.ReturnValue')
    count = text_set(n, links, 'checks', 'ReadinessChecks', 'suffix.ReturnValue')
    n['setCrankTarget'] = {'set': 'CrankTarget'}
    links += [['entry.then', 'setCrankTarget.execute'], ['clamp.ReturnValue', 'setCrankTarget.CrankTarget'],
              ['setCrankTarget.then', stage + '.execute'], [stage + '.then', count + '.execute']]
    spec['graphs'].append({'graph': 'SetReadiness', 'nodes': n, 'links': links, 'defaults': {
        'stageChoice.A': 'ESTABLISHING SIGNAL', 'stageChoice.B': 'CHARGING CARRIER',
        'clamp.Min': '0.0', 'clamp.Max': '1.0', 'five.B': '5.0', 'suffix.B': ' / 5 VIEW CHECKS READY'}})

    n = {'entry': {'entry': True}, 'now': call('GetTimeSeconds', GPS), 'epoch': {'get': 'HintEpoch'},
         'elapsed': call('Subtract_DoubleDouble', KML), 'period': call('Divide_DoubleDouble', KML),
         'floor': call('FTrunc', KML), 'index': call('Percent_IntInt', KML),
         'old': {'get': 'HintIndex'}, 'changed': call('NotEqual_IntInt', KML),
         'ifChanged': {'branch': True}, 'store': {'set': 'HintIndex'}}
    links = [['entry.then', 'ifChanged.execute'], ['now.ReturnValue', 'elapsed.A'], ['epoch.HintEpoch', 'elapsed.B'],
             ['elapsed.ReturnValue', 'period.A'], ['period.ReturnValue', 'floor.A'], ['floor.ReturnValue', 'index.A'],
             ['index.ReturnValue', 'changed.A'], ['old.HintIndex', 'changed.B'], ['changed.ReturnValue', 'ifChanged.Condition'],
             ['ifChanged.then', 'store.execute'], ['index.ReturnValue', 'store.HintIndex']]
    d = {'period.B': '7.0', 'index.B': str(len(HINTS))}
    for i, hint in enumerate(HINTS):
        n[f'is{i}'] = call('EqualEqual_IntInt', KML)
        n[f'pick{i}'] = call('SelectString', KML)
        links += [['index.ReturnValue', f'is{i}.A'], [f'is{i}.ReturnValue', f'pick{i}.bPickA']]
        d[f'is{i}.B'], d[f'pick{i}.A'] = str(i), hint
        if i:
            links += [[f'pick{i-1}.ReturnValue', f'pick{i}.B']]
        else:
            d['pick0.B'] = HINTS[0]
    setter = text_set(n, links, 'hint', 'LoadingHint', f'pick{len(HINTS)-1}.ReturnValue')
    links += [['store.then', setter + '.execute']]
    spec['graphs'].append({'graph': 'RollHint', 'nodes': n, 'links': links, 'defaults': d})
    return spec


def patch_poll(graph):
    """Only adds status alongside existing progress; every readiness gate is preserved."""
    graph = copy.deepcopy(graph)
    if graph['graph'] == 'PollTitle' and 'presentationSafe' not in graph['nodes']:
        graph['nodes'].update({
            'presentationPhase': {'get': 'CardPhase'},
            'presentationShown': call('GreaterEqual_IntInt', KML),
            'presentationElapsed': call('GreaterEqual_DoubleDouble', KML),
            'presentationReady': call('BooleanAND', KML),
            'presentationSafe': call('BooleanAND', KML)})
        graph['links'].remove(['go.ReturnValue', 'ifGo.Condition'])
        graph['links'] += [
            ['presentationPhase.CardPhase', 'presentationShown.A'],
            ['sinceReveal.ReturnValue', 'presentationElapsed.A'],
            ['presentationShown.ReturnValue', 'presentationReady.A'],
            ['presentationElapsed.ReturnValue', 'presentationReady.B'],
            ['presentationReady.ReturnValue', 'presentationSafe.B'],
            ['go.ReturnValue', 'presentationSafe.A'], ['presentationSafe.ReturnValue', 'ifGo.Condition']]
        graph['defaults'].update({'presentationShown.B': '3', 'presentationElapsed.B': '3.5'})
    if 'readinessText' in graph['nodes']:
        return graph
    end = 'ifDone' if graph['graph'] == 'PollRoad' else 'ifGo'
    graph['nodes']['readinessText'] = call('SetReadiness', ASSET + '.WBP_Saskarta_Loading_C')
    graph['links'].remove(['progress.then', end + '.execute'])
    graph['links'] += [['progress.then', 'readinessText.execute'], ['loading.LoadingWidget', 'readinessText.self'],
                       ['fraction.ReturnValue', 'readinessText.Fraction'], ['readinessText.then', end + '.execute']]
    graph['defaults']['readinessText.bTitle'] = 'false' if graph['graph'] == 'PollRoad' else 'true'
    return graph


def tree():
    amber, ivory = [0.92, 0.50, 0.15, 1], [0.90, 0.82, 0.68, 1]
    def txt(name, value, size, color=ivory, **extra):
        return {'class': 'TextBlock', 'name': name, 'properties': {
            'Text': value, 'Font': {'FontObject': MONO, 'Size': size},
            'ColorAndOpacity': {'SpecifiedColor': color},
            'ShadowColorAndOpacity': [0, 0, 0, 0.9], 'ShadowOffset': {'X': 1, 'Y': 2}, **extra}}
    content = {'class': 'VerticalBox', 'name': 'LoadingContent', 'children': [
        txt('LoadingChannel', '', 14, amber, Visibility='Collapsed'),
        {**txt('PreparationStage', 'CHARGING CARRIER', 18), 'slot_props': {'padding': [0, 0, 0, 10]}},
        {'class': 'SizeBox', 'name': 'LoadingTrackBox', 'properties': {'Visibility': 'Collapsed', 'bOverride_HeightOverride': True, 'HeightOverride': 3},
         'children': [{'class': 'Overlay', 'name': 'LoadingTrack', 'children': [
             {'class': 'Border', 'name': 'LoadingTrackBack', 'properties': {'BrushColor': [0.11, 0.065, 0.025, 0.25]}},
             {'class': 'Border', 'name': 'ProgressFill', 'properties': {'BrushColor': amber,
              'RenderTransformPivot': {'X': 0, 'Y': 0.5}, 'RenderTransform': {'Scale': {'X': 0, 'Y': 1}}},
              'slot_props': {'horizontal_alignment': 'Fill', 'vertical_alignment': 'Fill'}},
         ]}]},
        {**txt('ReadinessChecks', '', 14, amber, Visibility='Collapsed'), 'slot_props': {'padding': [0, 8, 0, 18]}},
        txt('LoadingNotesLabel', '', 14, amber, Visibility='Collapsed'),
        {'class': 'SizeBox', 'name': 'LoadingHintBox', 'properties': {'bOverride_HeightOverride': True, 'HeightOverride': 72},
         'children': [txt('LoadingHint', HINTS[0], 18, AutoWrapText=True, WrapTextAt=680)]},
        {'class': 'HorizontalBox', 'name': 'LoadingControls', 'properties': {'Visibility': 'Collapsed'}, 'children': [
            {'class': KEYPROMPT, 'name': name, 'slot_props': {'padding': [0, 0, 40, 0], 'vertical_alignment': 'Center'}}
            for name, *_ in CONTROLS]},
    ]}
    panel = {'class': 'Border', 'name': 'LoadingFrame', 'properties': {'BrushColor': [0, 0, 0, 0],
             'Padding': {'Left': 0, 'Top': 0, 'Right': 0, 'Bottom': 0}}, 'children': [content]}
    scaled = {'class': 'ScaleBox', 'name': 'LoadingSafeScale', 'properties': {'Stretch': 'ScaleToFit', 'StretchDirection': 'DownOnly'},
        'children': [{'class': 'SizeBox', 'name': 'LoadingDesignSize', 'properties': {
            'bOverride_WidthOverride': True, 'WidthOverride': 720, 'bOverride_HeightOverride': True, 'HeightOverride': 100},
        'children': [{'class': 'Overlay', 'name': 'LoadingScreen', 'properties': {},
            'children': [panel]}]}]}
    return {'asset': ASSET, 'tree': [
        {'class': 'Border', 'name': 'LoadingBackdrop', 'properties': {'BrushColor': [0, 0, 0, 1]}},
        {'class': 'Image', 'name': 'EmberGlow', 'properties': {'Brush': {
            'ResourceObject': UI + '/Textures/T_UI_EmberGlow.T_UI_EmberGlow', 'DrawAs': 'Image'},
            'ColorAndOpacity': [0, 0, 0, 0], 'Visibility': 'Collapsed'}}, scaled,
        {'class': 'ScaleBox', 'name': 'LoadingCrankSafeScale', 'properties': {'Stretch': 'ScaleToFit', 'StretchDirection': 'DownOnly'},
         'children': [{'class': 'SizeBox', 'name': 'LoadingCrankDesignSize', 'properties': {
             'bOverride_WidthOverride': True, 'WidthOverride': 720, 'bOverride_HeightOverride': True, 'HeightOverride': 164},
             'children': [{'class': '/Script/SaskartaCore.SaskartaMotorDiagram', 'name': 'LoadingCrank',
                 'properties': {'bLoadingPresentation': True, 'Visibility': 'HitTestInvisible'}}]}]},
        {'class': 'ScaleBox', 'name': 'LoadingCarSafeScale', 'properties': {'Stretch': 'ScaleToFit', 'StretchDirection': 'Both'},
         'children': [{'class': 'SizeBox', 'name': 'LoadingCarDesignSize', 'properties': {
             'bOverride_WidthOverride': True, 'WidthOverride': 800, 'bOverride_HeightOverride': True, 'HeightOverride': 450},
             'children': [{'class': 'Image', 'name': 'LoadingCar', 'properties': {'Brush': {
                 'ResourceObject': UI + '/Materials/M_LoadingCarrierSplat.M_LoadingCarrierSplat', 'DrawAs': 'Image'}}}]}]},
        {'class': 'ScaleBox', 'name': 'LoadingKeeperSafeScale', 'properties': {'Stretch': 'ScaleToFit', 'StretchDirection': 'Both'},
         'children': [{'class': 'SizeBox', 'name': 'LoadingKeeperDesignSize', 'properties': {
             'bOverride_WidthOverride': True, 'WidthOverride': 540, 'bOverride_HeightOverride': True, 'HeightOverride': 540},
             'children': [{'class': 'Image', 'name': 'TravellerPointCloud', 'properties': {
                 'Brush': {'ResourceObject': '/Game/SaskartaGaea/Characters/Traveller/PointCloud/M_UI_KeeperPointCloud.M_UI_KeeperPointCloud', 'DrawAs': 'Image'},
                 'RenderOpacity': 0.0}}]}]}],
        'slots': {
            'LoadingBackdrop': {'anchors': [0, 0, 1, 1], 'position': [0, 0], 'size': [0, 0], 'z_order': 0},
            'EmberGlow': {'anchors': [0, 0, 1, 1], 'position': [0, 0], 'size': [0, 0], 'z_order': 1},
            'LoadingSafeScale': {'anchors': [0.08, 0.82, 0.92, 0.98], 'alignment': [0, 0], 'position': [0, 0], 'size': [0, 0], 'z_order': 3},
            'LoadingCrankSafeScale': {'anchors': [0.08, 0.60, 0.92, 0.81], 'alignment': [0, 0], 'position': [0, 0], 'size': [0, 0], 'z_order': 3},
            'LoadingCarSafeScale': {'anchors': [0.15, 0.05, 0.85, 0.56], 'position': [0, 0], 'size': [0, 0], 'z_order': 2},
            'LoadingKeeperSafeScale': {'anchors': [0.31, 0.05, 0.69, 0.56], 'position': [0, 0], 'size': [0, 0], 'z_order': 2}},
        'variables': ['LoadingCrank', 'ProgressFill', 'EmberGlow', 'PreparationStage', 'ReadinessChecks', 'LoadingHint',
                      'LoadingCar', 'TravellerPointCloud'] + [r[0] for r in CONTROLS]}


def main():
    import gen_loading_specs as base
    base.dump(SPECS / 'WBP_Saskarta_Loading.graph.json', base.loading_widget_spec())
    base.dump(SPECS / 'WBP_Saskarta_Loading.tree.json', tree())
    full_path = SPECS / 'PC_Saskarta.json'
    full = json.loads(full_path.read_text(encoding='utf-8'))
    changed = {'PollRoad', 'PollTitle'}
    full['graphs'] = [patch_poll(g) if g['graph'] in changed else g for g in full['graphs']]
    base.dump(full_path, full)
    scoped = {'asset': full['asset'], 'description': 'Scoped startup readiness text only; all native readiness gates, timeouts and intro flow preserved.',
              'functions': [f for f in full['functions'] if f['name'] in changed],
              'graphs': [g for g in full['graphs'] if g['graph'] in changed]}
    base.dump(SPECS / 'PC_Saskarta.loading_presentation.json', scoped)
    for filename in ('PC_Saskarta.loading.json', 'PC_Saskarta.p3.json'):
        path = SPECS / filename
        other = json.loads(path.read_text(encoding='utf-8'))
        other['graphs'] = [patch_poll(g) if g['graph'] in changed else g for g in other['graphs']]
        # Continue added two PC variables after the last P3 generation. Keep the
        # existing full-variable mirror synchronized without rebuilding its graphs.
        other['variables'] = full['variables']
        base.dump(path, other)


if __name__ == '__main__':
    main()
