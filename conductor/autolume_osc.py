"""AutoLume OSC co-drive — steers the StyleGAN substrate on the SAME clock as the
ComfyUI apparition, so the two engines gather and dissolve as one organism.

AutoLume (v2.17-rc1, /Applications/Autolume.app) exposes its Perform parameters over
OSC on **port 1338** (confirmed on this machine). Each parameter's OSC address is set
in the app: click the parameter name on the Perform screen -> "Use OSC" popup. So the
address strings below are placeholders you MUST reconcile with your app's bindings —
override them via the NYE_OSC_* env vars (or just bind the app's params to these names).
On startup this module prints exactly what it will send so you can match them live.

The *mapping* (what audio/mood drives what) is the fixed, considered part; only the
literal addresses + range scaling are instance-specific.

Enable with NYE_AUTOLUME=1 (control.py picks it up). Off by default — window-capture
of the Perform output (browser `V` key) is independent of this and needs no OSC.
"""

from __future__ import annotations

import os

OSC_IP = os.environ.get("NYE_AUTOLUME_IP", "127.0.0.1")
OSC_PORT = int(os.environ.get("NYE_AUTOLUME_PORT", "1338"))  # AutoLume v2.17-rc1 default

# OSC addresses — RECONCILE with your AutoLume "Use OSC" bindings (see module docstring)
ADDR = {
    "diversity": os.environ.get("NYE_OSC_DIVERSITY", "/diversity"),
    "noise": os.environ.get("NYE_OSC_NOISE", "/noise"),
    "seed": os.environ.get("NYE_OSC_SEED", "/seed"),
    "rotation": os.environ.get("NYE_OSC_ROTATION", "/rotation"),
    "translate_x": os.environ.get("NYE_OSC_TRANSX", "/translate_x"),
    "translate_y": os.environ.get("NYE_OSC_TRANSY", "/translate_y"),
    "preset": os.environ.get("NYE_OSC_PRESET", "/preset"),
}

SEND_HZ = 20.0


class Sender:
    def __init__(self) -> None:
        from pythonosc.udp_client import SimpleUDPClient
        self.client = SimpleUDPClient(OSC_IP, OSC_PORT)
        self._last_send = 0.0
        self._last_seed = None
        self._last_theme = None
        print(f"[osc] AutoLume co-drive -> {OSC_IP}:{OSC_PORT}")
        print("[osc] sending on these addresses (match them in AutoLume's 'Use OSC' popups):")
        for name, addr in ADDR.items():
            print(f"[osc]   {addr:16s} <- {name}")

    def drive(self, st, t: float) -> None:
        # seed steps on the SAME ~8s clock as the ComfyUI seed -> substrate & dream
        # break their forms together
        if st.seed != self._last_seed:
            self._last_seed = st.seed
            self.client.send_message(ADDR["seed"], int(st.seed))

        # preset switches by theme on a new mood reading -> substrate follows the topic
        theme = (st.mood or {}).get("theme") if st.mood else None
        if theme and theme != self._last_theme:
            self._last_theme = theme
            self.client.send_message(ADDR["preset"], str(theme))

        if t - self._last_send < 1.0 / SEND_HZ:
            return
        self._last_send = t

        a = st.audio
        intensity = (st.mood or {}).get("intensity", 0.5) if st.mood else 0.5
        music_boost = 0.6 if a.music_mode else 0.0
        man = st.osc_manual  # live slider overrides from the control surface

        # a manual slider takes over that knob; otherwise it's audio-driven
        diversity = man["diversity"] if "diversity" in man \
            else max(0.0, min(2.0, intensity * (0.6 + a.rms) + a.bass * 0.5))
        noise = man["noise"] if "noise" in man \
            else max(0.0, min(2.0, a.bass + music_boost + 0.15 * a.mid))
        self.client.send_message(ADDR["diversity"], float(diversity))
        self.client.send_message(ADDR["noise"], float(noise))

        # beats kick the latent through layer transforms
        if a.beat_fired:
            self.client.send_message(ADDR["rotation"], float(a.beat * 0.15))
            self.client.send_message(ADDR["translate_x"], float((a.bass - 0.5) * 0.1))
            self.client.send_message(ADDR["translate_y"], float((a.treble - 0.5) * 0.1))
