using UnrealBuildTool;
using System.Collections.Generic;

// x86-64 commandlet/cooker target for the Spark's isolated FEX build host.
// These flags make the host Editor include the LinuxArm64 target-platform and
// shader-format modules needed to cook content for the native Spark runtime.
public class FayAvatarRuntimeEditorTarget : TargetRules
{
    public FayAvatarRuntimeEditorTarget(TargetInfo Target) : base(Target)
    {
        Type = TargetType.Editor;
        DefaultBuildSettings = BuildSettingsVersion.Latest;
        IncludeOrderVersion = EngineIncludeOrderVersion.Latest;
        bForceBuildTargetPlatforms = true;
        bForceBuildShaderFormats = true;
        ExtraModuleNames.Add("FayAvatarRuntime");
    }
}
