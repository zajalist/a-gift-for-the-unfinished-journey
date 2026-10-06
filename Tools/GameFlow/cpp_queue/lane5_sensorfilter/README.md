# Queued C++ (LANE5): the Sensor filter setting (LANE4's M_PP_SensorCRT on PPV_Saskarta_Sensor)

Not built. Apply at the next closed-editor build, then rebuild WBP_Saskarta_Settings (its "Sensor filter" row,
already in gen_settings_specs.mjs, writes `SensorFilter` and reads `saskarta.sensorfilter`).

1. `Public/SaskartaGameUserSettings.h`, next to CameraShake:
   ```cpp
   /** The carrier camera's sensor look (M_PP_SensorCRT): 0 Off, 1 Low, 2 Medium (default), 3 High. */
   UPROPERTY(Config, BlueprintReadWrite, Category = "Saskarta|Camera")
   int32 SensorFilter = 2;
   ```
2. `Private/SaskartaGameUserSettings.cpp`, in ComputeCVars next to saskarta.camerashake:
   ```cpp
   C.Add(TEXT("saskarta.sensorfilter"), I(FMath::Clamp(S->SensorFilter, 0, 3)));
   ```
3. New `Public/SaskartaSensorFilter.h` + `Private/SaskartaSensorFilter.cpp` (this folder): a world subsystem that,
   every 0.25 s in game worlds, finds PPV_Saskarta_Sensor (tag `Saskarta.SensorPPV`, else the actor name), swaps
   its MI_PP_SensorCRT blendable for a dynamic instance once, and sets `Amount`:
   - 0 / 0.35 / 0.6 / 0.85 for Off / Low / Medium / High (the cvar `saskarta.sensorfilter`);
   - times 0 unless the runner's FlowState is a carrier-camera state (Playing, Carrier, Collapsing, Booting,
     Rebooting): so the title, the menus, the loading and the cards, and the human-eye ending, have no sensor look.
   Only writes when the value changes (no per-frame work).
4. A test in `Tests/SaskartaSettingsTest.cpp`: ComputeCVars maps SensorFilter 3 -> "3", -1 -> "0", 9 -> "3";
   `USaskartaSensorFilterSubsystem::AmountFor(2, "Playing") == 0.6`, `AmountFor(2, "Title") == 0`.
