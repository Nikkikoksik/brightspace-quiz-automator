"""Verify config.py SETTINGS keys match what browser.py actually reads."""
import re
from pathlib import Path
import config


EXPECTED_KEYS = {"set_in_gradebook", "set_auto_submit", "rename_moodle_titles", "worker_count"}


def test_settings_has_expected_keys():
    assert set(config.SETTINGS.keys()) == EXPECTED_KEYS


def test_browser_settings_get_keys_exist_in_config():
    browser_src = (Path(__file__).parent.parent / "src" / "browser.py").read_text(encoding="utf-8")
    used_keys = set(re.findall(r'settings\.get\(["\'](\w+)["\']', browser_src))
    missing = used_keys - set(config.SETTINGS.keys())
    assert not missing, f"Keys used in browser.py but missing from config.SETTINGS: {missing}"
