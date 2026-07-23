from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np

from benchmarks import run_baseline
from benchmarks.run_baseline import (
    connect_owned_cleanup_service,
    managed_cleanup_config,
    measure_profile,
    resolved_stt_config,
)
from whisperflow_local.inserter import FocusTarget
from whisperflow_local.service import ServiceHealth, ServiceState


class FakeTranscriber:
    def transcribe(self, audio, sample_rate):
        return "raw text"


class FakeCleaner:
    def clean(self, transcript):
        return "clean text"


class FakeInsertionAdapter:
    def __init__(self, result=(True, "pasted")) -> None:
        self.captured = []
        self.inserted = []
        self.result = result

    def capture_target(self):
        target = FocusTarget(pid=42, bundle_id="test.bundle")
        self.captured.append(target)
        return target

    def insert(self, text, target):
        self.inserted.append((text, target))
        return self.result


class BaselineTests(unittest.TestCase):
    @patch(
        "benchmarks.run_baseline.time.perf_counter",
        side_effect=[1.0, 1.1, 1.2, 1.25],
    )
    def test_measure_profile_includes_confirmed_insertion(self, _clock) -> None:
        adapter = FakeInsertionAdapter()
        result = measure_profile(
            FakeTranscriber(), FakeCleaner(), np.zeros(4), 16_000, 1,
            insertion_adapter=adapter,
        )
        self.assertEqual(result["stt"]["p50_ms"], 100.0)
        self.assertEqual(result["cleanup"]["p50_ms"], 100.0)
        self.assertEqual(result["direct_insertion"]["p50_ms"], 50.0)
        self.assertEqual(result["direct_stop_to_insert"]["p50_ms"], 250.0)
        self.assertEqual(adapter.inserted, [("clean text", adapter.captured[0])])

    def test_measure_profile_applies_production_cleanup_guard(self) -> None:
        class ProtectedTranscriber:
            def transcribe(self, audio, sample_rate):
                return "Send Kaden the update."

        adapter = FakeInsertionAdapter()
        measure_profile(
            ProtectedTranscriber(), FakeCleaner(), np.zeros(4), 16_000, 1,
            insertion_adapter=adapter,
            protected_terms=("Kaden",),
        )
        self.assertEqual(adapter.inserted[0][0], "Send Kaden the update.")

    def test_measure_profile_rejects_unconfirmed_insertion(self) -> None:
        adapter = FakeInsertionAdapter((False, "paste_unconfirmed"))
        with self.assertRaisesRegex(RuntimeError, "paste_unconfirmed"):
            measure_profile(
                FakeTranscriber(), FakeCleaner(), np.zeros(4), 16_000, 1,
                insertion_adapter=adapter,
            )

    def test_runtime_configs_use_profile_and_managed_credentials(self) -> None:
        cfg = SimpleNamespace(
            stt={"model": "configured-model", "batch_size": 1, "quant": None},
            performance={"profile": "quality"},
        )
        self.assertEqual(
            resolved_stt_config(cfg),
            {"model": "large-v3", "batch_size": 8, "quant": None},
        )
        cleanup = managed_cleanup_config({
            "provider": "openai-compatible",
            "api_key": "configured-secret",
            "api_key_env": "SECRET_ENV",
            "api_key_keychain_account": "secret-account",
            "fallback_provider": "unsloth-cli",
        })
        for removed in (
            "api_key", "api_key_env", "api_key_keychain_account",
            "fallback_provider",
        ):
            self.assertNotIn(removed, cleanup)

    def test_managed_service_requires_ready_owned_runtime_key(self) -> None:
        cases = (
            ServiceHealth(ServiceState.ERROR, False, "failed", ""),
            ServiceHealth(ServiceState.READY, False, "foreign", "key"),
            ServiceHealth(ServiceState.READY, True, "missing key", ""),
        )
        for health in cases:
            with self.subTest(health=health):
                manager = Mock()
                manager.connect_or_start.return_value = health
                with self.assertRaisesRegex(RuntimeError, "ready app-owned"):
                    connect_owned_cleanup_service(manager)

        manager = Mock()
        manager.connect_or_start.return_value = ServiceHealth(
            ServiceState.READY, True, "ready", "runtime-key"
        )
        self.assertEqual(connect_owned_cleanup_service(manager), "runtime-key")

    def test_main_wires_live_insertion_without_claiming_qt_completion(self) -> None:
        class FakeRuntimeTranscriber:
            instances = []

            def __init__(self, cfg):
                self.cfg = cfg
                self.instances.append(self)

            def load(self):
                pass

        class FakeRuntimeCleaner:
            instances = []

            def __init__(self, cfg):
                self.cfg = cfg
                self.api_key = ""
                self.instances.append(self)

            def set_api_key(self, api_key):
                self.api_key = api_key

            def warmup(self):
                pass

        cfg = SimpleNamespace(
            stt={"model": "configured-stt", "batch_size": 1, "quant": None},
            performance={"profile": "quality"},
            cleanup={
                "provider": "openai-compatible",
                "base_url": "http://127.0.0.1:8888/v1",
                "model": "test-cleanup",
                "api_key_env": "SHOULD_NOT_BE_READ",
                "api_key_keychain_account": "should-not-be-read",
                "fallback_provider": "unsloth-cli",
            },
            insert={"mode": "paste"},
            personalization={"vocabulary": ["Kaden"]},
        )
        adapter = FakeInsertionAdapter()
        manager = Mock()
        manager.connect_or_start.return_value = ServiceHealth(
            ServiceState.READY, True, "ready", "generated-runtime-key"
        )
        measured = {
            "stt": {"p50_ms": 1.0},
            "cleanup": {"p50_ms": 2.0},
            "total": {"p50_ms": 3.0},
            "direct_insertion": {"p50_ms": 4.0},
            "direct_stop_to_insert": {"p50_ms": 7.0},
        }
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "result.json"
            argv = [
                "run_baseline.py", "--runs", "1", "--durations", "2",
                "--live-insertion", "--output", str(output),
            ]
            with (
                patch.object(run_baseline.sys, "argv", argv),
                patch.object(run_baseline, "ensure_sample", return_value=True),
                patch.object(run_baseline, "load_config", return_value=cfg),
                patch.object(
                    run_baseline, "load_wav_16k_mono",
                    return_value=(np.ones(4, dtype=np.float32), 16_000),
                ),
                patch.object(run_baseline, "Transcriber", FakeRuntimeTranscriber),
                patch.object(run_baseline, "Cleaner", FakeRuntimeCleaner),
                patch.object(
                    run_baseline, "LocalServiceManager", return_value=manager
                ) as manager_factory,
                patch.object(
                    run_baseline, "LiveInsertionAdapter", return_value=adapter
                ),
                patch.object(
                    run_baseline, "measure_profile", return_value=measured
                ) as measure,
                patch.object(run_baseline, "peak_rss_mb", return_value=100.0),
            ):
                self.assertEqual(run_baseline.main(), 0)
            payload = json.loads(output.read_text())

        self.assertEqual(payload["schema"], 4)
        self.assertTrue(payload["direct_stop_to_insert_measured"])
        self.assertEqual(
            payload["measurement_scope"], "direct-components-with-insertion"
        )
        self.assertNotIn("stop_to_insert_measured", payload)
        self.assertEqual(payload["performance_profile"], "quality")
        self.assertEqual(payload["stt_model"], "large-v3")
        self.assertEqual(payload["stt_batch_size"], 8)
        self.assertEqual(
            FakeRuntimeTranscriber.instances[0].cfg["model"], "large-v3"
        )
        self.assertEqual(FakeRuntimeCleaner.instances[0].api_key, "generated-runtime-key")
        manager.connect_or_start.assert_called_once_with()
        manager.stop.assert_called_once_with()
        managed_cfg = manager_factory.call_args.args[0]
        self.assertNotIn("api_key", managed_cfg)
        self.assertNotIn("api_key_env", managed_cfg)
        self.assertNotIn("api_key_keychain_account", managed_cfg)
        self.assertIs(measure.call_args.kwargs["insertion_adapter"], adapter)
        self.assertEqual(
            tuple(measure.call_args.kwargs["protected_terms"]), ("Kaden",)
        )

    def test_main_fails_loudly_and_stops_service_on_warmup_error(self) -> None:
        class FakeRuntimeTranscriber:
            def __init__(self, cfg):
                pass

            def load(self):
                pass

        class FailingCleaner:
            def __init__(self, cfg):
                pass

            def set_api_key(self, api_key):
                pass

            def warmup(self):
                raise RuntimeError("warmup failed")

        cfg = SimpleNamespace(
            stt={"model": "configured-stt", "batch_size": 1, "quant": None},
            performance={"profile": "instant"},
            cleanup={
                "provider": "openai-compatible",
                "base_url": "http://127.0.0.1:8888/v1",
                "model": "test-cleanup",
            },
            insert={"mode": "paste"},
            personalization={"vocabulary": []},
        )
        manager = Mock()
        manager.connect_or_start.return_value = ServiceHealth(
            ServiceState.READY, True, "ready", "generated-runtime-key"
        )
        argv = ["run_baseline.py", "--runs", "1", "--durations", "2"]
        with (
            patch.object(run_baseline.sys, "argv", argv),
            patch.object(run_baseline, "ensure_sample", return_value=True),
            patch.object(run_baseline, "load_config", return_value=cfg),
            patch.object(
                run_baseline, "load_wav_16k_mono",
                return_value=(np.ones(4, dtype=np.float32), 16_000),
            ),
            patch.object(run_baseline, "Transcriber", FakeRuntimeTranscriber),
            patch.object(run_baseline, "Cleaner", FailingCleaner),
            patch.object(
                run_baseline, "LocalServiceManager", return_value=manager
            ),
        ):
            with self.assertRaisesRegex(RuntimeError, "warmup failed"):
                run_baseline.main()
        manager.stop.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
