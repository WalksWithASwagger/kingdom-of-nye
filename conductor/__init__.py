"""Kingdom of Nye v3 conductor — the local brain that drives both visual engines.

The browser owns real-time audio features + rendering; this process owns words
(Whisper), mood (Gemini), generation (ComfyUI), and substrate steering (AutoLume
over OSC). They meet on a single WebSocket control plane.
"""
