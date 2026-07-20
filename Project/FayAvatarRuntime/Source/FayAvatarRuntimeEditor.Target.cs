using UnrealBuildTool;
using System.Collections.Generic;

// Standard editor target for the supported x86-64 build/cook host. This is
// deliberately not opted into LinuxArm64 and is unrelated to the experimental
// native-Spark Editor target used during the initial investigation.
public class FayAvatarRuntimeEditorTarget : TargetRules
{
    public FayAvatarRuntimeEditorTarget(TargetInfo Target) : base(Target)
    {
        Type = TargetType.Editor;
        DefaultBuildSettings = BuildSettingsVersion.Latest;
        IncludeOrderVersion = EngineIncludeOrderVersion.Latest;
        ExtraModuleNames.Add("FayAvatarRuntime");
    }
}
