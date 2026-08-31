#!/usr/bin/env python3
"""Generate RoleCallAI's one-time, cached lobby soundtrack with Vertex AI Lyria."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import google.auth
import httpx
from google.auth.transport.requests import Request

MODEL = "lyria-3-pro-preview"
LOCATION = "global"
ESTIMATED_COST_USD = 0.08
PROMPT = (
    "Instrumental only. Warm, optimistic ambient electronic music for people waiting to join "
    "a professional AI-facilitated meeting. Soft synth pads, gentle marimba or plucked textures, "
    "light organic percussion, around 92 BPM, steady low intensity, no vocals, no dramatic drops, "
    "no abrupt ending, unobtrusive and loop-friendly, around three minutes."
)
DOCUMENTATION_URL = (
    "https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/music/generate-music"
)
MODEL_URL = "https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/lyria/lyria-3"


@dataclass(frozen=True)
class AudioMetadata:
    durationSeconds: float
    sampleRateHz: int
    bitRate: int


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate the single static RoleCallAI lobby track. One request costs about $0.08."
    )
    parser.add_argument(
        "--project", help="Google Cloud project ID; defaults to GOOGLE_CLOUD_PROJECT."
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("apps/web/src/assets/audio/rolecall-lobby-lyria.mp3"),
    )
    parser.add_argument(
        "--provenance",
        type=Path,
        default=Path("apps/web/src/assets/audio/rolecall-lobby-lyria.provenance.json"),
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Print the safe request summary only."
    )
    parser.add_argument(
        "--confirm-cost-usd",
        type=float,
        help=f"Required for generation and must equal {ESTIMATED_COST_USD:.2f}.",
    )
    return parser.parse_args(argv)


def build_request() -> dict[str, Any]:
    return {"model": MODEL, "input": [{"type": "text", "text": PROMPT}]}


def extract_audio(response: dict[str, Any]) -> bytes:
    for output in response.get("outputs", []):
        if output.get("type") != "audio":
            continue
        mime_type = output.get("mime_type") or output.get("mimeType")
        if mime_type != "audio/mpeg":
            raise ValueError(f"Unexpected Lyria MIME type: {mime_type!r}")
        data = output.get("data")
        if not isinstance(data, str) or not data:
            raise ValueError("Lyria response did not include base64 audio data.")
        audio = base64.b64decode(data, validate=True)
        if not audio.startswith((b"ID3", b"\xff\xfb", b"\xff\xf3", b"\xff\xf2")):
            raise ValueError("Lyria response is not a recognizable MP3 stream.")
        return audio
    raise ValueError("Lyria response did not include an audio output.")


def inspect_audio(path: Path) -> AudioMetadata:
    completed = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration,bit_rate:stream=sample_rate",
            "-of",
            "json",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    details = json.loads(completed.stdout)
    streams = details.get("streams") or []
    if not streams:
        raise ValueError("ffprobe found no audio stream.")
    duration = float(details["format"]["duration"])
    sample_rate = int(streams[0]["sample_rate"])
    bit_rate = int(details["format"].get("bit_rate") or 0)
    if duration < 120 or duration > 190:
        raise ValueError(f"Unexpected Lyria duration: {duration:.2f}s")
    if sample_rate != 44_100:
        raise ValueError(f"Unexpected Lyria sample rate: {sample_rate}Hz")
    return AudioMetadata(duration, sample_rate, bit_rate)


def atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as temporary:
            temporary.write(content)
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temporary_name, path)
    except Exception:
        Path(temporary_name).unlink(missing_ok=True)
        raise


def provenance(audio: bytes, metadata: AudioMetadata) -> dict[str, Any]:
    return {
        "asset": "rolecall-lobby-lyria.mp3",
        "generatedAt": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "generator": "Google Vertex AI Lyria",
        "model": MODEL,
        "location": LOCATION,
        "prompt": PROMPT,
        "mimeType": "audio/mpeg",
        "estimatedGenerationCostUsd": ESTIMATED_COST_USD,
        "durationSeconds": round(metadata.durationSeconds, 3),
        "sampleRateHz": metadata.sampleRateHz,
        "bitRate": metadata.bitRate,
        "sha256": hashlib.sha256(audio).hexdigest(),
        "runtimeCalls": 0,
        "dataBoundaryNote": (
            "Only this fixed, non-personal prompt was sent to Lyria's global endpoint once. "
            "No participant, room, transcript, document, or meeting data was sent."
        ),
        "documentation": [MODEL_URL, DOCUMENTATION_URL],
    }


def generate(project: str, client: httpx.Client | None = None) -> dict[str, Any]:
    credentials, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    credentials.refresh(Request())
    endpoint = (
        "https://aiplatform.googleapis.com/v1beta1/"
        f"projects/{project}/locations/{LOCATION}/interactions"
    )
    request_client = client or httpx.Client(timeout=240)
    close_client = client is None
    try:
        response = request_client.post(
            endpoint,
            headers={"Authorization": f"Bearer {credentials.token}"},
            json=build_request(),
        )
        response.raise_for_status()
        return response.json()
    finally:
        if close_client:
            request_client.close()


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    project = args.project or os.getenv("GOOGLE_CLOUD_PROJECT")
    if args.dry_run:
        print(
            json.dumps(
                {
                    "model": MODEL,
                    "location": LOCATION,
                    "estimatedCostUsd": ESTIMATED_COST_USD,
                    "output": str(args.output),
                    "prompt": PROMPT,
                    "networkRequest": False,
                },
                indent=2,
            )
        )
        return 0
    if not project:
        print("--project or GOOGLE_CLOUD_PROJECT is required.", file=sys.stderr)
        return 2
    if args.confirm_cost_usd != ESTIMATED_COST_USD:
        print(
            f"Generation requires --confirm-cost-usd {ESTIMATED_COST_USD:.2f}; no request sent.",
            file=sys.stderr,
        )
        return 2
    if args.output.exists() or args.provenance.exists():
        print(
            "Output already exists. Refusing to spend money or overwrite the approved asset.",
            file=sys.stderr,
        )
        return 2

    response = generate(project)
    audio = extract_audio(response)
    atomic_write(args.output, audio)
    try:
        metadata = inspect_audio(args.output)
        atomic_write(
            args.provenance,
            (json.dumps(provenance(audio, metadata), indent=2) + "\n").encode(),
        )
    except Exception:
        args.output.unlink(missing_ok=True)
        raise

    print(
        f"Generated {args.output} ({metadata.durationSeconds:.1f}s, "
        f"sha256={hashlib.sha256(audio).hexdigest()[:12]}…)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
