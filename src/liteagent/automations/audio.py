"""Turns the voice's WAV into an Ogg/Opus voice note, the format WhatsApp plays as a voice message."""

import io

import av


def wav_to_ogg_opus(wav: bytes) -> bytes:
    try:
        source = av.open(io.BytesIO(wav))
    except Exception as exc:
        raise ValueError(f"could not read the audio: {exc}") from None
    out = io.BytesIO()
    with source, av.open(out, "w", format="ogg") as target:
        stream = target.add_stream("libopus", rate=48000)
        stream.layout = "mono"
        resampler = av.AudioResampler(format="s16", layout="mono", rate=48000)
        for frame in source.decode(audio=0):
            for resampled in resampler.resample(frame):
                for packet in stream.encode(resampled):
                    target.mux(packet)
        for resampled in resampler.resample(None):
            for packet in stream.encode(resampled):
                target.mux(packet)
        for packet in stream.encode(None):
            target.mux(packet)
    return out.getvalue()
