import pathlib
import sys

SCRIPTS = pathlib.Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from zentao_common import find_playwright_python


def test_selects_a_python_that_can_import_playwright_over_an_existing_invalid_candidate():
    selected = find_playwright_python(["/bin/false", sys.executable])

    assert selected == sys.executable
