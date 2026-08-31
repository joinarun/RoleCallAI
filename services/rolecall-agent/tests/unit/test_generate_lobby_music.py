from __future__ import annotations

import base64
import importlib.util
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[4] / "scripts" / "media" / "generate_lobby_music.py"
SPEC = importlib.util.spec_from_file_location("generate_lobby_music", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def test_request_is_fixed_non_personal_and_global():
    request = MODULE.build_request()

    assert request["model"] == "lyria-3-pro-preview"
    assert request["input"] == [{"type": "text", "text": MODULE.PROMPT}]
    assert MODULE.LOCATION == "global"
    assert "participant" not in MODULE.PROMPT.lower()
    assert "transcript" not in MODULE.PROMPT.lower()


def test_extracts_mpeg_audio_from_interactions_response():
    audio = b"ID3" + b"music"
    response = {
        "outputs": [
            {
                "type": "audio",
                "mime_type": "audio/mpeg",
                "data": base64.b64encode(audio).decode(),
            }
        ]
    }

    assert MODULE.extract_audio(response) == audio


@pytest.mark.parametrize(
    "response",
    [
        {},
        {"outputs": [{"type": "text", "text": "not audio"}]},
        {"outputs": [{"type": "audio", "mime_type": "audio/wav", "data": "AA=="}]},
    ],
)
def test_rejects_missing_or_unexpected_audio(response):
    with pytest.raises(ValueError):
        MODULE.extract_audio(response)


def test_dry_run_never_requires_credentials_or_writes(tmp_path, capsys):
    output = tmp_path / "track.mp3"
    provenance = tmp_path / "track.json"

    result = MODULE.main(["--dry-run", "--output", str(output), "--provenance", str(provenance)])

    assert result == 0
    assert not output.exists()
    assert not provenance.exists()
    assert '"networkRequest": false' in capsys.readouterr().out


def test_generation_requires_exact_cost_confirmation(monkeypatch, tmp_path):
    called = False

    def forbidden_generate(_project):
        nonlocal called
        called = True
        return {}

    monkeypatch.setattr(MODULE, "generate", forbidden_generate)
    result = MODULE.main(
        [
            "--project",
            "test-project",
            "--confirm-cost-usd",
            "0.07",
            "--output",
            str(tmp_path / "track.mp3"),
            "--provenance",
            str(tmp_path / "track.json"),
        ]
    )

    assert result == 2
    assert called is False
