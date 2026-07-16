"""Local speech-to-text — faster-whisper tapping the mic, emitting word deltas.

Replaces v2's Google Web Speech API (which also freed us from the Chrome lock-in).
Runs fully offline on CPU (CTranslate2 int8); on an M4 Max a base.en model keeps up
with late-night talk radio comfortably.

Chunking strategy: accumulate 0.1 s blocks and flush a phrase when we hear trailing
silence after speech (or hit a max window). Phrase-aligned chunks mean no overlap and
no dedup — each flush is transcribed once and its text emitted as a {type:"words"}
delta, which the browser feeds into the *existing, unchanged* keyword scorer and the
conductor feeds into the topic brain.
"""

from __future__ import annotations

import asyncio
import os

SR = 16000
BLOCK = 1600            # 0.1 s
SPEECH_RMS = float(os.environ.get("NYE_SPEECH_RMS", "0.006"))  # lower = hears quieter talk
SILENCE_HANG = 0.6     # s of quiet after speech -> flush
MIN_PHRASE = 0.5       # s; catch short utterances too
MAX_WINDOW = 8.0       # s; flush even mid-sentence so we never lag far behind
MODEL_NAME = os.environ.get("NYE_WHISPER_MODEL", "small.en")   # more accurate than base.en


def _load_model():
    from faster_whisper import WhisperModel
    print(f"[asr] loading faster-whisper '{MODEL_NAME}' (first run downloads it)…")
    model = WhisperModel(MODEL_NAME, device="cpu", compute_type="int8")
    print("[asr] model ready")
    return model


# phrases faster-whisper hallucinates on silence/room-tone — almost never real content here
HALLUCINATIONS = {
    "you", "thank you", "thank you.", "thanks for watching", "thanks for watching!",
    "bye", "bye bye", "bye.", "goodbye", "good bye", "we're done", "mm-hmm", "mm",
    "please subscribe", "subtitles by the amara.org community", ".", "so", "okay",
}


def _is_hallucination(text: str) -> bool:
    t = text.strip().lower()
    if len(t) < 3 or not any(c.isalpha() for c in t):
        return True
    return t.rstrip(".!?") in HALLUCINATIONS


def _transcribe(model, audio) -> str:
    segments, _ = model.transcribe(
        audio, language="en", beam_size=1, vad_filter=True,
        condition_on_previous_text=False,
    )
    text = " ".join(s.text.strip() for s in segments).strip()
    return "" if _is_hallucination(text) else text


def _capture_loop(hub, model, emit) -> None:
    import numpy as np
    import time

    import sounddevice as sd

    # outer loop re-opens the input stream if the device glitches mid-session (USB
    # unplug, format change) instead of killing speech for the rest of the night
    while hub.state.running:
        buf: list = []
        voiced = False
        silence = 0.0
        try:
            with sd.InputStream(samplerate=SR, channels=1, dtype="float32",
                                blocksize=BLOCK) as stream:
                print("[asr] listening on the default input device")
                while hub.state.running:
                    block, _ = stream.read(BLOCK)
                    mono = block[:, 0].copy()
                    buf.append(mono)
                    rms = float(np.sqrt(np.mean(mono * mono)) + 1e-9)
                    if rms > SPEECH_RMS:
                        voiced = True
                        silence = 0.0
                    else:
                        silence += BLOCK / SR
                    dur = sum(len(b) for b in buf) / SR

                    flush = (voiced and silence >= SILENCE_HANG and dur >= MIN_PHRASE) or dur >= MAX_WINDOW
                    if not flush:
                        continue

                    audio = np.concatenate(buf)
                    buf.clear()
                    was_voiced, voiced, silence = voiced, False, 0.0
                    if not was_voiced or dur < MIN_PHRASE:
                        continue  # silence window — nothing worth transcribing
                    try:
                        text = _transcribe(model, audio)
                    except Exception as e:
                        print(f"[asr] transcribe error: {e}")
                        continue
                    if text:
                        emit(text)
        except Exception as e:
            if not hub.state.running:
                break
            print(f"[asr] mic stream error ({type(e).__name__}: {e}); reopening in 2s")
            time.sleep(2.0)  # blocking sleep is fine — we're in an executor thread


async def asr_task(hub) -> None:
    loop = asyncio.get_running_loop()
    try:
        model = await loop.run_in_executor(None, _load_model)
    except Exception as e:
        print(f"[asr] could not load Whisper ({e}); speech disabled")
        return

    pending: set = set()

    def emit(text: str) -> None:
        # called from the capture thread — hop back onto the loop to touch the hub
        def _publish():
            hub.push_words(text)
            t = asyncio.create_task(hub.broadcast_json({"type": "words", "delta": text}))
            pending.add(t)          # keep a ref so the task can't be GC'd mid-flight
            t.add_done_callback(pending.discard)
            print(f"[asr] {text}")
        if not hub.state.running:
            return
        try:
            loop.call_soon_threadsafe(_publish)
        except RuntimeError:
            pass  # loop is closing during shutdown

    await loop.run_in_executor(None, _capture_loop, hub, model, emit)
