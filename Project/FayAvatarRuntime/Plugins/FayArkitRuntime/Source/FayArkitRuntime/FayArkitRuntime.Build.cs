using UnrealBuildTool;

public class FayArkitRuntime : ModuleRules
{
    public FayArkitRuntime(ReadOnlyTargetRules Target) : base(Target)
    {
        PCHUsage = PCHUsageMode.UseExplicitOrSharedPCHs;

        PublicDependencyModuleNames.AddRange(
            new string[]
            {
                "Core",
                "CoreUObject",
                "Engine",
                "FayAvatarBridge"
            });
    }
}
