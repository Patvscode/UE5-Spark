using UnrealBuildTool;

public class FayAvatarBridge : ModuleRules
{
    public FayAvatarBridge(ReadOnlyTargetRules Target) : base(Target)
    {
        PCHUsage = PCHUsageMode.UseExplicitOrSharedPCHs;

        PublicDependencyModuleNames.AddRange(
            new string[]
            {
                "Core",
                "CoreUObject",
                "Engine"
            });

        PrivateDependencyModuleNames.AddRange(
            new string[]
            {
                "HTTP",
                "Json",
                "WebSockets"
            });
    }
}
