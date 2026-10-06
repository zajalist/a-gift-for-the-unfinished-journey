using UnrealBuildTool;

public class SaskartaCore : ModuleRules
{
    public SaskartaCore(ReadOnlyTargetRules Target) : base(Target)
    {
        PCHUsage = PCHUsageMode.UseExplicitOrSharedPCHs;

        PublicDependencyModuleNames.AddRange(new string[] {
            "Core",
            "CoreUObject",
            "Engine",
            // Task MENUINPUT: USaskartaMenuWidget derives from UUserWidget (public header).
            "UMG",
            "SlateCore",
            "CinematicCamera",
            "Niagara"
        });

        // Task MENUINPUT: FSlateApplication (key -> navigation mapping), EKeys.
        PrivateDependencyModuleNames.AddRange(new string[] {
            "Slate",
            "InputCore"
        });

        // Task L7 (lighting director, readiness):
        //   RenderCore  FShaderPipelineCache::NumPrecompilesRemaining (ShaderPipelineCache.h)
        //   RHI         PipelineStateCache::NumActivePrecacheRequests (PipelineStateCache.h)
        //   PCG         UPCGComponent::IsGenerating (PCGComponent.h); PCG is listed in the .uplugin
        // World Partition (UWorldPartitionSubsystem, FWorldPartitionStreamingQuerySource), the
        // texture streamer (ContentStreaming.h), sky/fog/cloud components, Kismet and audio are
        // all in Engine.
        PrivateDependencyModuleNames.AddRange(new string[] {
            "RenderCore",
            "RHI",
            "PCG"
        });

        // Task EVENTS + RADIOSYS (story event runner, Low Voice station):
        //   Json           story-events.json / station.json / TSV importers
        //   LevelSequence  ULevelSequencePlayer, ALevelSequenceActor, UDefaultLevelSequenceInstanceData
        //   MovieScene     FMovieSceneSequencePlaybackSettings, UMovieSceneSequencePlayer
        //   AudioMixer     UAudioMixerBlueprintLibrary::SetSubmixEffectChainOverride (archive filter chain)
        //   AssetRegistry  take/song/line pickup by name without loading
        PrivateDependencyModuleNames.AddRange(new string[] {
            "Json",
            "LevelSequence",
            "MovieScene",
            "AudioMixer",
            "AssetRegistry"
        });

        // Task COLLAPSE-STAGE: ALandscapeProxy (the collapse stage grounds the carrier on the landscape only).
        PrivateDependencyModuleNames.Add("Landscape");
    }
}
