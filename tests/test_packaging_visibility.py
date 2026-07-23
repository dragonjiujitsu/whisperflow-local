from configparser import ConfigParser
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_developer_bundle_is_emitted_under_hidden_build_directory() -> None:
    spec = ConfigParser()
    spec.read(ROOT / "pysidedeploy.spec")

    assert spec["app"]["exec_directory"] == ".build"
    assert '.build" / "WhisperFlow Local.app"' in (
        ROOT / "packaging" / "build_macos.py"
    ).read_text()
