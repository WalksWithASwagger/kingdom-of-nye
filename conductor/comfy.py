"""ComfyUI generation loop — the apparition engine.

Owns the ComfyUI WebSocket, runs a strictly-sequential img2img feedback loop, and
proxies each finished frame to the browser. Each iteration:
  read control-law params -> build graph (prev frame as base64 feedback) ->
  POST /prompt -> await the decoded frame off the ws -> guard against black frames
  -> feed it back as next input + broadcast it to the browser.

Queue depth is 1 and the loop self-clocks on frame arrival, so it paces to whatever
MPS delivers (~1-2 fps) without ever running ahead of the feedback chain.

Graph nodes use comfyui-tooling-nodes: ETN_LoadImageBase64 (feedback in) and
ETN_SendImageWebSocket (frame out) — no disk round-trip, no filename cache issues.
"""

from __future__ import annotations

import asyncio
import base64
import os

import aiohttp

from .control import NEG_PROMPT

COMFY_HTTP = os.environ.get("NYE_COMFY_HTTP", "http://127.0.0.1:8188")
COMFY_WS = COMFY_HTTP.replace("http", "ws", 1) + "/ws"

WIDTH = int(os.environ.get("NYE_COMFY_W", "512"))
HEIGHT = int(os.environ.get("NYE_COMFY_H", "512"))
# DreamShaper 8 with LCM baked in — characterful/dreamlike, few-step, no separate LoRA
CKPT = os.environ.get("NYE_COMFY_CKPT", "DreamShaper8_LCM.safetensors")
LORA = os.environ.get("NYE_COMFY_LORA", "")  # "" = none (LCM is in the checkpoint)
# 4 steps: DreamShaper-LCM looks great here and it's ~a third faster than 6 — matters
# because the browser (WebGL) + AutoLume (StyleGAN) share this GPU with the diffusion
STEPS = int(os.environ.get("NYE_COMFY_STEPS", "4"))
CFG = float(os.environ.get("NYE_COMFY_CFG", "2.0"))
SAMPLER = os.environ.get("NYE_COMFY_SAMPLER", "lcm")
SCHED = os.environ.get("NYE_COMFY_SCHED", "sgm_uniform")
# defense-in-depth: every N frames, cold-start from noise to flush any slow grid/VAE
# accumulation the denoise floor didn't fully suppress (browser crossfade hides the cut)
REFRESH_EVERY = int(os.environ.get("NYE_COMFY_REFRESH", "24"))

_FRAME_TIMEOUT = 45.0


