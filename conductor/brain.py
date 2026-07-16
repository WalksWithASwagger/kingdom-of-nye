"""Topic brain — Gemini reads the rolling transcript and designs the mood.

This is the one cloud call in v3 (Kris chose the hybrid brain): local Whisper for
speech, a pennies-a-night Gemini flash-lite call for naming the mood. The contract
is unchanged from v2 — {label, theme, scene_prompt, palette, intensity} — so the
browser's palette/label machinery keeps working verbatim; it just arrives pushed
over the WebSocket instead of pulled from POST /interpret.

The gemini_* helpers are ported near-verbatim from the v2 server.py (blocking
urllib); brain_task wraps them in an executor so the event loop never stalls.
"""

from __future__ import annotations

import asyncio
import json
import os
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
LOCAL_ENV = HERE / ".env"
RAFIKI_ENV = Path.home() / "Code" / "rafiki" / ".env"

TEXT_MODEL = "gemini-flash-lite-latest"
INTERVAL = 45          # seconds between readings
THEMES = ("nye", "aliens", "demons", "ghosts", "gov", "cryptids", "time")

BRAIN_PROMPT = """You are the visual director for a live visualizer running \
behind old Art Bell / Coast to Coast AM radio episodes. Below is a rough live \
transcript fragment (speech-to-text, may be garbled). Decide what the \
conversation is about and design the visual mood.

Respond with ONLY a JSON object:
{
  "label": "short evocative lowercase mood name, max 5 words",
  "theme": "one of: nye aliens demons ghosts gov cryptids time, or null if none fits",
  "scene_prompt": "one vivid sentence of ATMOSPHERE for a diffusion model: light, \
color, texture, weather, a felt presence -- evocative not literal, no proper nouns, \
no named objects (say 'a cold amber glow at the desert's edge', not 'a UFO')",
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


def _gemini_call(model: str, body: dict) -> dict:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", "x-goog-api-key": API_KEY},
    )
    with urllib.request.urlopen(req, timeout=90) as resp:
        return json.loads(resp.read().decode("utf-8"))


def interpret(transcript: str) -> dict:
    """Blocking: transcript -> sanitized mood dict. Ported from v2 gemini_interpret."""
    body = {
        "contents": [{"parts": [{"text": BRAIN_PROMPT + transcript[:4000]}]}],
        "generationConfig": {"responseMimeType": "application/json"},
    }
    data = _gemini_call(TEXT_MODEL, body)
    raw = data["candidates"][0]["content"]["parts"][0]["text"]
    out = json.loads(raw)

    label = str(out.get("label", ""))[:60] or "the kingdom of nye"
    theme = out.get("theme")
    if theme not in THEMES:
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


async def read_now(hub, loop=None) -> dict | None:
    """Run one interpret against the current transcript, publish it, return it."""
    if not API_KEY:
        return None
    loop = loop or asyncio.get_running_loop()
    transcript = hub.transcript_text()
    try:
        result = await loop.run_in_executor(None, interpret, transcript)
    except Exception as e:
        print(f"[brain] FAILED: {e}")
        return None
    hub.state.mood = result
    hub.state.mood_at = loop.time()
    hub.state.mood_seq += 1
    await hub.broadcast_json({"type": "mood", **result})
    print(f"[brain] {result['label']}  (theme={result['theme']}, "
          f"intensity={result['intensity']:.2f})")
    return result


async def brain_task(hub) -> None:
    """Every INTERVAL seconds, if new words were heard, read the mood.

    Gates on hub.words_seen (monotonic) rather than transcript length — the rolling
    buffer plateaus, so a length check would freeze the mood mid-show. The watermark
    only advances on a SUCCESSFUL read, so a transient Gemini failure is retried."""
    if not API_KEY:
        print("[brain] no API key — mood naming disabled (visuals still run)")
        return
    loop = asyncio.get_running_loop()
    seen = -1
    while hub.state.running:
        await asyncio.sleep(INTERVAL)
        if not hub.transcript or hub.words_seen == seen:
            continue  # nothing new said; don't spend a call
        result = await read_now(hub, loop)
        if result is not None:
            seen = hub.words_seen  # advance only after a successful reading
