"""Smoke tests: verify all src modules import cleanly and public functions exist."""
import importlib
import pytest


def _mod(name):
    return importlib.import_module(name)


def test_import_actions():
    _mod("actions")


def test_import_browser():
    _mod("browser")


def test_import_navigation():
    _mod("navigation")


def test_import_config():
    _mod("config")


@pytest.mark.parametrize("fn", [
    "harvest_quiz_edit_urls",
    "get_quiz_names",
    "open_quiz_edit",
    "discover_course_urls",
    "set_per_page_200",
    "get_assignment_names",
    "open_assignment_edit",
])
def test_navigation_functions_exist(fn):
    mod = _mod("navigation")
    assert hasattr(mod, fn), f"navigation.{fn} missing"


@pytest.mark.parametrize("fn", [
    "apply_gradebook",
    "apply_auto_submit",
    "save_quiz",
    "apply_assignment_gradebook",
    "save_assignment",
    "verify_quiz_settings",
    "apply_pdf_only_file_type",
    "apply_rename_title",
    "read_quiz_before_state",
    "revert_gradebook",
    "revert_auto_submit",
])
def test_actions_functions_exist(fn):
    mod = _mod("actions")
    assert hasattr(mod, fn), f"actions.{fn} missing"


@pytest.mark.parametrize("fn", [
    "run",
    "run_assignments",
    "run_verify",
    "run_timer_fix",
    "run_undo",
    "run_bs_login",
])
def test_browser_functions_exist(fn):
    mod = _mod("browser")
    assert hasattr(mod, fn), f"browser.{fn} missing"


def test_no_duplicate_harvest():
    import inspect
    import navigation
    src = inspect.getsource(navigation)
    count = src.count("async def harvest_quiz_edit_urls")
    assert count == 1, f"harvest_quiz_edit_urls defined {count} times (expected 1)"
