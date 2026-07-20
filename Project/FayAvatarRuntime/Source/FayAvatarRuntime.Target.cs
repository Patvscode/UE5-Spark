using UnrealBuildTool;
using System.Collections.Generic;

public class FayAvatarRuntimeTarget : TargetRules
{
    public FayAvatarRuntimeTarget(TargetInfo Target) : base(Target)
    {
        Type = TargetType.Game;
        DefaultBuildSettings = BuildSettingsVersion.Latest;
        IncludeOrderVersion = EngineIncludeOrderVersion.Latest;
        ExtraModuleNames.Add("FayAvatarRuntime");
    }
}
