import unreal

klass = unreal.LevelSequenceEditorBlueprintLibrary
print('SEQUENCER_API', klass,
      ','.join(method for method in dir(klass) if any(term in method.lower()
      for term in ('open', 'time', 'frame', 'current', 'sequence', 'refresh'))))
print('SET_TIME_DOC', klass.set_current_time.__doc__)
print('OPEN_DOC', klass.open_level_sequence.__doc__)
print('BIND_METHODS', ','.join(method for method in dir(klass)
      if any(term in method.lower() for term in ('bound', 'camera', 'play', 'lock', 'editor'))))
print('BOUND_DOC', klass.get_bound_objects.__doc__)
print('CAMERA_DOC', klass.set_lock_camera_cut_to_viewport.__doc__)
