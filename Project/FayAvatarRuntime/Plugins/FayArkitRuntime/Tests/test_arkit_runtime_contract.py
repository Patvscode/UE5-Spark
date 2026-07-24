import json
from pathlib import Path
import unittest


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
HEADER = PLUGIN_ROOT / "Source/FayArkitRuntime/Public/FayArkitSpeechDriverComponent.h"
SOURCE = PLUGIN_ROOT / "Source/FayArkitRuntime/Private/FayArkitSpeechDriverComponent.cpp"
BUILD = PLUGIN_ROOT / "Source/FayArkitRuntime/FayArkitRuntime.Build.cs"
DESCRIPTOR = PLUGIN_ROOT / "FayArkitRuntime.uplugin"


class FayArkitRuntimeContractTests(unittest.TestCase):
    def test_plugin_is_source_only_and_depends_on_bridge(self):
        descriptor = json.loads(DESCRIPTOR.read_text(encoding="utf-8"))
        self.assertFalse(descriptor["CanContainContent"])
        self.assertEqual(descriptor["Modules"][0]["Name"], "FayArkitRuntime")
        self.assertEqual(descriptor["Modules"][0]["Type"], "Runtime")
        self.assertIn(
            "FayAvatarBridge",
            {plugin["Name"] for plugin in descriptor["Plugins"]},
        )
        build = BUILD.read_text(encoding="utf-8")
        self.assertIn('"FayAvatarBridge"', build)

    def test_public_orchestration_api_is_stable(self):
        header = HEADER.read_text(encoding="utf-8")
        expected = (
            "void AttachBridge(UFayAvatarBridgeComponent* InBridge);",
            "bool ConfigureAvatar(AActor* InAvatar, FName FaceComponentName);",
            "void ClearAvatar();",
            "bool IsConfigured() const;",
        )
        for declaration in expected:
            self.assertIn(declaration, header)

    def test_exact_reviewed_arkit_morphs_are_present(self):
        source = SOURCE.read_text(encoding="utf-8")
        required = {
            "jawOpen",
            "mouthClose",
            "mouthFunnel",
            "mouthPucker",
            "mouthSmileLeft",
            "mouthSmileRight",
            "eyeBlinkLeft",
            "eyeBlinkRight",
            "mouthSmile_L",
            "mouthSmile_R",
            "eyeBlink_L",
            "eyeBlink_R",
        }
        for morph in required:
            self.assertGreaterEqual(source.count(f'TEXT("{morph}")'), 1)
        self.assertIn("ResolveCompleteReviewedMorphContract", source)
        self.assertNotIn("FayMorphName=", source)

    def test_bridge_signals_are_subscribed_and_removed(self):
        source = SOURCE.read_text(encoding="utf-8")
        for event in (
            "OnMessageReceived",
            "OnSpeechStarted",
            "OnSpeechFinished",
            "OnMouthAmplitude",
        ):
            self.assertIn(f"Bridge->{event}.AddUniqueDynamic", source)
            self.assertIn(f"Bridge->{event}.RemoveDynamic", source)

    def test_driver_has_no_body_or_transform_write_api(self):
        source = SOURCE.read_text(encoding="utf-8")
        forbidden_writes = (
            "SetBone",
            "SetWorldTransform",
            "SetRelativeTransform",
            "SetActorTransform",
            "SetAnimInstanceClass",
            "SetAnimationMode",
            "ControlRig",
        )
        for symbol in forbidden_writes:
            self.assertNotIn(symbol, source)
        self.assertIn("SetMorphTarget", source)


if __name__ == "__main__":
    unittest.main()
