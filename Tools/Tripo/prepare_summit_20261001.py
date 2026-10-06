"""Stage four scoped summit asset imports using the established Tripo importer.

Offline only. The sole editor lane runs the emitted chunks after review. Reuses
the existing shared material without rebuilding it; does not place level actors.
"""
from pathlib import Path
import hashlib
import json

import import_tripo as importer
import tripo_ingest as ti

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'Saved/Tripo/20261001/import_packet'
SELECTION = {
    'S26_fence_panel':'s26_fence_panel',
    'S26_gate_open_clear':'s26_gate_open',
    'S26_transmitter_cabinet':'s26_transmitter_cabinet',
    'S26_radio_station_shell':'s26_radio_station',
}
GUARD = '''import unreal
if unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world() is not None:
    raise RuntimeError('Stop PIE before importing summit assets')
'''


def prepare():
    importer.STAGE = OUT / 'assets'
    sources = json.loads((ROOT/'SourceArt/Tripo/20261001/import_manifest.json').read_text())
    report = []
    for source in sources:
        key = source['key']
        if key not in SELECTION:
            continue
        relative = source['runtime_file']
        if key == 'S26_radio_station_shell':
            relative = 'SourceArt/Tripo/20261001/S26_radio_station_shell/S26_radio_station_shell_open_window_ue.glb'
        stats = ti.glb_stats(ROOT/relative)
        row = dict(key=key,t2=SELECTION[key],import_file=relative,
                   import_size_cm_wdh=stats['native_size_cm_wdh'],tris=stats['tris'])
        importer.prepare(row)
        stage = importer.STAGE/key
        staged = ti.glb_stats(stage/('SM_T2_'+row['t2']+'.glb'))
        assert staged['tris']==stats['tris']
        assert staged['native_size_cm_wdh']==stats['native_size_cm_wdh']
        assert len(list(stage.glob('T_T2_*')))==3
        scripts=[]
        for index,step in enumerate(('mesh','textures','finish','verify')):
            code=GUARD+importer.script(step,row)
            compile(code,key+step,'exec')
            path=OUT/'scripts'/key/f'{index:02d}_{step}.py'
            path.parent.mkdir(parents=True,exist_ok=True)
            path.write_text(code)
            scripts.append(dict(path=str(path.relative_to(ROOT)),sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
        report.append(dict(**row,source_sha256=hashlib.sha256((ROOT/relative).read_bytes()).hexdigest(),scripts=scripts))
    assert len(report)==4
    (OUT/'manifest.json').write_text(json.dumps(dict(
        state='offline_prepared_not_imported',
        shared_master=importer.DEST+'/Materials/M_T2_Master',
        note='Existing shared master required. No master modification or level placement included.',
        models=report),indent=2)+'\n')
    print('SUMMIT_PACKET_READY',len(report),'models',sum(len(r['scripts']) for r in report),'scripts',OUT)


if __name__=='__main__':
    prepare()
