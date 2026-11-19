"""Provider preset tests."""

from __future__ import annotations

from config.providers import PROVIDER_PRESETS, match_preset


def test_every_preset_has_name_and_custom_is_last():
    names = [preset.name for preset in PROVIDER_PRESETS]
    assert len(names) == len(set(names))
    assert PROVIDER_PRESETS[-1].name == "自定义"
    assert PROVIDER_PRESETS[-1].base_url == ""


def test_match_preset_round_trip():
    for index, preset in enumerate(PROVIDER_PRESETS[:-1]):
        assert match_preset(preset.base_url, preset.model) == index
    assert match_preset("https://unknown.example/v1", "x") == len(PROVIDER_PRESETS) - 1


def test_vision_presets_exist():
    assert any(preset.vision for preset in PROVIDER_PRESETS)
    assert any(not preset.vision for preset in PROVIDER_PRESETS)
