"""Optional Meta image-generation and speech-transcription helpers."""
import base64
import io
import json
import os
import wave

import httpx
from openai import OpenAI
from PIL import Image


def _configured(model_env, default):
    api_key = os.getenv("META_API_KEY", "").strip() or os.getenv("MODEL_API_KEY", "").strip()
    return bool(api_key and os.getenv(model_env, default).strip())


def image_generation_ready():
    return _configured("MUSE_IMAGE_MODEL", "muse-image-1.0")


def voice_transcription_ready():
    return _configured("MUSE_VOICE_MODEL", "muse-voice-transcribe-1.0")


def generate_floorplan(prompt):
    if not image_generation_ready():
        raise RuntimeError("Muse Image is not configured.")
    api_key = os.getenv("META_API_KEY", "").strip() or os.getenv("MODEL_API_KEY", "").strip()
    client = OpenAI(
        api_key=api_key,
        base_url=os.getenv("META_API_BASE_URL", os.getenv("MODEL_BASE_URL", "https://api.meta.ai/v1")).strip(),
        timeout=120,
        max_retries=0,
    )
    result = client.images.generate(
        model=os.getenv("MUSE_IMAGE_MODEL", "muse-image-1.0").strip(),
        prompt=("Create a clean, top-down 2D architectural floor plan drawing on a white background. "
                "Use crisp dark wall lines, clear room boundaries, visible door gaps, no perspective, "
                "no furniture, no text, and no shadows. Layout request: " + prompt),
        n=1,
        response_format="b64_json",
    )
    encoded = result.data[0].b64_json
    raw = base64.b64decode(encoded, validate=True)
    with Image.open(io.BytesIO(raw)) as image:
        image.load()
        image = image.convert("RGB")
        if image.width * image.height > 20_000_000:
            image.thumbnail((4096, 4096), Image.Resampling.LANCZOS)
        output = io.BytesIO()
        image.save(output, format="PNG", optimize=True)
    result_bytes = output.getvalue()
    if len(result_bytes) > 10 * 1024 * 1024:
        raise ValueError("The generated image exceeded the upload limit.")
    return result_bytes


def transcribe_audio(audio_bytes, filename):
    if not voice_transcription_ready():
        raise RuntimeError("Muse Voice Transcribe is not configured.")
    if len(audio_bytes) > 32 * 1024 * 1024:
        raise ValueError("Audio must be 32 MB or smaller.")
    try:
        with wave.open(io.BytesIO(audio_bytes), "rb") as wav:
            if wav.getnchannels() != 1 or wav.getsampwidth() != 2 or wav.getframerate() not in (16000, 24000):
                raise ValueError("Use a mono, 16-bit PCM WAV recorded at 16 kHz or 24 kHz.")
            if wav.getnframes() / wav.getframerate() > 600:
                raise ValueError("Audio must be 10 minutes or shorter.")
    except wave.Error as exc:
        raise ValueError("Choose a supported WAV audio recording.") from exc

    request_body = {"mode": "PUSH_TO_TALK", "model": os.getenv("MUSE_VOICE_MODEL", "muse-voice-transcribe-1.0").strip(), "audioEncoding": "WAV"}
    api_key = os.getenv("META_API_KEY", "").strip() or os.getenv("MODEL_API_KEY", "").strip()
    response = httpx.post(
        os.getenv("META_API_BASE_URL", os.getenv("MODEL_BASE_URL", "https://api.meta.ai/v1")).rstrip("/") + "/asr/transcribe",
        headers={"Authorization": "Bearer " + api_key},
        files={
            "request": (None, json.dumps(request_body), "application/json"),
            "audio": (filename or "recording.wav", audio_bytes, "audio/wav"),
        },
        timeout=120,
    )
    if response.status_code in (401, 403):
        raise RuntimeError("Meta API authentication failed.")
    if response.status_code >= 500 or response.status_code == 429:
        raise RuntimeError("Meta transcription service is temporarily unavailable.")
    if response.status_code >= 400:
        raise ValueError("Meta could not process this audio file.")
    try:
        payload = response.json()
        turns = payload.get("turns", [])
        transcript = payload.get("transcript") or " ".join(turn.get("transcript", "") for turn in turns)
    except (ValueError, AttributeError, TypeError) as exc:
        raise RuntimeError("Meta returned an unsupported transcription response.") from exc
    if not isinstance(transcript, str) or not transcript.strip():
        raise RuntimeError("The recording did not contain a usable transcript.")
    return transcript.strip()[:500]
