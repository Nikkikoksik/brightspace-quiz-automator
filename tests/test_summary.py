"""Unit tests for _print_run_summary in browser.py."""
import browser


def _ok(name, elapsed=1.0):
    return {"name": name, "elapsed": elapsed, "failed": False}


def _fail(name):
    return {"name": name, "elapsed": 0.5, "failed": True}


def test_all_passing(capsys):
    browser._print_run_summary([_ok("Quiz A", 2.0), _ok("Quiz B", 4.0)], "quiz", wall_time=6.0)
    out = capsys.readouterr().out
    assert "All OK" in out
    assert "Avg" in out
    assert "Total" in out
    assert "Errors" not in out


def test_with_failures(capsys):
    browser._print_run_summary([_ok("Q1"), _fail("Q2"), _fail("Q3")], "quiz")
    out = capsys.readouterr().out
    assert "Errors : 2" in out
    assert "All OK" not in out


def test_wall_time_none(capsys):
    browser._print_run_summary([_ok("Q1")], "quiz", wall_time=None)
    out = capsys.readouterr().out
    assert "Total" not in out


def test_empty_results(capsys):
    browser._print_run_summary([], "quiz")
    out = capsys.readouterr().out
    assert "0 quiz(s)" in out


def test_long_name_truncated(capsys):
    long_name = "A" * 50
    browser._print_run_summary([_ok(long_name)], "quiz")
    out = capsys.readouterr().out
    assert "…" in out


def test_item_kind_label(capsys):
    browser._print_run_summary([_ok("X")], kind="assignment")
    out = capsys.readouterr().out
    assert "assignment" in out
