import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.cea.preprocessing import normalize_cell, is_numeric_column, is_date_column, get_cell_context


def test_normalize_cell_strips_html():
    assert normalize_cell("<b>Hello</b>") == "Hello"


def test_normalize_cell_trims_whitespace():
    assert normalize_cell("  Hello  World  ") == "Hello World"


def test_normalize_cell_strips_outer_parens():
    assert normalize_cell("(Hello)") == "Hello"


def test_is_numeric_column():
    assert is_numeric_column(["1", "2", "3", "4", "5"])
    assert not is_numeric_column(["Alice", "Bob", "Carol"])


def test_is_date_column():
    assert is_date_column(["1976", "1980", "1985", "2001"])
    assert not is_date_column(["Alice", "Bob", "Carol"])


def test_get_cell_context():
    rows = [
        ["col0", "col1", "col2"],
        ["1976", "Eat My Dust!", "Charles Byron Griffith"],
        ["1976", "Hollywood Boulevard", "Joe Dante"],
    ]
    ctx = get_cell_context(rows, row_id=1, col_id=1, table_id="TEST")
    assert ctx.cell_value == "Eat My Dust!"
    assert ctx.col_id == 1
    assert ctx.row_id == 1
    assert "Hollywood Boulevard" in ctx.col_values


def test_get_cell_context_row2():
    rows = [
        ["col0", "col1"],
        ["a", "Alice"],
        ["b", "Bob"],
    ]
    ctx = get_cell_context(rows, row_id=2, col_id=1, table_id="T2")
    assert ctx.cell_value == "Bob"
