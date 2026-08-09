"""Guide prose keeps its line breaks; the app parses them properly."""

import csv

from src.canonical_store import write_app_csv
from tests.conftest import record
from tests.test_output import _select


def test_a_line_break_in_guide_prose_is_preserved(tmp_path):
    """These used to be flattened to spaces, because the app split the file on
    newlines before parsing fields and an embedded one tore a record in two -
    43 of 11,703 rows. The app now reads the file with a real CSV parser, so
    the text can keep its paragraphs."""
    path = tmp_path / "sites.csv"
    notice = "Closed DECEMBER 2015\nThe committee is working on it"

    write_app_csv([_select(record("ansg", "a", closed=notice))], path)

    with open(path, newline="") as f:
        rows = list(csv.DictReader(f))

    assert len(rows) == 1, "a quoted newline must not split the record"
    assert rows[0]["closed"] == notice
