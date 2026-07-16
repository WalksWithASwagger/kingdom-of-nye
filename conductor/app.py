"""The conductor process — one aiohttp app hosting the whole v3 backend.

Routes (browser-facing):
  GET  /health     -> {ok, genai}                     (unchanged contract)
  POST /interpret  -> run the topic brain now, return the mood  (test/override hook)
  GET  /ws         -> control plane: browser streams audio up; we push
                      words / mood / status / binary dream frames down
  GET  /*          -> static files (index.html at /)

Background tasks are started opportunistically: each subsystem (brain, asr, comfy,
control) is imported lazily and supervised, so a missing module or a down engine
(ComfyUI not running yet) never takes the server with it.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from aiohttp import WSMsgType, web

from . import brain
from .bus import Hub

HERE = Path(__file__).resolve().parent.parent
PORT = 8765

# name -> "module:task_fn"; started if importable, supervised if it throws
SUBSYSTEMS = {
    "brain": "conductor.brain:brain_task",
    "asr": "conductor.asr:asr_task",
    "control": "conductor.control:control_task",
    "comfy": "conductor.comfy:comfy_task",
}


@web.middleware
async def cors_and_nocache(request, handler):
    if request.method == "OPTIONS":
        resp = web.Response(status=204)
    else:
        resp = await handler(request)
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
    resp.headers["Cache-Control"] = "no-store"
    return resp


async def health(request):
    return web.json_response({"ok": True, "genai": brain.API_KEY is not None})


async def interpret(request):
    """Manual topic read. Optional {transcript} seeds the rolling buffer first."""
    hub: Hub = request.app["hub"]
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    transcript = str(payload.get("transcript", "")).strip()
    if transcript:
        hub.push_words(transcript)
    result = await brain.read_now(hub)
    if result is None:
        return web.json_response({"error": "no API key or interpret failed"}, status=503)
    return web.json_response(result)


async def ws_handler(request):
    hub: Hub = request.app["hub"]
    ws = web.WebSocketResponse(heartbeat=20)
    await ws.prepare(request)
    hub.add(ws)
    await ws.send_json({"type": "status", "msg": "conductor connected",
                        "genai": brain.API_KEY is not None})
    try:
        async for msg in ws:
            if msg.type != WSMsgType.TEXT:
                continue
            try:
                data = msg.json()
            except Exception:
                continue
            if data.get("type") == "audio":
                try:
                    a = hub.state.audio
                    a.bass = float(data.get("bass", 0.0))
                    a.mid = float(data.get("mid", 0.0))
                    a.treble = float(data.get("treble", 0.0))
                    a.rms = float(data.get("rms", 0.0))
                    a.beat = float(data.get("beat", 0.0))
                    a.beat_fired = bool(data.get("beatFired", False))
                    a.music_mode = bool(data.get("musicMode", False))
                    a.target = str(data.get("target", "nye"))
                    a.ts = float(data.get("ts", 0.0))
                except (TypeError, ValueError):
                    continue  # one malformed frame shouldn't drop the control plane
    finally:
        hub.remove(ws)
    return ws


async def static_handler(request):
    rel = request.match_info.get("path") or "index.html"
    target = (HERE / rel).resolve()
    if not str(target).startswith(str(HERE)) or not target.is_file():
        raise web.HTTPNotFound()
    return web.FileResponse(target)


async def _supervise(name: str, task_fn, hub: Hub):
    """Run a subsystem, restarting it with capped backoff so a crash can't disable it
    for the whole session. A clean return means the task is done by design (e.g. no API
    key) and is NOT restarted; only exceptions trigger a restart."""
    backoff = 1.0
    while hub.state.running:
        try:
            await task_fn(hub)
            return  # finished on purpose
        except asyncio.CancelledError:
            raise
        except Exception as e:
            print(f"[{name}] crashed: {type(e).__name__}: {e}; restarting in {backoff:.0f}s")
            await asyncio.sleep(backoff)
            backoff = min(30.0, backoff * 2)


def _load_task(spec: str):
    import importlib
    mod_name, fn_name = spec.split(":")
    try:
        mod = importlib.import_module(mod_name)
    except Exception as e:
        return None, f"module unavailable ({type(e).__name__})"
    fn = getattr(mod, fn_name, None)
    if fn is None:
        return None, "task fn missing"
    return fn, None


async def on_startup(app):
    hub: Hub = app["hub"]
    app["tasks"] = []
    for name, spec in SUBSYSTEMS.items():
        fn, err = _load_task(spec)
        if fn is None:
            print(f"[{name}] not started — {err}")
            continue
        app["tasks"].append(asyncio.create_task(_supervise(name, fn, hub)))
        print(f"[{name}] started")


async def on_cleanup(app):
    app["hub"].state.running = False
    for t in app.get("tasks", []):
        t.cancel()
    for t in app.get("tasks", []):
        try:
            await t
        except asyncio.CancelledError:
            pass


def build_app() -> web.Application:
    app = web.Application(middlewares=[cors_and_nocache])
    app["hub"] = Hub()
    app.router.add_get("/health", health)
    app.router.add_post("/interpret", interpret)
    app.router.add_get("/ws", ws_handler)
    app.router.add_get("/", static_handler)
    app.router.add_get("/{path:.*}", static_handler)
    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)
    return app


def main():
    print(f"Kingdom of Nye v3 conductor  →  http://localhost:{PORT}")
    print(f"topic brain: {'ON (' + brain.TEXT_MODEL + ')' if brain.API_KEY else 'OFF - no API key'}")
    web.run_app(build_app(), host="127.0.0.1", port=PORT, print=None)


if __name__ == "__main__":
    main()
