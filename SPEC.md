# The Kingdom of Nye — Spec, Features, and Roadmap

## Vision

A living, listening backdrop for late-night Art Bell sessions. Not a screensaver:
it hears the room, feels the audio, understands what the show is talking about, and
dreams imagery to match — all locally, on your own GPU. It should feel like the
broadcast is bleeding into the walls, and like the dream is *one continuous thing*
gathering and dissolving with the conversation, never cutting.

## Architecture (v3)

```
room audio ─┬─► browser  WebAudio FFT ─► bands + spectral-flux beats ─► shader uniforms
            │                          └─► keyword scorer (7 moods, 45s decay)
            └─► conductor  faster-whisper (local STT) ─► words

                    ┌──────────────── conductor (Python / aiohttp / asyncio) ────────────────┐
  browser  ◄──WS───►│  words + Gemini /interpret mood ─► slow-emergence control law           │
  (WebGL composite) │       │                              (blend · denoise · seed clock)      │
       ▲    ▲       │       ├─► ComfyUI img2img feedback loop ─► frames ─► (proxied to browser)│
       │    │       │       └─► AutoLume OSC co-drive (optional; shares the clock)             │
       │    └─ window-capture ◄── AutoLume Perform (StyleGAN substrate video)                  │
       └───────────────────────────────────────────────────────────────────────────────────── ┘
```

- **index.html** — one self-contained page: the WebGL composite (procedural nebula as a
  shared warp field + ComfyUI apparition + AutoLume substrate, fused with soft-light,
  grain, chromatic aberration, palette tint), the audio-feature engine, the keyword
  scorer, the 2D sprite overlay, the console. Talks to the conductor over one WebSocket.
- **conductor/** — the local brain (Python, aiohttp, one asyncio loop):
  - `app.py` — static serving, `/health`, `/interpret`, the `/ws` control plane, task supervision
  - `asr.py` — faster-whisper mic tap → word deltas (with a silence-hallucination filter)
  - `brain.py` — Gemini `/interpret` mood readings (label, theme, scene, palette, intensity)
  - `control.py` — the slow-emergence control law (the signature mechanic)
  - `comfy.py` — the ComfyUI img2img feedback loop + frame proxy + black-frame guard
  - `autolume_osc.py` — AutoLume OSC co-drive (opt-in)
  - `bus.py` — shared control state + WebSocket fan-out
- **server.py** — a thin launch shim that re-execs into the project venv and starts the conductor.

## v3 (this build) — the two-engine local rewrite

The whole *pixel* layer was rebuilt; the audio + speech + topic nervous system was kept.

1. **Fully local, open-source dreaming** — cloud Gemini image generation and the
   MilkDrop/Butterchurn layer are gone. ComfyUI (DreamShaper 8 + LCM, img2img feedback)
   generates on your GPU; the only remaining cloud call is the pennies-a-night topic brain.
2. **Local Whisper STT** — faster-whisper replaces Google's Web Speech API (also frees it
   from the Chrome lock-in). Runs offline on CPU; phrase-chunked with a silence-hallucination filter.
3. **The slow-emergence control law** (`control.py`) — words seed a *target*; the visual
   eases toward it over ~30 s. A denoise envelope makes apparitions **gather → settle →
   dissolve**; a shared ~8 s seed clock and topic-ease timing move both engines as one
   organism; bass/beat/bumper-music modulate denoise, seed drift, and substrate energy.
4. **ComfyUI feedback loop** (`comfy.py`) — strictly-sequential img2img at low denoise so
   the image morphs instead of regenerating. A denoise floor plus a periodic clean-repaint
   keep the loop from diverging into grid/plaid on MPS; `--fp32-vae` + a black-frame guard
   prevent NaN poisoning. Frames arrive over the ComfyUI websocket and are proxied to the browser.
5. **AutoLume substrate** — the StyleGAN Perform output is captured into the composite via
   the browser (`V` / window-capture); OSC co-drive (`NYE_AUTOLUME=1`) steers diversity,
   noise, seed, and preset on the same clock as the apparition.
6. **New composite shader** — the procedural nebula is demoted to a shared warp field; the
   substrate and apparition are combined soft-light with a single shared post-pass (grain,
   chromatic aberration, vignette, brain-palette tint) so both read as one film stock.
7. **Interface** — a broadcast-console HUD (ON AIR indicator, mood label, signal meter,
   bumper-music badge, whispered transcript), a redesigned splash, and a v3 console
   (`C`: dream presence, substrate presence, reactivity). Own `nye3-settings` namespace.
8. **The player** — a `<audio>` element routed into the analyser (visuals) + speakers
   (so the mic-fed brain still transcribes it), with a `setSource(mic|player)` switch.
   Drag-your-own-file for real (user-owned) episodes; a bundled **CC0** "Nightwaves"
   ambience (`assets/`, generated from scratch) for instant press-play; an "episodes"
   panel linking out to the Art Bell Vault + archive.org. **No Art Bell audio is bundled
   or hosted** — it's copyrighted; the safe stack is bring-your-own + link-out + CC0 demo.

Kept from before: the FFT band engine with slow AGC and attack/release smoothing;
spectral-flux beat detection + bumper-music hysteresis; the ~140-word keyword scorer with
45 s score decay and 7 themed moods; per-theme particle bursts; the topic-brain palette fade.

## Performance (Apple Silicon / MPS)

Realistic on an M-series GPU: ~0.4–0.5 dream-fps (2–2.5 s per 512² frame, 6-step LCM). The
browser crossfades between frames and keeps the composite alive at 60 fps, so it reads as a
continuous drift. True video-rate diffusion (StreamDiffusion / TensorRT) is CUDA-only and
deliberately out of scope — the aesthetic is slow emergence, not motion.

## Roadmap

- **Confirmed AutoLume OSC address map** — read the literal addresses off a running Perform
  and lock `autolume_osc.py` to them; add GANSpace feature-direction steering by mood.
- **BlackHole loopback option** — feed both Whisper and the browser from a clean loopback of
  the show audio instead of the room mic.
- **Vision gallery** — auto-save the night's frames + prompts to `visions/YYYY-MM-DD/` and a
  `/gallery` browser to relive the trip.
- **Depth parallax** — run each apparition through a depth model, displace in the shader for
  2.5D drift inside the dream.
- **CUDA realtime path** — optional ComfyStream/WebRTC transport for true 20–30 fps when an
  NVIDIA GPU is present (local or over NDI).
- **Projector/multi-display mode** — control HUD on the laptop, clean output on the TV.

## Development invariants

- The audio + keyword + topic layer is backend-agnostic and stays that way.
- The Gemini key never reaches the browser or the repo.
- The conductor degrades gracefully: a missing subsystem (ComfyUI down, no AutoLume, no mic)
  is logged and skipped, never fatal. The composite falls back to the procedural base.
- One page, one conductor package, no build step.
