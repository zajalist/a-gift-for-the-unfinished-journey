# Editable gameplay UMG layouts

Run `python Tools/UIRuntime/install_runtime_layouts.py` offline to prepare the three JSON packets under `Tools/UIRuntime/specs`. The root editor operator installs them through Hayba's native UMG tools, with an exclusive editor lease and PIE stopped. The native code must be rebuilt before the next play session.

The installer creates three new Widget Blueprints under `/Game/SaskartaGaea/GameFlow/UI`:

| Widget Blueprint | Native parent | UMG Designer content |
| --- | --- | --- |
| WBP_Saskarta_Power | SaskartaPowerWidget | Transparent battery inspection, seven fractional charge bars, warnings, speed and altitude labels, two custom telemetry graph widgets |
| WBP_Saskarta_Motor | SaskartaMotorResonanceWidget | Transparent motor screen, editable position and scale, native schematic UMG widget in a retainer with retained rendering disabled |
| WBP_Saskarta_GameplayHints | SaskartaGameplayHintWidget | Transparent tutorial row, seven editable caption groups, two existing control glyph image slots per group |

Native initialization binds the existing named widgets instead of replacing the designer tree. Charge, gaze gating, inscription suppression, crank timing, input scoring, and progressive hint timing remain native. No Blueprint Tick or polling property bindings are added. Widget classes are loaded once at world startup and retained across garbage collection.

Designer edits can change anchors, spacing, fonts, colors, icon sizes, and the motor scale. Preserve the named widgets and their types: the installer and native binding checks report missing or mistyped controls. At runtime, tutorial content uses the authored caption groups in order: two icons followed by a caption. Initial keyboard guidance therefore reads W/S DRIVE, A/D STEER, and MOUSE LOOK.

For each packet, call `ui_create_widget` with its `create` object; require the returned actual parent to equal `expected_parent`. Existing assets must first be queried and must not be blindly recreated. Call `ui_build_tree` with `widget_blueprint_path=asset` and `tree=tree`. Apply each entry in `slots` with `ui_set_widget_properties`; convert its four `anchors` values into two-value `anchors_min` and `anchors_max` fields. Require no rejected properties, slot keys, or build warnings. Call `ui_compile_widget`, require zero errors and warnings, then `ui_save_widget` and require actual save success. Finally call `ui_query` with `path=asset`, `flatten=true`, and `include_slot=true`; compare its actual `parent_class` and each name/class in `matches` with the packet's `expected_parent` and `expected_widgets`.

Direct Unreal Python cannot read or set `WidgetTree` and `RootWidget`: UE's `PropertyAccessUtil` rejects properties without Edit or BlueprintVisible flags. The native Hayba tools operate on the actual UMG editor tree and support custom native widget classes through their `/Script/SaskartaCore` paths. The old direct Python construction route has been replaced with these native packets.

Installation and runtime acceptance are separate from the source freeze receipt. This packet does not claim the assets are already installed or accepted in play.
