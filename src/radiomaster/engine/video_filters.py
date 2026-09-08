"""Audio filter strings for the FFplay video renderer."""

from typing import Any

SAMPLE_RATE = 48000


def build_effects_filters(rate: float, effects: dict[str, dict[str, Any]]) -> list[str]:
    """Build the list of "name=args" libavfilter descriptors for the
    current rate and effects settings used by FFplay video playback.
    """
    filters: list[str] = []

    if rate != 1.0:
        filters.append(f"atempo={rate}")

    if effects["equalizer"]["enabled"]:
        params = effects["equalizer"]["params"]
        if params:
            # firequalizer's gain_entry takes semicolon-separated
            # entry(freq,gain_db) pairs -- NOT the "c0 f=.. w=.. g=.."
            # form this used to build, which is invalid syntax that
            # libavfilter only rejects at graph-configure time, not at
            # filter-creation time (so it went undetected until now).
            entries = ";".join(f"entry({k},{v})" for k, v in params.items())
            filters.append(f"firequalizer=gain_entry={entries}")
        # No params with EQ "enabled" means no bands set yet -- nothing to
        # apply, and there's no valid neutral firequalizer arg string to
        # fall back to, so just skip adding the filter.

    if effects["dynamic_range"]["enabled"]:
        params = effects["dynamic_range"]["params"]
        threshold = params.get("threshold", -20)
        attack = params.get("attack", 5)
        release = params.get("release", 50)
        # compand's points list is "x/y|x/y|..." -- a slash between each
        # point's x and y, not a comma (comma is the separator libavfilter
        # actually uses between *options*, so "x,y" parsed as two options
        # and failed at graph-configure time).
        filters.append(
            f"compand=attacks={attack}:decays={release}:"
            f"points=-80/-80|-{abs(threshold)}/-{abs(threshold)}|0/0"
        )

    if effects["echo"]["enabled"]:
        params = effects["echo"]["params"]
        delay = params.get("delay", 500)
        decay = params.get("decay", 0.4)
        in_gain = params.get("in_gain", 0.8)
        out_gain = params.get("out_gain", 0.88)
        # aecho's positional args are in_gain:out_gain:delays:decays.
        filters.append(f"aecho={in_gain}:{out_gain}:{delay}:{decay}")

    if effects["reverb"]["enabled"]:
        params = effects["reverb"]["params"]
        room_size = params.get("room_size", 0.4)
        decay = params.get("decay", 0.4)
        mix = params.get("mix", 0.3)
        # ffmpeg has no dedicated reverb filter -- simulate room
        # reflections with a single aecho call given 4 taps (pipe-
        # separated delay/decay lists), spaced out and scaled by
        # room_size, each successive tap decaying faster than the last.
        max_delay = 30 + room_size * 220  # ms, roughly 50-250ms
        delays = [max_delay * f for f in (0.15, 0.35, 0.6, 1.0)]
        decays = [max(0.05, decay * f) for f in (0.9, 0.7, 0.5, 0.3)]
        delays_str = "|".join(f"{d:.0f}" for d in delays)
        decays_str = "|".join(f"{d:.3f}" for d in decays)
        filters.append(f"aecho=1.0:{mix}:{delays_str}:{decays_str}")

    if effects["chorus"]["enabled"]:
        params = effects["chorus"]["params"]
        delay = params.get("delay", 50)
        decay = params.get("decay", 0.4)
        speed = params.get("speed", 2.0)
        depth = params.get("depth", 2.0)
        filters.append(f"chorus=0.5:0.9:{delay}:{decay}:{speed}:{depth}")

    if effects["compressor"]["enabled"]:
        params = effects["compressor"]["params"]
        threshold = params.get("threshold", 0.1)
        ratio = params.get("ratio", 4)
        attack = params.get("attack", 20)
        release = params.get("release", 250)
        makeup = params.get("makeup", 1)
        filters.append(
            f"acompressor=threshold={threshold}:ratio={ratio}:"
            f"attack={attack}:release={release}:makeup={makeup}"
        )

    if effects["distortion"]["enabled"]:
        params = effects["distortion"]["params"]
        bits = int(params.get("bits", 8))
        mix = params.get("mix", 0.6)
        filters.append(f"acrusher=bits={bits}:mix={mix}:mode=log")

    if effects["flanger"]["enabled"]:
        params = effects["flanger"]["params"]
        delay = params.get("delay", 10)
        depth = params.get("depth", 2)
        speed = params.get("speed", 0.5)
        filters.append(f"flanger=delay={delay}:depth={depth}:speed={speed}")

    if effects["gargle"]["enabled"]:
        params = effects["gargle"]["params"]
        rate = params.get("rate", 20)
        depth = params.get("depth", 0.7)
        # No native "gargle" filter -- tremolo's amplitude modulation at a
        # gargle-appropriate rate produces the same warbling character.
        filters.append(f"tremolo=f={rate}:d={depth}")

    if effects["pitch_tempo"]["enabled"]:
        params = effects["pitch_tempo"]["params"]
        cents = params.get("cents", 0)
        tempo = params.get("tempo", 1.0)
        ratio = 2 ** (cents / 1200)
        # Chain pitch resampling and tempo compensation for video audio.
        filters.append(f"asetrate={SAMPLE_RATE}*{ratio}")
        filters.append(f"aresample={SAMPLE_RATE}")
        filters.append(f"atempo={tempo / ratio}")

    # Crossfade is deliberately NOT added to this single-stream filter
    # chain: acrossfade takes two separate audio inputs and blends them
    # into one output (for transitioning between two tracks) -- it can't
    # function as an in-place effect on a single stream, in either this
    # engine or the old ffplay -af string it was copied from. Making
    # crossfade real would mean decoding the next track in parallel and
    # mixing the tail of one into the head of the other, which is a
    # genuinely separate feature, not a filter-string fix.

    if effects["normalization"]["enabled"]:
        params = effects["normalization"]["params"]
        target = params.get("target", -16)
        filters.append(f"dynaudnorm=framelen=500:targetrms={10 ** (target / 20):.4f}")

    return filters
