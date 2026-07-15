# The Kingdom of Nye — v3

A local, open-source, **audio- and speech-reactive** visualizer for late-night
[Art Bell](https://en.wikipedia.org/wiki/Art_Bell) / Coast to Coast AM sessions. It
listens to the room, understands what the show is about, and paints a slow, evolving
hallucination to match — entirely on your own machine, no cloud image models.

Two minds dreaming together on one film stock:

- **ComfyUI** is the **apparition engine** — a Stable Diffusion img2img *feedback loop*.
  The spoken words never cut to a literal picture; they seed a drift. Art says "shadow
  people at the foot of the bed" and over ~30 seconds the visual field *gathers* toward
  it, holds, and dissolves. Evocative, not illustrative.
- **AutoLume** (optional) is the **subconscious substrate** — a continuously morphing
  StyleGAN latent field, steered live over OSC and folded in underneath the apparitions.
- A single WebGL **composite** fuses them — shared warp field, soft-light blend, one film
  grain, chromatic aberration on the bass — so it reads as *one* dream, not stacked layers.

The old MilkDrop/Y2K look is gone. Your GPU does the dreaming.

## What you need

- **Apple Silicon Mac** (built and tuned on an M4 Max; any recent M-series works) or a
  CUDA box. Metal/MPS is fine — this is designed around a "slow and gorgeous", not
  video-rate, generation loop.
- **[ComfyUI](https://github.com/comfyanonymous/ComfyUI)** running locally, with:
  - a checkpoint — default is **DreamShaper 8 (LCM baked in)**, `DreamShaper8_LCM.safetensors`
    from [Lykon/DreamShaper](https://huggingface.co/Lykon/DreamShaper) → `models/checkpoints/`
  - the **[comfyui-tooling-nodes](https://github.com/Acly/comfyui-tooling-nodes)** custom node
    (base64 image in / websocket image out)
- **Python 3** (a project venv is created automatically on first run).
- **A Gemini API key** for the topic "mood" brain — the one hybrid piece (pennies/night).
  Drop it in `.env` next to `server.py`: `echo 'GEMINI_API_KEY=…' > .env`
- **[AutoLume](https://www.metacreation.net/autolume)** — optional, only for the substrate layer.

## Run it

**One command** (starts ComfyUI if needed + the conductor, then opens the browser):

```bash
./start.sh
# override paths: NYE_COMFYUI_DIR=/path/to/ComfyUI  NYE_BROWSER="Google Chrome"  ./start.sh
```

Or start the pieces by hand:

```bash
# 1. ComfyUI (Apple Silicon flags — fp32 VAE avoids black-frame NaNs in the loop)
cd /path/to/ComfyUI
.venv/bin/python main.py --force-fp16 --use-pytorch-cross-attention --fp32-vae

# 2. the conductor (creates its venv + installs deps on first run)
cd /path/to/kingdom-of-nye
python3 server.py            # → http://localhost:8765
```

Open **http://localhost:8765**, click **TUNE IN**, allow the mic, and **play the show out
loud**. Press `F` for fullscreen and let it ride. The mic hears the room, so nothing needs
to be wired together — YouTube, archive.org, VLC, whatever.

For the AutoLume substrate: launch AutoLume **Perform**, then press **`V`** in the browser
and pick its window. To drive AutoLume live over OSC too, run the conductor with
`NYE_AUTOLUME=1` (see `conductor/autolume_osc.py` for the address map).

## Keys

| Key | Does |
|-----|------|
| `F` | fullscreen |
| `1`–`7` | pin a mood (Nye, aliens, demons, ghosts, government, cryptids, wormhole) |
| `0` | back to automatic (follow the conversation) |
| `←` / `→` | step through the moods |
| `V` | capture / release the AutoLume window as the substrate |
| `G` | pause / resume the dream layer |
| `S` | live spectrum overlay (see the audio reactivity raw) |
| `P` | capture the current frame as a PNG |
| `H` | hide / show the console (clean projection) |
| `C` | the console (dream presence, substrate presence, reactivity) |
| `?` | show all controls · `Esc` closes |

## How it works

```
room audio ─┬─► browser: WebAudio FFT ─► bands + spectral-flux beats ─► shader + keyword scorer
            └─► conductor: faster-whisper (local STT) ─► words

                       ┌──────────────── conductor (Python, one asyncio loop) ───────────────┐
   browser ◄──WS──────►│  words + Gemini mood  ──►  slow-emergence control law                │
   (WebGL composite)   │        │                     (blend · denoise · seed clock)           │
        ▲   ▲          │        └──► ComfyUI img2img feedback loop ──► frames ──► (proxied back)│
        │   │          │        └──► AutoLume OSC co-drive (optional, shares the same clock)    │
        │   └──NDI/window-capture◄── AutoLume Perform (StyleGAN substrate)                      │
        └─────────────────────────────────────────────────────────────────────────────────────┘
```

- **The browser** owns real-time audio features (FFT bands, spectral-flux beat detection,
  bumper-music mode) and all rendering. It streams those features up and receives words,
  mood, and dream frames back over one WebSocket.
- **The conductor** (`conductor/`) owns words (local Whisper), mood (Gemini `/interpret`
  — label, theme, scene, palette, intensity), generation (ComfyUI), and substrate steering
  (AutoLume OSC). It runs everything on a single asyncio loop; the blocking bits (Whisper,
  Gemini) go to executor threads.
- **The slow-emergence control law** (`conductor/control.py`) is the signature mechanic. A
  new topic sets a *target* prompt; the visual eases toward it over ~30 s (smoothstep). A
  denoise envelope makes each apparition **gather → settle → dissolve**; a shared ~8 s seed
  clock drifts both engines together; bass, beats, and bumper-music bend it all in real time.
- **The feedback loop** (`conductor/comfy.py`) feeds each frame back into the next at low
  denoise, so the image *morphs* continuously instead of regenerating. A denoise floor and a
  periodic clean-repaint keep the loop from diverging into grid/plaid artifacts on MPS.

Tinker from the browser console: `__abv.state`, `__abv.BRAIN`, `__abv.CONDUCTOR`,
`__abv.SUB`, `__abv.SETTINGS`, `__abv.toggleSubstrate()`.

## Configuration

Everything worth changing is an environment variable (see `conductor/comfy.py`,
`conductor/asr.py`, `conductor/autolume_osc.py`):

| Var | Default | What |
|-----|---------|------|
| `NYE_COMFY_CKPT` | `DreamShaper8_LCM.safetensors` | ComfyUI checkpoint |
| `NYE_COMFY_STEPS` / `NYE_COMFY_CFG` | `6` / `2.0` | sampler steps / cfg |
| `NYE_WHISPER_MODEL` | `base.en` | faster-whisper model |
| `NYE_AUTOLUME` | off | `1` to enable AutoLume OSC co-drive |
| `NYE_AUTOLUME_PORT` | `1338` | AutoLume OSC port (v2.17-rc1 default) |
| `NYE_OSC_*` | see `autolume_osc.py` | per-parameter OSC addresses — reconcile with AutoLume's "Use OSC" bindings |
| `GEMINI_API_KEY` | — | topic-brain key (`.env` also works) |

> **AutoLume note:** the OSC *port* (1338) is confirmed; the OSC *addresses* are set
> per-parameter inside AutoLume's Perform "Use OSC" popups, so match the app's bindings
> to the names the conductor prints on startup (with `NYE_AUTOLUME=1`). Pretrained
> pickles for the substrate live at `~/Code/autolume-models/` (metfaces, afhqwild).

## Credits & license

MIT licensed — see [LICENSE](./LICENSE). Built on
[ComfyUI](https://github.com/comfyanonymous/ComfyUI),
[comfyui-tooling-nodes](https://github.com/Acly/comfyui-tooling-nodes),
[faster-whisper](https://github.com/SYSTRAN/faster-whisper), DreamShaper by Lykon, and
[AutoLume](https://www.metacreation.net/autolume) from SFU's Metacreation Lab.

The name is a nod to Pahrump, Nevada — the Kingdom of Nye — where Art broadcast from his
home studio.
