#!/usr/bin/env python3
"""
scripts/check_keys.py - Meta Model API Key Verification Utility
Tests MODEL_API_KEY against Meta Model API endpoints:
1. One minimal SAM 3.1 request (concept 'room')
2. One minimal Muse Spark request ('hello')
3. Optional --list-models flag to inspect account model access

SECURITY GUARANTEE: Never prints, logs, or returns the API key.
Zero emoji policy enforced.
Built with Python standard library (urllib.request) for maximum portability.
"""

import argparse
import base64
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

# Ensure project root is in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import MODEL_API_KEY, MODEL_BASE_URL, SAM_MODEL, MUSE_MODEL

# Minimal valid 10x10 PNG bytes
DUMMY_PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAoAAAAKCAYAAACNMs+9AAAAFUlEQVR42mP8"
    "z8BQz0AEYBxVSF+FABJADveWkH6oAAAAAElFTkSuQmCC"
)
DUMMY_IMAGE_DATA_URL = f"data:image/png;base64,{DUMMY_PNG_B64}"


def list_models(api_key, base_url):
    url = f"{base_url.rstrip('/')}/models"
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {api_key}",
            "User-Agent": "FloorPlan3D-KeyChecker/1.0",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            models = data.get("data", [])
            print(f"[PASS] Available models ({len(models)}):")
            for m in models:
                mid = m.get("id") if isinstance(m, dict) else str(m)
                print(f"  - {mid}")
            return True
    except urllib.error.HTTPError as err:
        if err.code == 401:
            print("[FAIL] 401 Unauthorized: Invalid MODEL_API_KEY.")
        elif err.code == 403:
            print("[FAIL] 403 Forbidden: Account does not have permission to query /models.")
        else:
            print(f"[FAIL] HTTP {err.code}: {err.reason}")
        return False
    except Exception as exc:
        print(f"[FAIL] Network error querying /models: {type(exc).__name__}: {exc}")
        return False


def test_sam_key(api_key, base_url, model):
    url = f"{base_url.rstrip('/')}/responses"
    payload = {
        "model": model,
        "input": [{
            "type": "message",
            "role": "user",
            "content": [
                {"type": "input_text", "text": "room"},
                {"type": "input_image", "image_url": DUMMY_IMAGE_DATA_URL},
            ],
        }],
        "metadata": {"mask_encoding": "one_bit", "include_confidence": "true"},
    }
    data_bytes = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data_bytes,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "FloorPlan3D-KeyChecker/1.0",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            if resp.status == 200:
                print(f"[PASS] SAM 3.1 ({model}): Response 200 OK")
                return True
            print(f"[FAIL] SAM 3.1: Unexpected HTTP {resp.status}")
            return False
    except urllib.error.HTTPError as err:
        if err.code == 401:
            print("[FAIL] SAM 3.1: 401 Unauthorized (invalid MODEL_API_KEY).")
        elif err.code == 403:
            print(f"[FAIL] SAM 3.1: 403 Forbidden (no access to {model}; did you accept terms?).")
        elif err.code == 404:
            print(f"[FAIL] SAM 3.1: 404 Not Found (model {model} not found or endpoint URL incorrect).")
        elif err.code == 429:
            print("[FAIL] SAM 3.1: 429 Rate Limit Exceeded.")
        else:
            print(f"[FAIL] SAM 3.1: HTTP {err.code} ({err.reason})")
        return False
    except Exception as exc:
        print(f"[FAIL] SAM 3.1: Connection error ({type(exc).__name__}: {exc})")
        return False


def test_muse_key(api_key, base_url, model):
    url = f"{base_url.rstrip('/')}/chat/completions"
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": "hello"}],
        "max_tokens": 10,
    }
    data_bytes = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data_bytes,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "FloorPlan3D-KeyChecker/1.0",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            if resp.status == 200:
                print(f"[PASS] Muse Spark ({model}): Response 200 OK")
                return True
            print(f"[FAIL] Muse Spark: Unexpected HTTP {resp.status}")
            return False
    except urllib.error.HTTPError as err:
        if err.code == 401:
            print("[FAIL] Muse Spark: 401 Unauthorized (invalid MODEL_API_KEY).")
        elif err.code == 403:
            print(f"[FAIL] Muse Spark: 403 Forbidden (no access to {model}; did you accept terms?).")
        elif err.code == 404:
            print(f"[FAIL] Muse Spark: 404 Not Found (model {model} not found or endpoint URL incorrect).")
        elif err.code == 429:
            print("[FAIL] Muse Spark: 429 Rate Limit Exceeded.")
        else:
            print(f"[FAIL] Muse Spark: HTTP {err.code} ({err.reason})")
        return False
    except Exception as exc:
        print(f"[FAIL] Muse Spark: Connection error ({type(exc).__name__}: {exc})")
        return False


def main():
    parser = argparse.ArgumentParser(description="Check Meta Model API key and model connectivity.")
    parser.add_argument("--list-models", action="store_true", help="List available models for the configured key.")
    args = parser.parse_args()

    api_key = MODEL_API_KEY
    base_url = MODEL_BASE_URL

    if not api_key:
        print("[FAIL] MODEL_API_KEY is not configured in environment or .env file.")
        print("Set MODEL_API_KEY in your .env file or environment, then rerun.")
        sys.exit(1)

    print(f"Checking Meta Model API configuration at {base_url}...")

    if args.list_models:
        ok = list_models(api_key, base_url)
        sys.exit(0 if ok else 1)

    sam_ok = test_sam_key(api_key, base_url, SAM_MODEL)
    muse_ok = test_muse_key(api_key, base_url, MUSE_MODEL)

    if sam_ok and muse_ok:
        print("\nAll key checks passed successfully. Ready for live processing (MOCK_AI=0).")
        sys.exit(0)
    else:
        print("\nOne or more checks failed. Review error output above.")
        sys.exit(1)


if __name__ == "__main__":
    main()
