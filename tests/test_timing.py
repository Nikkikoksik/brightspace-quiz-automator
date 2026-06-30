"""Unit tests for _save_timing in browser.py."""
import json
import browser


def test_creates_file_with_one_entry(tmp_path, monkeypatch):
    f = tmp_path / "stats.json"
    monkeypatch.setattr(browser, "STATS_FILE", str(f))
    browser._save_timing("https://example.com/quiz", "Quiz 1", 3.5)
    data = json.loads(f.read_text(encoding="utf-8"))
    assert len(data) == 1
    entry = data[0]
    assert entry["course"] == "https://example.com/quiz"
    assert entry["quiz"] == "Quiz 1"
    assert entry["seconds"] == 3.5


def test_appends_on_second_call(tmp_path, monkeypatch):
    f = tmp_path / "stats.json"
    monkeypatch.setattr(browser, "STATS_FILE", str(f))
    browser._save_timing("https://example.com/quiz", "Quiz 1", 2.0)
    browser._save_timing("https://example.com/quiz", "Quiz 2", 4.0)
    data = json.loads(f.read_text(encoding="utf-8"))
    assert len(data) == 2
    assert data[1]["quiz"] == "Quiz 2"


def test_required_keys_present(tmp_path, monkeypatch):
    f = tmp_path / "stats.json"
    monkeypatch.setattr(browser, "STATS_FILE", str(f))
    browser._save_timing("https://example.com/quiz", "Q", 1.0)
    entry = json.loads(f.read_text(encoding="utf-8"))[0]
    for key in ("date", "time", "course", "quiz", "seconds"):
        assert key in entry, f"missing key: {key}"


def test_corrupt_file_overwritten(tmp_path, monkeypatch):
    f = tmp_path / "stats.json"
    f.write_text("NOT VALID JSON", encoding="utf-8")
    monkeypatch.setattr(browser, "STATS_FILE", str(f))
    browser._save_timing("https://example.com/quiz", "Q", 1.0)
    data = json.loads(f.read_text(encoding="utf-8"))
    assert len(data) == 1


def test_elapsed_rounded(tmp_path, monkeypatch):
    f = tmp_path / "stats.json"
    monkeypatch.setattr(browser, "STATS_FILE", str(f))
    browser._save_timing("url", "Q", 3.14159)
    entry = json.loads(f.read_text(encoding="utf-8"))[0]
    assert entry["seconds"] == 3.1
