#!/usr/bin/env python3
"""Companion server for the Art Bell visualizer.

Serves the visualizer at http://localhost:8765 and proxies Gemini so the API
key stays out of the browser. Zero dependencies.

Endpoints:
  GET  /health     -> {ok, genai}
  POST /interpret  -> LLM topic brain: transcript -> {label, theme, scene_prompt,
                      palette, intensity} via a Gemini flash-lite text model
                      (JSON mode)
  POST /generate   -> {prompt, reference?} -> {image: dataURL} via
                      gemini-2.5-flash-image; saves a copy + sidecar to
                      visions/YYYY-MM-DD/

API key lookup order: $GEMINI_API_KEY, $GOOGLE_API_KEY, a GEMINI_API_KEY or
GOOGLE_API_KEY line in a local .env file next to this script, then
~/Code/rafiki/.env. Get a key at https://aistudio.google.com/app/apikey
"""

from __future__ import annotations

import base64
import json
import os
import threading
import time
import urllib.request
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

PORT = 8765
IMAGE_MODEL = "gemini-2.5-flash-image"
TEXT_MODEL = "gemini-flash-lite-latest"
MIN_SECONDS_BETWEEN_IMAGES = 20
MIN_SECONDS_BETWEEN_INTERPRET = 15
HERE = Path(__file__).resolve().parent
LOCAL_ENV = HERE / ".env"                          # drop your key here (gitignored)
RAFIKI_ENV = Path.home() / "Code" / "rafiki" / ".env"  # personal fallback
VISIONS_DIR = HERE / "visions"

BRAIN_PROMPT = """You are the visual director for a live visualizer running \
behind old Art Bell / Coast to Coast AM radio episodes. Below is a rough live \
transcript fragment (speech-to-text, may be garbled). Decide what the \
conversation is about and design the visual mood.

Respond with ONLY a JSON object:
{
  "label": "short evocative lowercase mood name, max 5 words",
  "theme": "one of: nye aliens demons ghosts gov cryptids time, or null if none fits",
  "scene_prompt": "one vivid sentence describing imagery for an AI image generator, dark cinematic surreal, matching the topic",
  "palette": [[r,g,b],[r,g,b],[r,g,b]],
  "intensity": 0.5
}

palette: three colors as 0.0-1.0 floats - darkest base, main body, bright
accent. Dark moody colors, base very dark. intensity: 0.0-1.0, how
agitated/energetic the conversation feels.

If the transcript is empty, mundane, or too garbled to read a topic, use theme \
"nye", label "the kingdom of nye", and a Nevada desert night scene.

Transcript:
"""


def _key_from_env_file(path: Path) -> str | None:
    if not path.exists():
        return None
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        for name in ("GEMINI_API_KEY", "GOOGLE_API_KEY"):
            if line.startswith(name + "="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return None


def find_api_key() -> str | None:
    for name in ("GEMINI_API_KEY", "GOOGLE_API_KEY"):
        if os.environ.get(name):
            return os.environ[name]
    return _key_from_env_file(LOCAL_ENV) or _key_from_env_file(RAFIKI_ENV)


API_KEY = find_api_key()
_image_lock = threading.Lock()
_interpret_lock = threading.Lock()
_last_image = 0.0
_last_interpret = 0.0


def gemini_call(model: str, body: dict) -> dict:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", "x-goog-api-key": API_KEY},
    )
    with urllib.request.urlopen(req, timeout=90) as resp:
        return json.loads(resp.read().decode("utf-8"))


def gemini_generate(prompt: str, reference: str | None) -> str:
    """Generate one image (optionally evolving a reference), return a data: URL."""
    parts: list[dict] = []
    if reference and reference.startswith("data:"):
        header, b64 = reference.split(",", 1)
        mime = header.split(":", 1)[1].split(";", 1)[0]
        parts.append({"inlineData": {"mimeType": mime, "data": b64}})
        prompt += (" Use the attached image as loose inspiration: keep a similar "
                   "overall palette and dreamlike continuity, but evolve the "
                   "scene into this new subject.")
    parts.append({"text": prompt})
    body = {
        "contents": [{"parts": parts}],
        "generationConfig": {
            "responseModalities": ["TEXT", "IMAGE"],
            "imageConfig": {"aspectRatio": "16:9"},
        },
    }
    data = gemini_call(IMAGE_MODEL, body)
    for part in data["candidates"][0]["content"]["parts"]:
        inline = part.get("inlineData")
        if inline and inline.get("mimeType", "").startswith("image/"):
            return f"data:{inline['mimeType']};base64,{inline['data']}"
    raise ValueError("no image in Gemini response")


