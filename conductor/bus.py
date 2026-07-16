"""Shared state + a tiny WebSocket fan-out hub.

Everything the conductor's async tasks read/write lives on one `Hub`:
  - `state` — the fused control state (audio in, mood in, control-law out)
  - the set of connected browser sockets, with json/binary broadcast helpers
  - the rolling transcript (fed by Whisper, read by the topic brain)

There is deliberately no locking around `state`: the whole conductor runs on one
asyncio event loop, so field reads/writes between tasks are already serialized.
The only blocking work (Whisper, Gemini, torch) is pushed to executor threads and
hands results back as plain assignments on the loop.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field


@dataclass
class AudioFeatures:
    """Per-frame features the browser computes and streams up at ~15 Hz."""
    bass: float = 0.0
    mid: float = 0.0
    treble: float = 0.0
    rms: float = 0.0
    beat: float = 0.0
    beat_fired: bool = False
    music_mode: bool = False
    target: str = "nye"   # the browser's current keyword-scored theme
    ts: float = 0.0       # browser clock, seconds


@dataclass
class ControlState:
    audio: AudioFeatures = field(default_factory=AudioFeatures)

    # last topic-brain reading (the /interpret contract), + when it landed
    mood: dict | None = None
    mood_at: float = 0.0
    mood_seq: int = 0     # bumps on every new reading; control.py watches this

    # --- slow-emergence control law (owned by control.py) ---
    prompt_a: str = ""    # settled apparition
    prompt_b: str = ""    # incoming apparition
    blend: float = 0.0    # 0..1 ease from A -> B (smoothstep over T_travel)
    denoise: float = 0.25 # feedback repaint strength (near-frozen at rest)
    seed: int = 1
    emergence: float = 0.0  # gather->settle->dissolve envelope, 0..1

    # open-vocab words currently woven into the dream (for the on-screen "dreaming of")
    vision_words: list = field(default_factory=list)
    vision_seq: int = 0

    # live overrides from the browser control surface
    denoise_bias: float = 0.0                                   # morph slider
    reseed_seq: int = 0                                         # remix button
    osc_manual: dict = field(default_factory=dict)             # AutoLume slider values

    running: bool = True


class Hub:
    def __init__(self) -> None:
        self.state = ControlState()
        self.transcript: list[str] = []   # rolling finalized speech fragments
        self.words_seen = 0               # monotonic fragment count (the brain's gate)
        self._clients: set = set()

    # -- client registry --
    def add(self, ws) -> None:
        self._clients.add(ws)

    def remove(self, ws) -> None:
        self._clients.discard(ws)

    @property
    def client_count(self) -> int:
        return len(self._clients)

    # -- fan-out --
    async def broadcast_json(self, obj: dict) -> None:
        if not self._clients:
            return
        data = json.dumps(obj)
        await self._send_all(lambda ws: ws.send_str(data))

    async def broadcast_bytes(self, payload: bytes) -> None:
        if not self._clients:
            return
        await self._send_all(lambda ws: ws.send_bytes(payload))

    async def _send_all(self, send) -> None:
        # fan out concurrently with a per-client timeout: one stalled socket (sleeping
        # laptop, congested wifi) must not block frames to everyone else
        clients = list(self._clients)
        if not clients:
            return

        async def _one(ws):
            try:
                await asyncio.wait_for(send(ws), timeout=2.0)
                return None
            except Exception:
                return ws  # timed out or errored -> evict

        for ws in await asyncio.gather(*[_one(ws) for ws in clients]):
            if ws is not None:
                self._clients.discard(ws)

    # -- transcript (Whisper writes, brain reads) --
    def push_words(self, text: str, keep: int = 8) -> None:
        text = text.strip()
        if text:
            self.transcript.append(text)
            self.words_seen += 1
            del self.transcript[:-keep]

    def transcript_text(self) -> str:
        return " ".join(self.transcript)
