"""Root-owned read-only editor probe. No spawn, simulation, mutation or save."""
import json
import unreal

PATHS = (
    '/Niagara/DefaultAssets/Templates/Systems/RadialBurst',
    '/Niagara/DefaultAssets/Templates/Systems/MinimalLightweight',
    '/Game/Vefects/Free_Fire/Shared/Particles/NS_Fire_Small_Smoke',
)

def read(obj, name):
    # Fail on the first unsupported reflected field; never conceal partial inventory.
    return obj.get_editor_property(name)

def path(obj):
    return obj.get_path_name() if obj else None

for name in PATHS:
    asset = unreal.load_asset(name)
    report = {'asset': name, 'loaded': bool(asset), 'emitters': []}
    if asset:
        report['class'] = asset.get_class().get_name()
        handles = read(asset, 'emitter_handles')
        if not isinstance(handles, dict):
            for handle in handles:
                row = {'name': str(read(handle, 'name')), 'enabled': read(handle, 'is_enabled')}
                instance = read(handle, 'versioned_instance')
                emitter = read(instance, 'emitter') if not isinstance(instance, dict) else None
                if emitter and not isinstance(emitter, dict):
                    row['emitter'] = path(emitter)
                    versions = read(emitter, 'version_data')
                    row['versions'] = []
                    if not isinstance(versions, dict):
                        for version in versions:
                            detail = {'sim_target': str(read(version, 'sim_target')),
                                      'local_space': read(version, 'local_space'), 'renderers': []}
                            renderers = read(version, 'renderer_properties')
                            if not isinstance(renderers, dict):
                                for renderer in renderers:
                                    material = read(renderer, 'material')
                                    detail['renderers'].append({
                                        'class': renderer.get_class().get_name(),
                                        'path': path(renderer),
                                        'material': material if isinstance(material, dict) else path(material),
                                        'material_user_param_binding': str(read(renderer, 'material_user_param_binding')),
                                        'sub_image_size': str(read(renderer, 'sub_image_size')),
                                        'facing_mode': str(read(renderer, 'facing_mode')),
                                        'alignment': str(read(renderer, 'alignment'))})
                            else:
                                detail['renderer_error'] = renderers
                            row['versions'].append(detail)
                    else:
                        row['version_error'] = versions
                else:
                    stateless = read(handle, 'stateless_emitter')
                    row['stateless'] = stateless if isinstance(stateless, dict) else path(stateless)
                report['emitters'].append(row)
        else:
            report['handle_error'] = handles
    print('SIX_WAY_NIAGARA_INVENTORY ' + json.dumps(report, sort_keys=True))
