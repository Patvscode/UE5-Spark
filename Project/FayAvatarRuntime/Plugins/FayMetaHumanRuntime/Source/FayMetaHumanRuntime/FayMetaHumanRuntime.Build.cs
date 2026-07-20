using UnrealBuildTool;

public class FayMetaHumanRuntime : ModuleRules
{
    public FayMetaHumanRuntime(ReadOnlyTargetRules Target) : base(Target)
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

        PrivateDependencyModuleNames.AddRange(
            new string[]
            {
                "AudioPlatformConfiguration",
                "LiveLink",
                "LiveLinkInterface",
                "MetaHumanCoreTech",
                "NNE",
                "SpeechAnimationSolver"
            });
    }
}
