using UnrealBuildTool;

public class FayMetaHumanEditorTools : ModuleRules
{
    public FayMetaHumanEditorTools(ReadOnlyTargetRules Target) : base(Target)
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
                "BlueprintGraph",
                "FayBodyMotion",
                "IKRig",
                "IKRigEditor",
                "Kismet",
                "MetaHumanCharacter",
                "MetaHumanCharacterEditor",
                "UnrealEd"
            });
    }
}
