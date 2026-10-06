import json
import unreal

seq = unreal.load_asset('/Game/SaskartaGaea/GameFlow/Cinematics/LS_CIN_19_Hatch_SideSupportedReviewV9')
assert seq
binding = [item for item in seq.get_bindings() if str(item.get_display_name()) == 'Samyor_Hatch'][0]
tracks = [track for track in binding.get_tracks() if isinstance(track, unreal.MovieScene3DTransformTrack)]
assert len(tracks) == 1
sections = tracks[0].get_sections()
assert len(sections) == 1
channels = sections[0].get_all_channels()
rate = seq.get_tick_resolution()
print('BODY_TRANSFORM_TRACK ' + json.dumps({
    'sections': len(sections), 'channels': len(channels),
    'tick_rate': [rate.numerator, rate.denominator],
    'key_counts': [channel.get_num_keys() for channel in channels[:6]],
    'z_values': [float(key.get_value()) for key in channels[2].get_keys()][::20],
}, separators=(',', ':')))
