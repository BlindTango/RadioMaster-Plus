"""Effects engine for real-time audio processing via FFmpeg filter graphs."""

from typing import Any


class EffectsEngine:
    """Manages audio effect parameters and generates FFmpeg filter graph strings."""

    def __init__(self) -> None:
        self._effects: dict[str, dict[str, Any]] = {
            "equalizer": {"enabled": False, "preset": "Flat", "params": {}},
            "dynamic_range": {"enabled": False, "preset": "Light Compression", "params": {}},
            "reverb_echo": {"enabled": False, "preset": "Small Room", "params": {}},
            "pitch_tempo": {"enabled": False, "preset": "Semitone Down", "params": {}},
            "crossfade": {"enabled": False, "preset": "Medium (5s)", "params": {}},
            "normalization": {"enabled": False, "preset": "Standard (-16 LUFS)", "params": {}},
        }

    def set_enabled(self, effect_id: str, enabled: bool) -> None:
        """Enable or disable an effect."""
        if effect_id in self._effects:
            self._effects[effect_id]["enabled"] = enabled

    def is_enabled(self, effect_id: str) -> bool:
        """Check if an effect is enabled."""
        return self._effects.get(effect_id, {}).get("enabled", False)

    def set_params(self, effect_id: str, params: dict[str, Any]) -> None:
        """Set parameters for an effect."""
        if effect_id in self._effects:
            self._effects[effect_id]["params"] = params

    def set_preset(self, effect_id: str, preset_name: str) -> None:
        """Set the active preset name for an effect."""
        if effect_id in self._effects:
            self._effects[effect_id]["preset"] = preset_name

    def get_params(self, effect_id: str) -> dict[str, Any]:
        """Get current parameters for an effect."""
        return self._effects.get(effect_id, {}).get("params", {})

    def build_filter_graph(self, rate: float = 1.0, pan: float = 0.0) -> str | None:
        """Build a complete FFmpeg filter graph string from all enabled effects."""
        filters = []

        # Rate control
        if rate != 1.0:
            filters.append(f"atempo={rate}")

        # Pan
        if pan != 0.0:
            pan_val = max(-1.0, min(1.0, pan))
            left_gain = 1.0 - max(0, pan_val)
            right_gain = 1.0 - max(0, -pan_val)
            filters.append(f"pan=stereo|c0={left_gain}*c0|c1={right_gain}*c1")

        # Equalizer
        if self._effects["equalizer"]["enabled"]:
            params = self._effects["equalizer"]["params"]
            if params:
                bands = " ".join(f"c0 f={k} w={k} g={v}" for k, v in params.items())
                filters.append(f"firequalizer={bands}")
            else:
                filters.append("firequalizer=0")

        # Dynamic range
        if self._effects["dynamic_range"]["enabled"]:
            params = self._effects["dynamic_range"]["params"]
            threshold = params.get("threshold", -20)
            ratio = params.get("ratio", 4)
            attack = params.get("attack", 5)
            release = params.get("release", 50)
            filters.append(
                f"compand=attacks={attack}:decays={release}:"
                f"points=-80,-80|-{abs(threshold)},-{abs(threshold)}|0,0"
            )

        # Reverb/Echo
        if self._effects["reverb_echo"]["enabled"]:
            params = self._effects["reverb_echo"]["params"]
            delay = params.get("delay", 50)
            decay = params.get("decay", 0.5)
            filters.append(f"aecho={delay}:{decay}:{delay * 2}:{decay * 0.5}")

        # Pitch/Tempo
        if self._effects["pitch_tempo"]["enabled"]:
            params = self._effects["pitch_tempo"]["params"]
            cents = params.get("cents", 0)
            tempo = params.get("tempo", 1.0)
            ratio = 2 ** (cents / 1200)
            filters.append(f"asetrate=44100*{ratio},atempo={tempo / ratio}")

        # Normalization
        if self._effects["normalization"]["enabled"]:
            params = self._effects["normalization"]["params"]
            target = params.get("target", -16)
            filters.append(f"dynaudnorm=framelen=500:targetrms={10 ** (target / 20):.4f}")

        return ",".join(filters) if filters else None
