import unreal

print('PARAMS_DOC', str(unreal.MovieSceneSequencePlaybackParams.__doc__))
print('PARAMS_PROPS', str(unreal.MovieSceneSequencePlaybackParams().get_editor_property('position_type')))
print('FRAME_TIME_DOC', str(unreal.FrameTime.__doc__))
