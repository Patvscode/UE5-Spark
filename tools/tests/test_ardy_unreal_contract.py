from __future__ import annotations

import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SOURCE_PATH = (
    REPO_ROOT
    / "Project/FayAvatarRuntime/Plugins/FayBodyMotion/Source/FayBodyMotion/Private"
    / "FayArdyPoseClientComponent.cpp"
)
HEADER_PATH = (
    REPO_ROOT
    / "Project/FayAvatarRuntime/Plugins/FayBodyMotion/Source/FayBodyMotion/Public"
    / "FayArdyPoseClientComponent.h"
)


class ArdyUnrealContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = SOURCE_PATH.read_text(encoding="utf-8")
        cls.header = HEADER_PATH.read_text(encoding="utf-8")

    def test_production_health_identity_is_exact(self) -> None:
        for marker in (
            'Object->Values.Num() == 13',
            'constexpr int32 ExpectedProtocolVersion = 2;',
            'CoordinateSystem == ExpectedCoordinateSystem',
            'ValidateSourceDescriptor(*Source)',
            'ValidateMotionCatalog(*MotionCatalog, QualifiedCatalog)',
            'Provider == TEXT("ardy")',
            'FacialControl == TEXT("excluded")',
            'Checkpoint == TEXT("ARDY-Core-RP-20FPS-Horizon8")',
            'EmbeddingCount == static_cast<double>(ExpectedMotionCatalog().Num())',
            'Object->TryGetBoolField(TEXT("dynamicTextReady"), bDynamicTextReady)',
            'bDynamicTextReady &&',
            'P95GenerationMilliseconds > 0.0',
            'P95GenerationMilliseconds < 400.0',
            'TEXT("FayAllowDiagnosticArdy=")',
        ):
            self.assertIn(marker, self.source)
        self.assertIn("bool bAllowDiagnosticProvider = false;", self.header)

    def test_pose_envelope_and_numeric_bounds_are_sealed(self) -> None:
        for marker in (
            "Object->Values.Num() != 6",
            "Source->Values.Num() != 8",
            "(*FrameObject)->Values.Num() != 5",
            "Frames->Num() != TargetBufferFrames",
            "Positions->Num() != ExpectedJointCount",
            'TEXT("invalid global joint position")',
            "MaximumJointPositionMetres",
            "SequenceNumber != FMath::FloorToDouble(SequenceNumber)",
            "SequenceNumber >= ExclusiveInt64UpperBound",
            "ExpectedFrameStepSeconds",
            "SizeSquared < 0.98f || SizeSquared > 1.02f",
            "Frame.RootTranslationMetres.Size() > MaximumRootTranslationMetres",
            "MaximumRootFrameStepMetres",
            "root translation changes too far between frames",
            "Contact < 0.0 || Contact > 1.0",
            "generated neck or head rotation is not excluded",
            'RotationSpace != TEXT("local")',
            'QuaternionOrder != TEXT("xyzw")',
            'PositionSpace != TEXT("global")',
        ):
            self.assertIn(marker, self.source)

    def test_root_and_core27_hips_are_the_same_transform(self) -> None:
        for marker in (
            "RootPositionConsistencyToleranceMetres = 1.0e-5",
            "Frame.JointPositionsMetres[0]",
            "root translation does not match global Hips position",
            "RootRotationConsistencyDotThreshold = 1.0f - 1.0e-5f",
            "FMath::Abs(",
            "Frame.JointRotations[0]",
            "root rotation does not match local Hips rotation",
        ):
            self.assertIn(marker, self.source)

    def test_disconnect_resets_time_and_keeps_loopback_fixed(self) -> None:
        self.assertIn("double LastFrameTimeSeconds = -1.0;", self.header)
        set_ready = self.source[
            self.source.index("void UFayArdyPoseClientComponent::SetReady") :
            self.source.index("bool UFayArdyPoseClientComponent::ParsePoseBatch")
        ]
        self.assertIn("LastFrameTimeSeconds = -1.0;", set_ready)
        self.assertIn("bHasLastRootTranslation = false;", set_ready)
        self.assertLess(
            set_ready.index("if (!bChanged)"),
            set_ready.index("bServiceReady = bReady;"),
        )
        self.assertIn('BaseUrl == TEXT("http://127.0.0.1:8777")', self.source)
        self.assertNotIn("FayArdyBaseUrl", self.source)

    def test_sequence_cursor_survives_actions_and_recovery(self) -> None:
        self.assertIn("int64 LastSequence = 0;", self.header)
        self.assertIn("LastSequence = Batch.Sequence;", self.source)
        self.assertNotIn("LastSequence = 0;", self.source)

    def test_free_text_prompt_is_forwarded_on_every_pose_batch(self) -> None:
        self.assertIn("FString ActivePrompt;", self.header)
        start_behavior = self.source[
            self.source.index("bool UFayArdyPoseClientComponent::StartBehavior") :
            self.source.index("void UFayArdyPoseClientComponent::StopBehavior")
        ]
        self.assertIn("const FString& Prompt", start_behavior)
        self.assertIn("Prompt.TrimStartAndEnd()", start_behavior)
        self.assertIn("NormalizedPrompt.Len() > 512", start_behavior)
        request = self.source[
            self.source.index("void UFayArdyPoseClientComponent::RequestPoseBatch") :
            self.source.index("void UFayArdyPoseClientComponent::RetireHealthRequest")
        ]
        self.assertIn('Payload->SetStringField(TEXT("prompt"), ActivePrompt);', request)

    def test_ready_service_is_requalified_periodically(self) -> None:
        for marker in (
            "constexpr double HealthPollSeconds = 5.0;",
            "bServiceReady ? HealthPollSeconds : HealthRetrySeconds",
            "HealthRetryElapsedSeconds += FMath::Max(0.0f, DeltaTime);",
            "ProbeHealth();",
        ):
            self.assertIn(marker, self.source)

    def test_synchronous_http_start_failure_enters_baked_fallback(self) -> None:
        health_start = self.source[
            self.source.index("if (!HealthRequest->ProcessRequest())") :
            self.source.index("void UFayArdyPoseClientComponent::RequestPoseBatch")
        ]
        pose_start = self.source[
            self.source.index("if (!PoseRequest->ProcessRequest())") :
            self.source.index("void UFayArdyPoseClientComponent::RetireHealthRequest")
        ]
        self.assertIn("SetReady(false);", health_start)
        self.assertIn("SetReady(false);", pose_start)

    def test_cancelled_callbacks_cannot_mutate_newer_requests(self) -> None:
        for marker in (
            "void UFayArdyPoseClientComponent::RetireHealthRequest()",
            "void UFayArdyPoseClientComponent::RetirePoseRequest()",
            "OnProcessRequestComplete().Unbind();",
            "Request != HealthRequest",
            "Request != PoseRequest",
            "ActiveBehavior.IsNone()",
            "bClientEnabled = false;",
        ):
            self.assertIn(marker, self.source)
        self.assertIn("RetirePoseRequest();\n    ActiveBehavior =", self.source)
        set_ready = self.source[
            self.source.index("void UFayArdyPoseClientComponent::SetReady") :
            self.source.index("bool UFayArdyPoseClientComponent::ParsePoseBatch")
        ]
        self.assertIn("RetireHealthRequest();", set_ready)
        self.assertIn("RetirePoseRequest();", set_ready)
        self.assertIn("!bServiceReady", self.source)

    def test_http_response_origin_type_and_actual_size_are_sealed(self) -> None:
        for marker in (
            'Request->GetEffectiveURL() == BaseUrl + TEXT("/healthz")',
            'Request->GetEffectiveURL() != BaseUrl + TEXT("/v2/poses")',
            "Response->GetContent().Num() <= MaximumResponseBytes",
            "Response->GetContent().Num() > MaximumResponseBytes",
            "ESearchCase::IgnoreCase",
        ):
            self.assertIn(marker, self.source)
        self.assertNotIn("GetContentLength()", self.source)
        self.assertNotIn("StartsWith(TEXT(\"application/json\"))", self.source)

    def test_expected_integer_fields_do_not_use_rounding_overloads(self) -> None:
        for marker in (
            "double Version = 0.0;",
            "double FramesPerSecond = 0.0;",
            "double BufferFrames = 0.0;",
            "double EmbeddingCount = 0.0;",
            "Version == static_cast<double>(ExpectedProtocolVersion)",
            "EmbeddingCount == static_cast<double>(ExpectedMotionCatalog().Num())",
        ):
            self.assertIn(marker, self.source)
        self.assertNotIn("int32 Version = 0;", self.source)
        self.assertNotIn("int32 FramesPerSecond = 0;", self.source)

    def test_root_motion_is_bounded_within_and_across_batches(self) -> None:
        self.assertIn("bool bHasLastRootTranslation = false;", self.header)
        for marker in (
            "bHasPreviousRootTranslation",
            "if (!bRejected && bHasLastRootTranslation)",
            "LastRootTranslationMetres = Batch.Frames.Last().RootTranslationMetres;",
            "MaximumActionTransitionGapSeconds",
            "MaximumActionTransitionRootStepMetres",
            "action-transition frame gap is invalid",
        ):
            self.assertIn(marker, self.source)
        start_behavior = self.source[
            self.source.index("bool UFayArdyPoseClientComponent::StartBehavior") :
            self.source.index("void UFayArdyPoseClientComponent::StopBehavior")
        ]
        self.assertNotIn("LastFrameTimeSeconds = -1.0;", start_behavior)
        self.assertNotIn("bHasLastRootTranslation = false;", start_behavior)


if __name__ == "__main__":
    unittest.main()
