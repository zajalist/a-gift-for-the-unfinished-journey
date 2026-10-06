using UnrealBuildTool;

public class SaskartaTerrainEditor : ModuleRules
{
    public SaskartaTerrainEditor(ReadOnlyTargetRules Target) : base(Target)
    {
        PCHUsage = PCHUsageMode.UseExplicitOrSharedPCHs;
        PublicDependencyModuleNames.AddRange(new string[] { "Core", "CoreUObject", "Engine" });
        PrivateDependencyModuleNames.AddRange(new string[] { "Landscape", "Foliage", "UnrealEd", "Json" });
        if (Target.Platform == UnrealTargetPlatform.Win64)
        {
            PublicSystemLibraries.Add("bcrypt.lib");
        }
    }
}
