"""Tests for gui/gradebook_review_window.py — data interface + mutations.
Runs headless via QT_QPA_PLATFORM=offscreen (same as test_gradebook.py)."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

QtWidgets = pytest.importorskip("PyQt6.QtWidgets", reason="PyQt6 is not installed")
QApplication = QtWidgets.QApplication

from gui.gradebook_review_window import GradebookReviewWindow, UNCATEGORIZED


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


STRUCT = {
    "categories": [
        {"name": "Quizzes", "weight": 40.0, "items": ["Quiz 1", "Quiz 2"]},
        {"name": "Exam", "weight": 60.0, "items": ["Final Exam"]},
    ],
    "uncategorized": ["Bonus"],
}


def test_load_then_to_structure_roundtrips(qapp):
    w = GradebookReviewWindow()
    w.load_structure(STRUCT)
    out = w.to_structure()
    assert [c["name"] for c in out["categories"]] == ["Quizzes", "Exam"]
    assert out["categories"][0]["weight"] == 40.0
    assert out["categories"][0]["items"] == ["Quiz 1", "Quiz 2"]
    assert out["uncategorized"] == ["Bonus"]


def test_remove_category_moves_items_to_uncategorized(qapp):
    w = GradebookReviewWindow()
    w.load_structure(STRUCT)
    quizzes = w._sections[0]
    w.remove_section(quizzes)
    out = w.to_structure()
    assert [c["name"] for c in out["categories"]] == ["Exam"]
    assert set(out["uncategorized"]) == {"Bonus", "Quiz 1", "Quiz 2"}


def test_move_item_between_categories(qapp):
    w = GradebookReviewWindow()
    w.load_structure(STRUCT)
    # move Quiz 1 (in Quizzes) → Exam
    row = w._sections[0]._items_box.itemAt(0).widget()
    assert row.name == "Quiz 1"
    w.move_item(row, "Exam")
    out = w.to_structure()
    assert "Quiz 1" not in out["categories"][0]["items"]
    assert "Quiz 1" in out["categories"][1]["items"]


def test_move_item_to_uncategorized(qapp):
    w = GradebookReviewWindow()
    w.load_structure(STRUCT)
    row = w._sections[1]._items_box.itemAt(0).widget()   # Final Exam
    w.move_item(row, UNCATEGORIZED)
    out = w.to_structure()
    assert out["categories"][1]["items"] == []
    assert "Final Exam" in out["uncategorized"]


def test_invalid_weight_detected(qapp):
    w = GradebookReviewWindow()
    w.load_structure(STRUCT)
    w._sections[0].weight_edit.setText("abc")
    assert w.invalid_weight_columns() == ["Quizzes"]


def test_add_category_appears_before_uncategorized(qapp):
    w = GradebookReviewWindow()
    w.load_structure(STRUCT)
    w._add_category("New One", 0.0, [])
    out = w.to_structure()
    assert out["categories"][-1]["name"] == "New One"
    # uncategorized still the trailing section widget
    assert w._sec_layout.indexOf(w._uncat) == w._sec_layout.count() - 2


def test_apply_emits_structure_and_hides(qapp):
    w = GradebookReviewWindow()
    w.load_structure(STRUCT)
    captured = []
    w.apply_requested.connect(lambda s: captured.append(s))
    w._on_apply()
    assert len(captured) == 1
    assert [c["name"] for c in captured[0]["categories"]] == ["Quizzes", "Exam"]
    assert w.isHidden()


def test_apply_blocked_on_invalid_weight(qapp):
    w = GradebookReviewWindow()
    w.load_structure(STRUCT)
    w._sections[0].weight_edit.setText("oops")
    captured = []
    w.apply_requested.connect(lambda s: captured.append(s))
    w._on_apply()
    assert captured == []          # never emitted
