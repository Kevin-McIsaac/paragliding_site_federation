"""Line endings, and the idempotency check that hid them."""

import csv

from src.canonical_store import write_app_csv
from tests.conftest import record
from tests.test_output import _select


def test_windows_line_endings_are_normalised(tmp_path):
    """Some guide prose arrives with CRLF. Git rewrites it to LF on checkout,
    so the file on disk would differ from the one just generated and every
    weekly run would rewrite it - a spurious diff in the pull request forever.
    """
    path = tmp_path / "sites.csv"
    shut = record("ansg", "a", closed="Closed.\r\n\r\nAwaiting an agreement.")

    write_app_csv([_select(shut)], path)

    assert b"\r" not in path.read_bytes()


def test_line_breaks_themselves_survive(tmp_path):
    """Normalising endings is not flattening - the paragraphs stay."""
    path = tmp_path / "sites.csv"
    shut = record("ansg", "a", closed="Closed.\r\n\r\nAwaiting an agreement.")

    write_app_csv([_select(shut)], path)

    with open(path, newline="") as f:
        row = list(csv.DictReader(f))[0]
    assert row["closed"] == "Closed.\n\nAwaiting an agreement."


def test_a_byte_difference_is_not_reported_as_unchanged(tmp_path):
    """The idempotency check used read_text(), which applies universal newline
    translation - a file holding CRLF read back as LF, compared equal to fresh
    LF content, and was never rewritten. The check reported "unchanged" while
    the bytes on disk differed."""
    path = tmp_path / "sites.csv"
    site = _select(record("pge", "1"))

    write_app_csv([site], path)
    # Simulate the file having been written with Windows endings.
    path.write_bytes(path.read_bytes().replace(b"\n", b"\r\n"))

    assert write_app_csv([site], path) is True, "a byte difference must rewrite"
    assert b"\r" not in path.read_bytes()
