"""Tests for src/gradebook_automator.py — AI parsing, prompt, outline text helpers."""
import pytest
import gradebook_automator as ga


ITEMS = ["Quiz 1", "Quiz 2", "Final Exam", "Project"]

GOOD_JSON = '''
{"categories": [
  {"name": "Quizzes", "weight": 20, "items": ["Quiz 1", "Quiz 2"]},
  {"name": "Final Exam", "weight": 50, "items": ["Final Exam"]},
  {"name": "Project", "weight": 30, "items": ["Project"]}
]}
'''


def test_parse_plain_json():
    s = ga._parse_ai_response(GOOD_JSON, ITEMS)
    assert [c["name"] for c in s["categories"]] == ["Quizzes", "Final Exam", "Project"]
    assert s["categories"][0]["weight"] == 20.0
    assert s["uncategorized"] == []


def test_parse_markdown_fenced_json():
    fenced = "Here you go:\n```json\n" + GOOD_JSON + "\n```\nDone."
    s = ga._parse_ai_response(fenced, ITEMS)
    assert len(s["categories"]) == 3


def test_hallucinated_item_dropped():
    bad = '{"categories": [{"name": "Quizzes", "weight": 100, "items": ["Quiz 1", "Ghost Quiz"]}]}'
    s = ga._parse_ai_response(bad, ["Quiz 1"])
    assert s["categories"][0]["items"] == ["Quiz 1"]


def test_missed_item_goes_uncategorized():
    partial = '{"categories": [{"name": "Quizzes", "weight": 100, "items": ["Quiz 1"]}]}'
    s = ga._parse_ai_response(partial, ["Quiz 1", "Forgotten"])
    assert s["uncategorized"] == ["Forgotten"]


def test_unparseable_raises():
    with pytest.raises(ValueError):
        ga._parse_ai_response("no json here at all", ITEMS)


def test_no_categories_raises():
    with pytest.raises(ValueError):
        ga._parse_ai_response('{"categories": []}', ITEMS)


def test_build_prompt_mentions_items_and_table_hint():
    p = ga._build_prompt("outline text", ["Quiz 1"])
    assert "Quiz 1" in p
    assert "100" in p          # sums-to-~100% guidance
    assert "JSON" in p


def test_extract_categories_dispatch(monkeypatch):
    calls = {}
    def fake_claude(prompt, api_key):
        calls["key"] = api_key
        return GOOD_JSON
    monkeypatch.setattr(ga, "_call_claude", fake_claude)
    s = ga.extract_categories("outline", ITEMS, "claude", "sk-test")
    assert calls["key"] == "sk-test"
    assert len(s["categories"]) == 3


def test_extract_categories_unknown_provider():
    with pytest.raises(ValueError):
        ga.extract_categories("outline", ITEMS, "grok", "k")
