"""The slow-emergence control law — the signature mechanic of v3.

Spoken words never hard-cut to a picture. Two things shape the dream:
  - a slow **base scene** from the topic brain (mood/palette, every ~45s), and
  - the **live words** the room is actually saying, pulled verbatim from the Whisper
    transcript (ANY evocative word, not just the 7 known themes) and injected straight
    into the prompt. A new word gives a fast "gather" pulse (denoise spikes so the dream
    reforms toward it), then settles. So you can throw quirky shit into the air and watch
    it surface.

This module owns the control-law fields on `hub.state`. comfy.py reads prompt_a/prompt_b/
blend/denoise/seed each generation; autolume_osc.py reads the same clock. It also honors
live overrides set from the browser control surface (denoise bias, reseed, OSC values).
"""

from __future__ import annotations

import asyncio
import os
import re

STYLE_SUFFIX = (
    "dark cinematic dreamscape, volumetric haze, film grain, deep shadow, "
    "analog late-night surrealism, no text, no words"
)
NEG_PROMPT = (
    "text, watermark, letters, caption, frame, border, grid, tiles, checkerboard, plaid, "
    "interior, room, ceiling, tiled floor, kitchen, low quality, blurry, jpeg artifacts"
)
REST_PROMPT = ("a vast empty nevada desert at night under an enormous starfield, a distant "
               "lone radio tower with a faint red beacon, violet haze on the horizon")

# words too common to be evocative — everything else the room says is fair game
STOPWORDS = set("""
the a an and or but so of to in on at by for with from into over under about as is are was
were be been being have has had do does did will would can could should may might must not
no yes this that these those there here it its it's i you he she we they them his her their
our your my me him us who what when where why how which than then them if because while just
really very kind sort like well okay yeah know think thing things stuff going gonna want
said says say get got getting make made makes let lets going come came now some any all more
most much many one two three them theyre youre thats whats dont cant im ive were weve
""".split())


def _smoothstep(x: float) -> float:
    x = max(0.0, min(1.0, x))
    return x * x * (3.0 - 2.0 * x)


def salient_words(text: str, keep: int = 5) -> list[str]:
    """Most-recent evocative content words from the transcript tail."""
    words = re.findall(r"[a-zA-Z']{4,}", text.lower())
    out: list[str] = []
    for w in reversed(words):          # most recent first
        w = w.strip("'")
        if w and w not in STOPWORDS and w not in out:
            out.append(w)
        if len(out) >= keep:
            break
    out.reverse()
    return out


def compose(base_scene: str, words: list[str]) -> str:
    parts = []
    if words:
        parts.append(", ".join(words))          # the literal spoken words lead
    if base_scene:
        parts.append(base_scene.strip().rstrip("."))
    body = ", ".join(parts) if parts else REST_PROMPT
    return f"{body}, {STYLE_SUFFIX}"


def build_prompt(scene: str) -> str:  # kept for comfy.py rest-state import compatibility
    return compose(scene, [])


TICK_HZ = 25
T_TRAVEL_SPEECH = 26.0
T_TRAVEL_MUSIC = 12.0
T_GATHER = 6.0
T_SETTLE = 20.0
T_WORD_GATHER = 2.5      # a freshly-heard word spikes fast...
T_WORD_DECAY = 9.0       # ...then settles
DENOISE_REST = 0.52
DENOISE_MUSIC_REST = 0.60
DENOISE_SPAN = 0.14      # topic-change envelope
DENOISE_WORD_SPAN = 0.13 # new-word pulse
DENOISE_FLOOR = 0.46
SEED_DRIFT_SEC = 8.0
SEED_JUMP = 7


