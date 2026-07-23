import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[4]


def load_script(name, module_name):
    path = ROOT / "scripts" / name
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


PREFLIGHT = load_script(
    "check-spark-stack-preflight.py", "check_spark_stack_preflight"
)
WARM = load_script("warm-ardy-service.py", "warm_ardy_service")


class StartupHelperTests(unittest.TestCase):
    def test_memory_preflight_reads_memavailable(self):
        value = PREFLIGHT.parse_mem_available_kib(
            "MemTotal:       131072000 kB\n"
            "MemFree:          1000000 kB\n"
            "MemAvailable:    24117248 kB\n"
        )
        self.assertEqual(value, 24117248)
        with self.assertRaises(ValueError):
            PREFLIGHT.parse_mem_available_kib("MemTotal: 100 kB\n")

    def test_ardy_health_requires_dynamic_text_and_measured_sub_buffer_latency(self):
        base = {
            "status": "ready",
            "provider": "ardy",
            "protocolVersion": 2,
            "dynamicTextReady": True,
            "p95GenerationMs": 100.0,
        }
        self.assertTrue(WARM.qualified_health(base))
        for key, bad_value in (
            ("dynamicTextReady", False),
            ("p95GenerationMs", 0.0),
            ("p95GenerationMs", 400.0),
            ("p95GenerationMs", float("nan")),
            ("protocolVersion", 1),
            ("provider", "mock"),
        ):
            value = dict(base)
            value[key] = bad_value
            self.assertFalse(WARM.qualified_health(value), (key, bad_value))

    def test_warmup_sends_cached_idle_until_health_qualifies(self):
        calls = []
        health_checks = 0

        def requester(method, path, payload):
            nonlocal health_checks
            calls.append((method, path, payload))
            if path == "/healthz":
                health_checks += 1
                return {
                    "status": "ready",
                    "provider": "ardy",
                    "protocolVersion": 2,
                    "dynamicTextReady": True,
                    "p95GenerationMs": 0.0 if health_checks == 1 else 120.0,
                }
            return {
                "version": 2,
                "fps": 20,
                "sequence": 8,
                "frames": [{} for _ in range(8)],
            }

        clock = [0.0]

        def sleeper(seconds):
            clock[0] += seconds

        value = WARM.wait_until_ready(
            30,
            requester=requester,
            monotonic=lambda: clock[0],
            sleeper=sleeper,
        )
        self.assertEqual(value["p95GenerationMs"], 120.0)
        pose_calls = [call for call in calls if call[1] == "/v2/poses"]
        self.assertEqual(len(pose_calls), 1)
        self.assertEqual(pose_calls[0][2], {
            "behavior": "idle",
            "intensity": 0.35,
            "duration": 1.0,
            "afterSequence": 0,
        })
        self.assertNotIn("prompt", pose_calls[0][2])


class UnitTemplateTests(unittest.TestCase):
    def setUp(self):
        self.unit_root = ROOT / "deploy" / "systemd" / "user"

    def unit(self, name):
        return (self.unit_root / name).read_text(encoding="utf-8")

    def test_controller_is_enabled_but_heavy_target_has_no_install_hook(self):
        controller = self.unit("ue5-spark-private-controller.service.in")
        target = self.unit("ue5-spark-digital-human.target.in")
        self.assertIn("WantedBy=default.target", controller)
        self.assertIn(
            "ReadWritePaths=@LIVE_ROOT@ @CONFIG_WORKSPACE_ROOT@",
            controller,
        )
        self.assertIn("@ASSET_PROJECT_ROOT@", controller)
        self.assertNotIn("[Install]", target)
        self.assertNotIn("WantedBy=", target)

    def test_avatar_is_strictly_ordered_after_qualified_ardy_warmup(self):
        ready = self.unit("ue5-spark-ardy-ready.service.in")
        avatar = self.unit("ue5-spark-avatar.service.in")
        target = self.unit("ue5-spark-digital-human.target.in")
        self.assertIn("Before=ue5-spark-avatar.service", ready)
        self.assertIn("Requires=ue5-spark-ardy-ready.service", avatar)
        self.assertIn("After=ue5-spark-ardy-ready.service", avatar)
        self.assertIn("Requires=ue5-spark-ardy-ready.service", target)

    def test_stopping_target_stops_every_heavy_member(self):
        for name in (
            "ue5-spark-ardy.service.in",
            "ue5-spark-ardy-ready.service.in",
            "ue5-spark-avatar.service.in",
        ):
            self.assertIn(
                "PartOf=ue5-spark-digital-human.target",
                self.unit(name),
                name,
            )

    def test_ardy_preflight_and_no_swap_container_limit_remain_fixed(self):
        ardy_unit = self.unit("ue5-spark-ardy.service.in")
        ardy_launcher = (ROOT / "scripts" / "run-ardy-open-text-container.sh").read_text(
            encoding="utf-8"
        )
        self.assertIn("--minimum-available-gib 20", ardy_unit)
        self.assertIn("--memory 24g", ardy_launcher)
        self.assertIn("--memory-swap 24g", ardy_launcher)

    def test_no_unit_controls_fay(self):
        combined = "\n".join(
            path.read_text(encoding="utf-8")
            for path in sorted(self.unit_root.glob("*.in"))
        ).casefold()
        self.assertNotIn("fay.service", combined)
        self.assertNotIn("systemctl", combined)


if __name__ == "__main__":
    unittest.main()
