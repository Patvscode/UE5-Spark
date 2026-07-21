using UnrealBuildTool;

public class FayAvatarRuntime : ModuleRules
{
    public FayAvatarRuntime(ReadOnlyTargetRules Target) : base(Target)
    {
        PCHUsage = PCHUsageMode.UseExplicitOrSharedPCHs;

        PrivateDependencyModuleNames.AddRange(
            new string[]
            {
                "Core",
                "CoreUObject",
                "Engine",
                "FayAvatarBridge",
                "FayBodyMotion",
                "FayMetaHumanRuntime"
            });

    }
}
