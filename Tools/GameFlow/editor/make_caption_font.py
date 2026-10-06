# python_run (Hayba), LANE5: F_ArefRuqaa_Caption, the caption layer's font. The same two Aref Ruqaa faces
# as F_ArefRuqaa (Regular, Bold) plus a fallback typeface, Cormorant (FF_Cormorant, scaled 1.12), for the
# glyphs Aref Ruqaa lacks: the Saskartan macrons (a/u/e with macron) and other Latin Extended-A letters.
# F_ArefRuqaa itself is left alone (the title and the menus use it). Saves only this package.
import unreal
eal = unreal.EditorAssetLibrary
D = '/Game/SaskartaGaea/GameFlow/UI/Fonts'
NAME = 'F_ArefRuqaa_Caption'
path = D + '/' + NAME
if eal.does_asset_exist(path):
    font = eal.load_asset(path)
else:
    font = unreal.AssetToolsHelpers.get_asset_tools().create_asset(NAME, D, unreal.Font, unreal.FontFactory())
font.set_editor_property('font_cache_type', unreal.FontCacheType.RUNTIME)


def face(n, f):
    return '(Name="' + n + '",Font=(FontFaceAsset="/Script/Engine.FontFace\'' + D + '/' + f + '.' + f + '\'"))'


text = ('(DefaultTypeface=(Fonts=(' + face('Regular', 'FF_ArefRuqaa_Regular') + ',' + face('Bold', 'FF_ArefRuqaa_Bold') + ')),'
        'FallbackTypeface=(Typeface=(Fonts=(' + face('Regular', 'FF_Cormorant') + ')),ScalingFactor=1.12))')
cf = font.get_editor_property('composite_font')
cf.import_text(text)
font.set_editor_property('composite_font', cf)
print('FONT', str(font.get_editor_property('composite_font').export_text())[:700])
print('FONT saved', str(eal.save_asset(path, False)))
