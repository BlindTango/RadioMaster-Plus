"""Tests for configuration management."""

import pytest
import tempfile
import os
from radiomaster.utils.config import ConfigManager, DEFAULT_CONFIG


class TestConfig:
    """Test configuration management."""

    @pytest.fixture
    def config(self) -> ConfigManager:
        tmp_dir = tempfile.mkdtemp()
        return ConfigManager(tmp_dir)

    def test_default_values(self, config: ConfigManager) -> None:
        assert config.get("playback", "default_volume") == 0.8
        assert config.get("general", "language") == "en"
        assert config.get("radio", "station_update_frequency") == "weekly"

    def test_set_and_get(self, config: ConfigManager) -> None:
        config.set("playback", "default_volume", value=0.5)
        assert config.get("playback", "default_volume") == 0.5

    def test_nested_set(self, config: ConfigManager) -> None:
        config.set("custom", "section", "key", value="value")
        assert config.get("custom", "section", "key") == "value"

    def test_save_and_load(self, config: ConfigManager) -> None:
        config.set("playback", "default_volume", value=0.3)
        config.save()

        # Create new config pointing to same file
        config2 = ConfigManager(config._config_dir)
        assert config2.get("playback", "default_volume") == 0.3

    def test_default_fallback(self, config: ConfigManager) -> None:
        result = config.get("nonexistent", "key", default="fallback")
        assert result == "fallback"
