# The Kingdom of Nye - Art Bell Visualizer

An audio-reactive, **topic-reactive**, **AI-generative** trippy visualizer for
late-night Art Bell listening. It listens to the room through the mic: the
visuals pulse with the audio and kick on every beat, speech recognition plus an
LLM "topic brain" understand what the show is talking about, a Gemini dream
layer paints visions of it into the shader, and the real MilkDrop 2 engine
(Butterchurn) surges up whenever the bumper music hits.

Full details: [SPEC.md](./SPEC.md) (features, architecture, cost model, roadmap).

## Quick start

**No install, no build, no dependencies.** You need Python 3 (for the AI
companion server) and Chrome.

The lightweight version (audio + topic reactivity + MilkDrop, no AI images):
just open `index.html` in Chrome directly. Done.

The full experience (adds the Gemini dream layer + LLM topic brain):

```bash
# 1. get a free Gemini API key: https://aistudio.google.com/app/apikey
# 2. drop it in a .env file next to server.py (gitignored):
echo 'GEMINI_API_KEY=your-key-here' > .env
# 3. run the server and open it:
python3 server.py
# then open http://localhost:8765 in Chrome
```

(You can also export `GEMINI_API_KEY` as an environment variable instead of
using `.env`.)

Then:

1. Click **TUNE IN** and allow the microphone.
2. Play the show out loud from anything - YouTube, archive.org, VLC. The mic
   hears the room, so nothing needs to be wired together.
3. Press `F` for fullscreen and let it ride.

Chrome specifically, because topic detection uses the Web Speech API
(`webkitSpeechRecognition`), which other browsers barely support. Without it
(or with the mic denied) the visualizer still runs - audio-reactive only, or
drifting on its own in demo mode.

## The AI layers

`server.py` is a zero-dependency stdlib proxy: it holds the API key so it never
touches the browser, and it saves your dream gallery locally.

- **Topic brain** (Gemini flash-lite text model): every ~45 s it reads the
  rolling transcript and designs the mood - label, palette, scene, intensity.
  The visuals follow ANY topic, not just the 7 built-in moods. Pennies per night.
- **Dream layer** (`gemini-2.5-flash-image`): paints visions of the current
  topic, melted into the shader and warped by the bass. New image on topic
  change (25 s debounce) plus a slow ambient refresh. ~$0.04/image,
  ~$0.30-0.60/evening, hard session cap, live cost ticker in the HUD.
- **Continuity**: each vision is handed back as a reference image, so the night
  is one long evolving hallucination (toggle in settings).
- **Vision gallery**: every dream auto-saves to `visions/YYYY-MM-DD/` with its
  prompt - wake up to the night's trip log.

## Keys

| Key | Does |
|-----|------|
| `F` | fullscreen |
| `1`-`7` | pin a mood (Nye, aliens, demons, ghosts, government, cryptids, wormhole) |
| `0` | back to automatic (follow the conversation) |
| `G` | toggle the AI dream layer |
| `B` | next MilkDrop preset (turns the layer on if it's off) |
| `S` | live spectrum overlay (see the audio-reactivity raw) |
| `C` | settings drawer (cadence, opacity, reactivity, blend, cap) |

## How it decides the mood

Two layers. The keyword engine reacts instantly: ~140 trigger words score into
7 moods with a 45 s decay half-life. The LLM brain reads the whole transcript
every ~45 s and can override with a custom palette + scene for topics the
keywords don't know. Beat detection (spectral flux) makes everything kick in
time, and sustained periodic beats flip bumper-music mode, which surges the
MilkDrop layer.

Tinker via the console: `__abv.state`, `__abv.BRAIN`, `__abv.CHURN`,
`__abv.SETTINGS`, `__abv.fireDream()`, `__abv.hearTranscript('the demons are here')`.

## Credits & license

MIT licensed - see [LICENSE](./LICENSE). Bundles
[Butterchurn](https://github.com/jberg/butterchurn), the WebGL MilkDrop 2
engine by Jordan Berg and contributors (also MIT).

Built for late-night [Art Bell](https://en.wikipedia.org/wiki/Art_Bell) /
Coast to Coast AM sessions. The name is a nod to Pahrump, Nevada - the Kingdom
of Nye - where Art broadcast from his home studio.
