import unreal

sub = unreal.get_editor_subsystem(unreal.WorldPartitionEditorSubsystem)
print('WP_API', ','.join(name for name in dir(sub)
      if any(term in name.lower() for term in ('load', 'region', 'cell', 'actor', 'camera'))))
