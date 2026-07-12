# The Kingdom of Nye - Spec, Features, and Roadmap

## Vision

A living, listening backdrop for late-night Art Bell sessions. Not a screensaver:
it hears the room, feels the audio, understands what the show is talking about,
and dreams imagery to match - all from one local page plus one small local
server, with honest cost controls. It should feel like the radio broadcast is
bleeding into the walls.

## Architecture

```
mic ──► WebAudio FFT ──► shader uniforms (bass/mid/treble/rms/beat)
 │
 ├──► Chrome Web Speech ──► keyword engine (instant twitch, 7 moods)
 │                     └──► rolling transcript ──► /interpret (LLM brain)
 │                                                    │
 ▼                                                    ▼
index.html (WebGL nebula + Butterchurn + 2D sprites) ◄── palette/scene/label
 │
 └──► /generate (topic + transcript + previous vision) ──► Gemini image
                    │
                    └──► visions/YYYY-MM-DD/ (auto-saved gallery)
```

- **index.html** - self-contained page: WebGL domain-warped nebula shader,
  Butterchurn (MilkDrop 2) layer, 2D sprite/caption overlay, speech recognition,
  audio analysis, settings drawer. Works standalone (file://) in degraded mode.
- **server.py** - zero-dependency stdlib server: serves the page, proxies Gemini
  (key never reaches the browser), saves the vision gallery. Key lookup:
  `$GEMINI_API_KEY` / `$GOOGLE_API_KEY` / `~/Code/rafiki/.env`.

## v1 (shipped) - feature inventory

- Audio-reactive WebGL nebula: FFT bands drive pulse, twinkle, warp; slow AGC
  keeps quiet late-night volume alive; fast-attack/slow-release smoothing.
- 7 themed moods with smooth ~8 s crossfade morphs (blended shader params):
  Kingdom of Nye, Visitors, The Adversary, Restless Spirits, Shadow Government,
  Something in the Woods, Down the Wormhole. Per-theme particle systems
  (saucers + beams, embers + sigils, orbs + wisps, redaction bars + radar,
  eyes in the woods, warp streaks, radio ripples).
- Topic detection: continuous Chrome speech recognition, ~140 keyword/phrase
  triggers, score decay (45 s half-life) so moods follow the conversation.
- Heard trigger words drift across the screen as ghostly captions.
- Generative dream layer: Gemini `gemini-2.5-flash-image` visions of what the
  show is discussing, melted into the shader (domain-warped by bass, slow Ken
  Burns, ping-pong crossfade between last two visions).
- Cost control: topic-change-triggered generation (25 s debounce) + 4 min
  ambient refresh, ~$0.04/image, ~$0.30-0.60/evening, 80-image hard cap,
  live HUD cost ticker.
- Keys: F fullscreen, 1-7 pin mood, 0 auto, G dream layer, S spectrum overlay.
- Graceful degradation: no server -> shader-only; no mic -> demo auto-drift.

## v2 (this build)

1. **LLM topic brain** - `/interpret`: every ~45 s the rolling transcript goes to
   `gemini-2.5-flash-lite` (JSON mode) which returns a mood label, an optional
   base-theme anchor, a custom scene prompt, a 3-color palette, and intensity.
   The visuals can now follow ANY topic - shadow people, near-death experiences,
   numbers stations - not just the 7 hardcoded moods. Keyword engine remains as
   the instant-reaction layer between brain ticks. Cost: pennies/night.
2. **Beat detection** - spectral-flux onset detection over the existing FFT
   (rolling mean+std threshold, refractory period). Beats kick the shader
   (`u_beat`: zoom punch, brightness, star flare) and fire particle bursts.
3. **Bumper-music mode** - sustained periodic beats flip `musicMode`:
   reactivity cranks up and the Butterchurn layer surges. Art's bumper music
   becomes the peak of the trip.
4. **Butterchurn (MilkDrop 2) layer** - the legendary Winamp visualizer engine,
   vendored (~1 MB static JS), fed by the same mic audio graph, blended between
   nebula and sprites. Presets rotate on mood change; `B` cycles; opacity rides
   music mode + settings. Skipped gracefully if the vendored files are absent.
5. **Dream continuity** - each generation sends the previous vision as a Gemini
   reference image, so the night becomes one continuously evolving hallucination
   instead of disconnected slides.
6. **Vision gallery** - every dream auto-saved to `visions/YYYY-MM-DD/` with a
   JSON sidecar (prompt, mood, time). Wake up to the night's trip log.
7. **Settings drawer** (`C`) - dream cadence, dream opacity, reactivity,
   session cap, Butterchurn blend, continuity toggle; persisted in localStorage.
8. **HUD upgrades** - beat dot, music-mode badge, brain mood label.

## Cost model

| Thing | Cost |
|-------|------|
| Topic brain (`flash-lite`, ~1 call/45 s) | ~$0.01-0.03 / night |
| Visions (`flash-image`, topic-triggered) | ~$0.04 each, ~$0.30-0.60 / night |
| Hard cap | 80 images (~$3.12), adjustable in settings |
| Butterchurn, beats, shader | free, local |

## v3+ roadmap

- **Live Dream mode** - fal.ai realtime SDXL/LCM img2img (~$0.002/image over a
  websocket): continuous ~0.2-1 fps morphing of the current frame. A living
  painting. ~$1-4/hr, needs a fal.ai account; off by default.
- **Local Whisper transcription** - mlx-whisper on Apple Silicon replaces Web
  Speech: better accuracy on AM-radio audio, works offline, no Chrome dependency.
- **Depth parallax** - run each vision through a depth model, displace in the
  shader for 2.5D camera drift inside the dream.
- **Veo video dreams** - short generated video loops per mood. Flagged: video
  generation runs ~$0.40+/second; strictly opt-in.
- **Vision gallery browser** - a `/gallery` page: browse past nights, prompts,
  and moods; export a "trip report".
- **WebGPU port** - compute-shader particles and higher-res noise once WebGPU
  is worth the migration.
- **Projector/multi-display mode** - control HUD on the laptop, clean output on
  the TV/projector via a second window.
- **Séance rooms** - WebRTC sync so a remote friend sees the same trip while
  you listen together on a call.

## Development invariants

- The page must always work standalone (file://) with no server: shader,
  keywords, particles, spectrum. Every network feature degrades gracefully.
- The API key never reaches the browser or the repo.
- Every recurring cost is visible in the HUD and capped by default.
- One page, one server file, vendored static JS only - no build step, ever.