def gemini_interpret(transcript: str) -> dict:
    body = {
        "contents": [{"parts": [{"text": BRAIN_PROMPT + transcript[:4000]}]}],
        "generationConfig": {"responseMimeType": "application/json"},
    }
    data = gemini_call(TEXT_MODEL, body)
    raw = data["candidates"][0]["content"]["parts"][0]["text"]
    out = json.loads(raw)
    # clamp/sanitize before it touches the page
    label = str(out.get("label", ""))[:60] or "the kingdom of nye"
    theme = out.get("theme")
    if theme not in ("nye", "aliens", "demons", "ghosts", "gov", "cryptids", "time"):
        theme = None
    palette = out.get("palette")
    ok_palette = (
        isinstance(palette, list) and len(palette) == 3
        and all(isinstance(c, list) and len(c) == 3 for c in palette)
    )
    if ok_palette:
        palette = [[max(0.0, min(1.0, float(v))) for v in c] for c in palette]
    else:
        palette = None
    try:
        intensity = max(0.0, min(1.0, float(out.get("intensity", 0.5))))
    except (TypeError, ValueError):
        intensity = 0.5
    return {
        "label": label,
        "theme": theme,
        "scene_prompt": str(out.get("scene_prompt", ""))[:500],
        "palette": palette,
        "intensity": intensity,
    }


def save_vision(image_data_url: str, prompt: str, meta: dict) -> None:
    try:
        day_dir = VISIONS_DIR / time.strftime("%Y-%m-%d")
        day_dir.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%H%M%S")
        header, b64 = image_data_url.split(",", 1)
        ext = "png" if "png" in header else "jpg"
        (day_dir / f"{stamp}.{ext}").write_bytes(base64.b64decode(b64))
        sidecar = {"time": time.strftime("%Y-%m-%d %H:%M:%S"), "prompt": prompt, **meta}
        (day_dir / f"{stamp}.json").write_text(json.dumps(sidecar, indent=2), encoding="utf-8")
    except Exception as e:  # the gallery is best-effort; never fail a generation over it
        print(f"[vision] save failed: {e}")


class Handler(SimpleHTTPRequestHandler):
    def end_headers(self):
        # file:// pages (origin "null") must be able to call us too
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def do_OPTIONS(self):
        self.send_response(204)
        self.end_headers()

    def _json(self, code: int, payload: dict) -> None:
        raw = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _read_body(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(length) or b"{}")

    def do_GET(self):
        if self.path == "/health":
            self._json(200, {"ok": True, "genai": API_KEY is not None})
            return
        super().do_GET()

    def do_POST(self):
        if self.path == "/generate":
            self._handle_generate()
        elif self.path == "/interpret":
            self._handle_interpret()
        else:
            self._json(404, {"error": "unknown endpoint"})

    def _handle_generate(self):
        global _last_image
        if not API_KEY:
            self._json(503, {"error": "no GOOGLE_API_KEY found (env or ~/Code/rafiki/.env)"})
            return
        if not _image_lock.acquire(blocking=False):
            self._json(429, {"error": "generation already in flight"})
            return
        try:
            if time.time() - _last_image < MIN_SECONDS_BETWEEN_IMAGES:
                self._json(429, {"error": "too soon"})
                return
            payload = self._read_body()
            prompt = str(payload.get("prompt", "")).strip()
            if not prompt:
                self._json(400, {"error": "missing prompt"})
                return
            t0 = time.time()
            image = gemini_generate(prompt, payload.get("reference"))
            _last_image = time.time()
            print(f"[gen] {_last_image - t0:5.1f}s  {prompt[:100]}")
            save_vision(image, prompt, {"mood": payload.get("mood", "")})
            self._json(200, {"image": image})
        except Exception as e:  # surfaced to the page, which degrades gracefully
            print(f"[gen] FAILED: {e}")
            self._json(500, {"error": str(e)})
        finally:
            _image_lock.release()

    def _handle_interpret(self):
        global _last_interpret
        if not API_KEY:
            self._json(503, {"error": "no API key"})
            return
        if not _interpret_lock.acquire(blocking=False):
            self._json(429, {"error": "interpret already in flight"})
            return
        try:
            if time.time() - _last_interpret < MIN_SECONDS_BETWEEN_INTERPRET:
                self._json(429, {"error": "too soon"})
                return
            payload = self._read_body()
            transcript = str(payload.get("transcript", "")).strip()
            result = gemini_interpret(transcript)
            _last_interpret = time.time()
            print(f"[brain] {result['label']}  (theme={result['theme']}, intensity={result['intensity']:.2f})")
            self._json(200, result)
        except Exception as e:
            print(f"[brain] FAILED: {e}")
            self._json(500, {"error": str(e)})
        finally:
            _interpret_lock.release()

    def log_message(self, fmt, *args):
        pass  # keep the terminal quiet; gen/brain lines are printed above


def main():
    os.chdir(Path(__file__).resolve().parent)
    print(f"Art Bell visualizer  →  http://localhost:{PORT}")
    print(f"image generation: {'ON (' + IMAGE_MODEL + ')' if API_KEY else 'OFF - no API key found'}")
    print(f"topic brain: {'ON (' + TEXT_MODEL + ')' if API_KEY else 'OFF'}")
    HTTPServer(("127.0.0.1", PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