def build_graph(st, prev_b64: str | None) -> dict:
    g: dict = {}
    g["10"] = {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": CKPT}}
    if LORA:
        g["11"] = {"class_type": "LoraLoader", "inputs": {
            "model": ["10", 0], "clip": ["10", 1], "lora_name": LORA,
            "strength_model": 1.0, "strength_clip": 1.0}}
        model_ref, clip_ref = ["11", 0], ["11", 1]
    else:
        model_ref, clip_ref = ["10", 0], ["10", 1]

    g["20"] = {"class_type": "CLIPTextEncode", "inputs": {"clip": clip_ref, "text": st.prompt_a}}
    g["21"] = {"class_type": "CLIPTextEncode", "inputs": {"clip": clip_ref, "text": st.prompt_b or st.prompt_a}}
    g["22"] = {"class_type": "ConditioningAverage", "inputs": {
        "conditioning_to": ["21", 0], "conditioning_from": ["20", 0],
        "conditioning_to_strength": round(float(st.blend), 3)}}
    g["23"] = {"class_type": "CLIPTextEncode", "inputs": {"clip": clip_ref, "text": NEG_PROMPT}}

    if prev_b64:
        g["30"] = {"class_type": "ETN_LoadImageBase64", "inputs": {"image": prev_b64}}
        g["31"] = {"class_type": "VAEEncode", "inputs": {"pixels": ["30", 0], "vae": ["10", 2]}}
        latent, denoise = ["31", 0], round(float(st.denoise), 3)
    else:
        g["32"] = {"class_type": "EmptyLatentImage", "inputs": {
            "width": WIDTH, "height": HEIGHT, "batch_size": 1}}
        latent, denoise = ["32", 0], 1.0  # cold start: paint from noise

    g["40"] = {"class_type": "KSampler", "inputs": {
        "model": model_ref, "positive": ["22", 0], "negative": ["23", 0],
        "latent_image": latent, "seed": int(st.seed), "steps": STEPS, "cfg": CFG,
        "sampler_name": SAMPLER, "scheduler": SCHED, "denoise": denoise}}
    g["41"] = {"class_type": "VAEDecode", "inputs": {"samples": ["40", 0], "vae": ["10", 2]}}
    g["50"] = {"class_type": "ETN_SendImageWebSocket", "inputs": {"images": ["41", 0], "format": "PNG"}}
    return g


def _strip_header(data: bytes) -> bytes:
    """ComfyUI binary previews carry an 8-byte header; slice to the image magic."""
    for magic in (b"\x89PNG", b"\xff\xd8\xff"):
        i = data.find(magic, 0, 16)
        if i != -1:
            return data[i:]
    return data[8:]  # fallback: standard 4-byte type + 4-byte format header


def _is_black(png: bytes) -> bool:
    try:
        import io
        from PIL import Image
        import numpy as np
        im = Image.open(io.BytesIO(png)).convert("L")
        return float(np.asarray(im).mean()) < 2.0
    except Exception:
        return False  # can't check -> assume fine (fp32-vae already guards NaNs)


async def _wait_for_comfy(session) -> bool:
    for _ in range(120):  # up to ~2 min while ComfyUI boots + loads the model
        try:
            async with session.get(COMFY_HTTP + "/", timeout=aiohttp.ClientTimeout(total=3)) as r:
                if r.status == 200:
                    return True
        except Exception:
            pass
        await asyncio.sleep(1.0)
    return False


async def _await_frame(ws) -> bytes | None:
    """Read ws until the decoded output frame arrives (no previews are enabled)."""
    try:
        async with asyncio.timeout(_FRAME_TIMEOUT):
            async for msg in ws:
                if msg.type == aiohttp.WSMsgType.BINARY:
                    return _strip_header(msg.data)
                if msg.type == aiohttp.WSMsgType.TEXT:
                    import json
                    data = json.loads(msg.data)
                    if data.get("type") == "execution_error":
                        print(f"[comfy] execution error: {data.get('data')}")
                        return None
                if msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                    return None
    except (TimeoutError, asyncio.TimeoutError):
        print("[comfy] frame timeout")
    return None


async def comfy_task(hub) -> None:
    """Generate frames forever, surviving ComfyUI restarts / ws drops by reconnecting.

    Outer loop = (re)connect; inner loop = the feedback generation loop. Any POST
    failure, closed ws, or repeated frame miss breaks out to reconnect with backoff
    rather than silently wedging or busy-spinning prompts into a dead ComfyUI.
    """
    import uuid
    client_id = uuid.uuid4().hex
    prev_b64: str | None = None
    last_good: bytes | None = None
    gen = 0
    async with aiohttp.ClientSession() as session:
        while hub.state.running:
            print(f"[comfy] connecting to ComfyUI at {COMFY_HTTP} …")
            if not await _wait_for_comfy(session):
                await asyncio.sleep(3.0)
                continue
            print(f"[comfy] connected (ckpt={CKPT}, lora={LORA or 'none'}, "
                  f"{STEPS} steps, {SAMPLER}/{SCHED}, cfg={CFG})")
            prev_b64 = None  # fresh feedback chain on every (re)connect
            fails = 0
            try:
                async with session.ws_connect(f"{COMFY_WS}?clientId={client_id}",
                                              max_msg_size=32 * 1024 * 1024,
                                              heartbeat=20) as ws:
                    while hub.state.running:
                        if REFRESH_EVERY and gen and gen % REFRESH_EVERY == 0:
                            prev_b64 = None  # periodic clean repaint from the prompt
                        graph = build_graph(hub.state, prev_b64)
                        try:
                            async with session.post(
                                    COMFY_HTTP + "/prompt",
                                    json={"prompt": graph, "client_id": client_id},
                                    timeout=aiohttp.ClientTimeout(total=15)) as r:
                                if r.status != 200:
                                    print(f"[comfy] /prompt {r.status}: {(await r.text())[:200]}")
                                    fails += 1
                                    if fails > 5:
                                        break  # comfy likely unhealthy -> reconnect
                                    await asyncio.sleep(min(8, 1.5 * fails))
                                    continue
                        except (aiohttp.ClientError, asyncio.TimeoutError, TimeoutError) as e:
                            print(f"[comfy] POST failed ({type(e).__name__}) -> reconnect")
                            break

                        frame = await _await_frame(ws)
                        if frame is None:
                            if ws.closed:
                                print("[comfy] ws closed -> reconnect")
                                break
                            fails += 1
                            if fails > 5:
                                break  # stop spinning; reconnect fresh
                            continue
                        fails = 0

                        if _is_black(frame):
                            if last_good is None:
                                continue  # nothing good yet; try again from noise
                            frame = last_good  # drop poisoned frame, reuse last good
                        else:
                            last_good = frame

                        prev_b64 = base64.b64encode(frame).decode("ascii")
                        gen += 1
                        await hub.broadcast_bytes(frame)
            except Exception as e:
                print(f"[comfy] connection error ({type(e).__name__}: {e}) -> reconnect")
            if hub.state.running:
                await asyncio.sleep(2.0)  # backoff before reconnecting
