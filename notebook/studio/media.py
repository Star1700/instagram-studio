"""Validate finished videos locally and remux MP4 for progressive download."""
from fractions import Fraction
from pathlib import Path
import tempfile

import av

MAX_VIDEO_BYTES = 100_000_000


def prepare_video(data: bytes) -> tuple[bytes, dict]:
    if not data or len(data) > MAX_VIDEO_BYTES:
        raise ValueError("Bitte wähle ein fertiges MP4-Video bis 100 MB.")
    if len(data) < 12 or data[4:8] != b"ftyp":
        raise ValueError("Bitte exportiere dein Video als MP4 mit H.264 und gegebenenfalls AAC-Ton.")
    try:
        with tempfile.TemporaryDirectory(prefix="studio-video-") as folder:
            source, target = Path(folder) / "input.mp4", Path(folder) / "ready.mp4"
            source.write_bytes(data)
            with av.open(str(source)) as container:
                if len(container.streams.video) != 1 or len(container.streams.audio) > 1:
                    raise ValueError("Das MP4 braucht genau eine Videospur und höchstens eine Tonspur.")
                video = container.streams.video[0]
                duration = float(video.duration * video.time_base) if video.duration else (container.duration or 0) / av.time_base
                rate = float(video.average_rate or Fraction(0))
                codec = video.codec_context
                if codec.name != "h264" or codec.format is None or codec.format.name != "yuv420p":
                    raise ValueError("Bitte exportiere das Video mit H.264, 8 Bit und dem Farbformat 4:2:0.")
                if not 3 <= duration <= 900 or not 23 <= rate <= 60:
                    raise ValueError("Das Video muss 3 Sekunden bis 15 Minuten lang sein und 23 bis 60 Bilder pro Sekunde haben.")
                if not (320 <= codec.width <= 1920 and 320 <= codec.height <= 3840):
                    raise ValueError("Bitte verwende ein Video mit 320 bis 1920 Pixel Breite und 320 bis 3840 Pixel Höhe.")
                if codec.bit_rate and codec.bit_rate > 25_000_000:
                    raise ValueError("Bitte exportiere das Video mit höchstens 25 Mbit/s.")
                for audio in container.streams.audio:
                    ac = audio.codec_context
                    if ac.name != "aac" or ac.sample_rate > 48000 or ac.channels > 2:
                        raise ValueError("Bitte verwende AAC-Ton mit höchstens 48 kHz und Stereo.")
                frame = next(container.decode(video), None)
                if frame is None or frame.interlaced_frame:
                    raise ValueError("Das Video konnte nicht gelesen werden. Bitte exportiere es mit progressiver Abtastung.")
                metadata = {"width": codec.width, "height": codec.height, "duration": round(duration, 2), "fps": round(rate, 2)}
            # Remux without changing pixels or audio; move the index to the beginning.
            with av.open(str(source)) as source_container, av.open(str(target), "w", format="mp4",
                    options={"movflags": "+faststart", "use_editlist": "0"}) as output:
                mapping = {stream.index: output.add_stream_from_template(stream) for stream in source_container.streams
                           if stream.type in {"video", "audio"}}
                for packet in source_container.demux():
                    if packet.dts is None or packet.stream.index not in mapping:
                        continue
                    packet.stream = mapping[packet.stream.index]
                    output.mux(packet)
            ready = target.read_bytes()
            if len(ready) > MAX_VIDEO_BYTES:
                raise ValueError("Das fertige MP4 darf höchstens 100 MB groß sein.")
            return ready, metadata
    except ValueError:
        raise
    except Exception:
        raise ValueError("Das Video konnte nicht gelesen werden. Bitte exportiere es erneut als MP4 mit H.264.") from None