class ControlLaw:
    def __init__(self) -> None:
        self.t = 0.0
        self.mood_seq_seen = 0
        self.words_seen = -1
        self.reseed_seen = 0
        self.topic_at = -999.0     # last mood change (slow travel)
        self.word_at = -999.0      # last new spoken word (fast pulse)
        self.last_seed_drift = 0.0
        self.base_scene = ""       # from the LLM mood
        self.live_words: list[str] = []

    def _rebuild_target(self, st) -> None:
        st.prompt_b = compose(self.base_scene, self.live_words)

    def on_new_mood(self, st, mood: dict) -> None:
        if st.blend > 0.35:
            st.prompt_a = st.prompt_b or st.prompt_a
        self.base_scene = mood.get("scene_prompt", "") or ""
        self._rebuild_target(st)
        st.blend = 0.0
        self.topic_at = self.t
        st.seed += SEED_JUMP

    def on_new_words(self, st, hub) -> None:
        fresh = salient_words(hub.transcript_text())
        if fresh and fresh != self.live_words:
            self.live_words = fresh
            self._rebuild_target(st)
            self.word_at = self.t                 # fire the gather pulse
            if st.blend > 0.75:
                st.blend = 0.55                   # let the updated target ease back in
            st.seed += 2
            st.vision_words = fresh               # for the on-screen "dreaming of" line
            st.vision_seq += 1

    def tick(self, st, hub, dt: float) -> None:
        self.t += dt

        if st.mood_seq != self.mood_seq_seen and st.mood:
            self.mood_seq_seen = st.mood_seq
            self.on_new_mood(st, st.mood)
        if hub.words_seen != self.words_seen:
            self.words_seen = hub.words_seen
            self.on_new_words(st, hub)
        if st.reseed_seq != self.reseed_seen:     # manual "remix" button
            self.reseed_seen = st.reseed_seq
            st.seed += SEED_JUMP + 5

        a = st.audio
        music = a.music_mode
        t_travel = T_TRAVEL_MUSIC if music else T_TRAVEL_SPEECH
        since = self.t - self.topic_at
        st.blend = _smoothstep(since / t_travel)
        if st.blend >= 0.98 and st.prompt_b:
            st.prompt_a = st.prompt_b

        # topic envelope (gather->settle) + fast word pulse
        env = (since / T_GATHER) if since < T_GATHER else max(0.0, 1.0 - (since - T_GATHER) / T_SETTLE)
        wsince = self.t - self.word_at
        wenv = (wsince / T_WORD_GATHER) if wsince < T_WORD_GATHER else max(0.0, 1.0 - (wsince - T_WORD_GATHER) / T_WORD_DECAY)
        st.emergence = max(env, wenv)

        base = DENOISE_MUSIC_REST if music else DENOISE_REST
        denoise = base + DENOISE_SPAN * env + DENOISE_WORD_SPAN * wenv + 0.04 * a.bass + st.denoise_bias
        if a.beat_fired:
            denoise += 0.05
        st.denoise = max(DENOISE_FLOOR, min(0.72, denoise))

        if self.t - self.last_seed_drift >= SEED_DRIFT_SEC:
            self.last_seed_drift = self.t
            st.seed += 1


async def control_task(hub) -> None:
    st = hub.state
    if not st.prompt_a:
        st.prompt_a = build_prompt("")
        st.prompt_b = st.prompt_a
    law = ControlLaw()
    dt = 1.0 / TICK_HZ
    vision_seen = 0
    print("[control] slow-emergence control law online (open-vocab word capture)")

    osc = None
    if os.environ.get("NYE_AUTOLUME", "").lower() in ("1", "true", "on"):
        try:
            from . import autolume_osc
            osc = autolume_osc.Sender()
            print("[control] AutoLume OSC co-drive enabled")
        except Exception as e:
            print(f"[control] AutoLume OSC unavailable: {e}")

    while st.running:
        law.tick(st, hub, dt)
        if st.vision_seq != vision_seen:          # push the current vision words to the HUD
            vision_seen = st.vision_seq
            asyncio.create_task(hub.broadcast_json({"type": "vision", "words": st.vision_words}))
        if osc is not None:
            try:
                osc.drive(st, law.t)
            except Exception:
                pass
        await asyncio.sleep(dt)
