"""The slow-emergence control law — the signature mechanic of v3.

Spoken words never hard-cut to a picture. A new topic sets a *target*; the visual
eases toward it over ~30 s while an envelope makes the apparition GATHER (denoise
spikes so the feedback image dissolves and reforms), SETTLE (denoise falls to near
-frozen continuity), and DISSOLVE (denoise creeps back up as the reading fades),
right before the next topic gathers. Audio breathes on top; bumper music breaks
into a faster, more abstract mode.

This module owns the control-law fields on `hub.state` (prompt_a/prompt_b, blend,
denoise, seed, emergence). comfy.py reads them each generation; autolume_osc.py
(task 5) reads the same clock so substrate and dream move as one organism.
"""

from __future__ import annotations

import asyncio
import os

# atmosphere appended to every apparition prompt — evocative, dreamlike, un-literal
STYLE_SUFFIX = (
    "dark cinematic dreamscape, volumetric haze, film grain, deep shadow, "
    "analog late-night surrealism, no text, no words"
)
# steer hard away from the img2img feedback's favourite degenerate attractors
# (tiled rooms, grid floors, plaid) as well as the usual text/border junk
NEG_PROMPT = (
    "text, watermark, letters, caption, frame, border, grid, tiles, checkerboard, plaid, "
    "interior, room, ceiling, tiled floor, kitchen, low quality, blurry, jpeg artifacts"
)
REST_PROMPT = ("a vast empty nevada desert at night under an enormous starfield, a distant "
               "lone radio tower with a faint red beacon, violet haze on the horizon, still and waiting")

TICK_HZ = 25
T_TRAVEL_SPEECH = 30.0   # s to ease A->B in calm speech mode
T_TRAVEL_MUSIC = 12.0    # faster during bumper-music breaks
T_GATHER = 6.0           # s for the emergence envelope to peak
T_SETTLE = 20.0          # s for it to decay back to rest
# NB: img2img feedback loves geometric attractors (grid rooms, neon tunnels). Below ~0.45
# denoise, a static prompt lets one build and lock in. Keeping the floor here means the
# prompt reasserts every frame — looser continuity, but organic content instead of a grid.
DENOISE_REST = 0.52
DENOISE_MUSIC_REST = 0.60
DENOISE_SPAN = 0.14      # envelope adds up to this (rest is already high)
DENOISE_FLOOR = 0.46
SEED_DRIFT_SEC = 8.0
SEED_JUMP = 7            # break the form on a topic jump


def _smoothstep(x: float) -> float:
    x = max(0.0, min(1.0, x))
    return x * x * (3.0 - 2.0 * x)


def build_prompt(scene: str) -> str:
    scene = (scene or "").strip().rstrip(".")
    return f"{scene}, {STYLE_SUFFIX}" if scene else f"{REST_PROMPT}, {STYLE_SUFFIX}"


class ControlLaw:
    def __init__(self) -> None:
        self.t = 0.0
        self.mood_seq_seen = 0
        self.topic_at = -999.0     # when the current target started easing in
        self.last_seed_drift = 0.0

    def on_new_mood(self, st, mood: dict) -> None:
        # promote whatever we were easing toward, then aim at the new scene
        if st.blend > 0.35:
            st.prompt_a = st.prompt_b or st.prompt_a
        st.prompt_b = build_prompt(mood.get("scene_prompt", ""))
        st.blend = 0.0
        self.topic_at = self.t
        st.seed += SEED_JUMP     # break the current attractor so a new form coalesces

    def tick(self, st, dt: float) -> None:
        self.t += dt

        # a fresh reading landed?
        if st.mood_seq != self.mood_seq_seen and st.mood:
            self.mood_seq_seen = st.mood_seq
            self.on_new_mood(st, st.mood)

        a = st.audio
        music = a.music_mode
        t_travel = T_TRAVEL_MUSIC if music else T_TRAVEL_SPEECH
        since = self.t - self.topic_at

        # blend A -> B: smoothstep over the travel window
        st.blend = _smoothstep(since / t_travel)
        if st.blend >= 0.98 and st.prompt_b:
            st.prompt_a = st.prompt_b     # settled: B becomes the new resting form
            # keep blend high; next mood resets it

        # emergence envelope: ramp to 1 over T_GATHER, decay over T_SETTLE
        if since < T_GATHER:
            env = since / T_GATHER
        else:
            env = max(0.0, 1.0 - (since - T_GATHER) / T_SETTLE)
        st.emergence = env

        # denoise: rest continuity + envelope + audio breath + beat flicker
        base = DENOISE_MUSIC_REST if music else DENOISE_REST
        denoise = base + DENOISE_SPAN * env + 0.04 * a.bass
        if a.beat_fired:
            denoise += 0.05
        st.denoise = max(DENOISE_FLOOR, min(0.68, denoise))

        # seed: slow drift so it never dead-locks into one static image
        if self.t - self.last_seed_drift >= SEED_DRIFT_SEC:
            self.last_seed_drift = self.t
            st.seed += 1


async def control_task(hub) -> None:
    st = hub.state
    if not st.prompt_a:
        st.prompt_a = build_prompt("")   # rest scene
        st.prompt_b = st.prompt_a
    law = ControlLaw()
    dt = 1.0 / TICK_HZ
    print("[control] slow-emergence control law online")

    # optional AutoLume OSC co-drive (task 5); absent module = no-op
    osc = None
    if os.environ.get("NYE_AUTOLUME", "").lower() in ("1", "true", "on"):
        try:
            from . import autolume_osc
            osc = autolume_osc.Sender()
            print("[control] AutoLume OSC co-drive enabled")
        except Exception as e:
            print(f"[control] AutoLume OSC unavailable: {e}")

    while st.running:
        law.tick(st, dt)
        if osc is not None:
            try:
                osc.drive(st, law.t)
            except Exception:
                pass
        await asyncio.sleep(dt)
