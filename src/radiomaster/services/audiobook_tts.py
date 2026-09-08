"""Shared engine catalogue and configuration for audiobook speech and preview."""

from radiomaster.services.sapi_tts import SAPITTS


TTS_ENGINES = {"sapi5": "Windows SAPI 5"}


def create_tts(engine_id: str):
    if engine_id not in TTS_ENGINES:
        raise ValueError(f"The saved TTS engine '{engine_id}' is not supported. Choose an engine in Settings > Audiobooks.")
    engine = SAPITTS()
    if not engine.available:
        raise RuntimeError("Windows SAPI 5 is unavailable. Check your Windows speech installation.")
    return engine


def configure_tts(engine, voice_id: str, rate: int, volume: int) -> None:
    if voice_id:
        if not any(voice["id"] == voice_id for voice in engine.get_voices()):
            raise ValueError("The selected voice is no longer installed. Choose a voice in Settings > Audiobooks.")
        engine.set_voice(voice_id)
    engine.set_rate(rate)
    engine.set_volume(volume)


def configured_tts(config):
    engine = create_tts(config.get("audiobooks.tts_engine", default="sapi5"))
    configure_tts(
        engine,
        config.get("audiobooks.tts_voice", default=""),
        config.get("audiobooks.tts_rate", default=0),
        config.get("audiobooks.tts_volume", default=100),
    )
    return engine
