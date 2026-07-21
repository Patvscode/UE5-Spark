using UnrealBuildTool;

public class FayBodyMotion : ModuleRules
{
    public FayBodyMotion(ReadOnlyTargetRules Target) : base(Target)
    {
        PCHUsage = PCHUsageMode.UseExplicitOrSharedPCHs;

        PublicDependencyModuleNames.AddRange(
            new string[]
            {
                "Core",
                "CoreUObject",
                "Engine",
                "FayAvatarBridge",
                "HTTP"
            });

        PrivateDependencyModuleNames.AddRange(
            new string[]
            {
                "Json"
            });
    }
}
