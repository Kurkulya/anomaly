# Stack profile: Python (unittest, pytest)

Picked when the repo has `test*.py` files, `pytest.ini`, `conftest.py` or a `[tool.pytest]`
table. unittest flags were checked with `python3 -m unittest --help`. pytest was not installed
here: its flags are from memory, unverified.

- **Find tests.** unittest finds `test*.py` (`-p` changes the pattern). pytest finds
  `test_*.py` and `*_test.py`; read `testpaths` in `pytest.ini`, `pyproject.toml` or
  `tox.ini`.
- **Run one file.** `python3 -m unittest path/to/test_x.py`; one test:
  `python3 -m unittest pkg.test_x.Class.test_name`. pytest: `python3 -m pytest path/to/test_x.py`.
- **Time one file.** unittest: `--durations N` (N=0 for all) lists the slowest test cases;
  Python 3.12 or later. pytest: `--durations=N` (unverified).
- **Empty assertion.** No `self.assert*`, `assertRaises` or `self.fail` (pytest: no bare
  `assert`); `assertTrue` of a fixed value; `assertIsNotNone` alone.
- **E2e test.** unittest has no marker. Look for a subprocess that starts the CLI or a
  server, a network call, or `@unittest.skipUnless`. pytest: a `@pytest.mark.<name>`
  declared in config (unverified).
- **Break code.** In the copy, edit the code under test by hand. Run the cover with
  `python3 -m unittest <cover>` (`-f` stops at the first failure).
- **Install freshness.** Standard-library tests need none. With a virtualenv, compare
  `pip list` with `requirements*.txt`.

## Recipes

```bash
# <T> = ':(glob)**/test*.py' ':(glob)test*.py' ':(glob)**/*_test.py'
# ('*test*.py' would also match helpers and fixtures under a tests/ folder)
git ls-files <T> | cut -d/ -f1-2 | sort | uniq -c | sort -rn
git grep -cE "^[[:space:]]*(async )?def test" -- <T> | awk -F: '{s+=$2} END {print s}'
python3 -m unittest discover --durations 25    # Python 3.12+; use the repo's start dir

# EMPTY-ASSERTION
git grep -L -E "assert|self\.fail|pytest\.raises" -- <T> | head
git grep -nE "assertIsNotNone\(|assertTrue\((True|1)\)" -- <T> | head -50

# INTERNALS: mocks of the unit's own siblings
git grep -cE "mock\.patch|@patch" -- <T> | sort -t: -k2 -rn | head -20
```
