import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from whisperflow_local.paths import AppPaths
from whisperflow_local.stt import Transcriber, ensure_speech_model


class SpeechModelLifecycleTests(unittest.TestCase):
    def config(self):
        return {"model": "distil-large-v3", "quant": None, "batch_size": 12,
                "min_duration_s": 0.4, "min_rms": 0.005}

    def test_complete_app_owned_model_needs_no_download(self):
        with tempfile.TemporaryDirectory() as temp:
            paths = AppPaths.discover(Path(temp)); model = paths.models / "Speech" / "distil-large-v3"
            model.mkdir(parents=True); (model / "weights.npz").write_bytes(b"weights")
            (model / "config.json").write_text("{}")
            with patch("huggingface_hub.hf_hub_download") as download:
                self.assertEqual(ensure_speech_model(self.config(), paths), model)
                download.assert_not_called()

    def test_transcriber_model_path_is_application_support_not_cwd(self):
        with tempfile.TemporaryDirectory() as temp:
            paths = AppPaths.discover(Path(temp)); transcriber = Transcriber(self.config(), paths)
            self.assertEqual(transcriber.model_path, paths.models / "Speech" / "distil-large-v3")
            self.assertNotIn("mlx_models", str(transcriber.model_path))


if __name__ == "__main__": unittest.main()
