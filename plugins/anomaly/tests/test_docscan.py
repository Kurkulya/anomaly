"""`docs scan <range>` through the CLI, in-process, against a temporary git repository (AC-50): it reports
the docs-audit checks 1 to 3, each finding with its `file:line`: an ADR whose revisit date has passed, a
deferral note with no owner and revisit date, and a path in a `CLAUDE.md` that no longer exists. It marks the
findings that sit in files the range touches and exits 1 on any such finding. The fixture clock is
2026-10-04 (tests.fixtures.NOW)."""
import re
import tempfile
import unittest
from datetime import date
from pathlib import Path

from tests.fixtures import GitFixture, run_cli, write_text

# The deferral word is joined here so that this file holds no bare deferral note of its own.
DEFERRAL = 'TO' + 'DO'
LOCATION = re.compile(r'([\w./-]+\.(?:md|py)):(\d+)')

OVERDUE_ADR = """# ADR-0001: Overdue

Status: Accepted · Date: 2026-07-01 · Owner: VK · Revisit-by: 2026-09-01

Decision: a decision whose revisit date has passed.
"""
FUTURE_ADR = """# ADR-0002: Not yet due

Status: Accepted · Date: 2026-07-01 · Owner: VK · Revisit-by: 2026-12-01

Revisit: when a tracker needs more, or 2026-12-01.
"""
FRONT_BLOCK_ADR = """# ADR-0003: Front block date

Status: Accepted · Date: 2026-07-01 · Owner: VK

Decision: a decision with no Revisit-by field.
Revisit: 2026-08-15.
"""
NOTES = f"""\"\"\"Planted notes.\"\"\"

# {DEFERRAL}: tidy this up later
# {DEFERRAL}(VK, revisit 2026-11-05): replace the stub
VALUE = 1
"""
CLAUDE_MD = """# Demo

Run the helper `src/present.py` before a push.
The old helper lived in `src/missing.py`.
"""


def location_of(text, needle, path):
    """`path:line` of the first line of `text` that holds `needle`."""
    for number, line in enumerate(text.splitlines(), 1):
        if needle in line:
            return f'{path}:{number}'
    raise AssertionError(f'{needle!r} is not in {path}')


class DocsScanTestCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        self.home = self.root / 'home'
        self.home.mkdir()
        self.repo = GitFixture(self.root / 'repo')

    def commit(self, files, message, day):
        """Write these files (a path to text map), commit exactly them dated 2026-10-<day>; returns the id."""
        for relative, text in files.items():
            self.repo.write(relative, text)
        return self.repo.commit(list(files), message, date(2026, 10, day))

    def scan(self, range_spec):
        return run_cli('docs', 'scan', range_spec, '--repo', str(self.repo.root), '--home', str(self.home))

    def locations(self, result):
        """Every `file:line` of a successful run's stdout, in order; the run must have no stderr."""
        code, out, err = result
        self.assertEqual(err, '', out)
        return [f'{path}:{number}' for path, number in LOCATION.findall(out)]


class ScanFindingsTest(DocsScanTestCase):
    """AC-50: each finding kind is reported with its `file:line`, and nothing else is."""

    def test_overdue_adrs_unkeyed_deferrals_and_dead_claude_paths_are_reported_and_nothing_else(self):
        """Three kinds, four planted findings: an overdue `Revisit-by:`, a past `Revisit:` front-block
        line, an unkeyed deferral note, and a path in CLAUDE.md that does not exist are reported; a future ADR date,
        the keyed deferral note and an existing path are not."""
        base = self.commit({
            'docs/adr/0001-overdue.md': OVERDUE_ADR, 'docs/adr/0002-future.md': FUTURE_ADR,
            'docs/adr/0003-front-block.md': FRONT_BLOCK_ADR, 'src/notes.py': NOTES, 'src/present.py': 'X = 1\n',
            'CLAUDE.md': CLAUDE_MD}, 'docs: plant', 1)
        head = self.commit({'README.md': '# Demo\n'}, 'docs: readme', 2)

        result = self.scan(f'{base}..{head}')

        expected = [
            location_of(OVERDUE_ADR, 'Revisit-by: 2026-09-01', 'docs/adr/0001-overdue.md'),
            location_of(FRONT_BLOCK_ADR, 'Revisit: 2026-08-15', 'docs/adr/0003-front-block.md'),
            location_of(NOTES, f'# {DEFERRAL}: tidy', 'src/notes.py'),
            location_of(CLAUDE_MD, 'src/missing.py', 'CLAUDE.md'),
        ]
        self.assertEqual(sorted(self.locations(result)), sorted(expected), result)
        out = result[1]
        with self.subTest('the dead path is named on its finding line'):
            self.assertTrue(any(expected[3] in line and 'src/missing.py' in line for line in out.splitlines()), out)
        with self.subTest('the existing path is not named'):
            self.assertNotIn('src/present.py', out)

    def test_a_deferral_counts_only_as_the_first_word_of_a_comment_a_line_or_a_list_item(self):
        """The word after a comment marker, at the start of a line or of a list item is a deferral note; a mention
        in the middle of code or of a sentence, or the key shape with a placeholder owner, is not. A keyed note whose
        literal date has passed is reported where it stands."""
        notes = f"""pattern = re.compile(r'{DEFERRAL}\\(')
\"\"\"A sentence with no {DEFERRAL} key here.\"\"\"
owner = f'{DEFERRAL}(VK, revisit {{date}})'
# {DEFERRAL}(<owner>, revisit YYYY-MM-DD) is the key shape
# the note `{DEFERRAL}: later` is quoted in a span
# {DEFERRAL} fix the parser
{DEFERRAL}: drop this
- {DEFERRAL} write this
value = 1  // {DEFERRAL} after code
the key `{DEFERRAL}(VK, revisit 2026-09-01)` is old
# {DEFERRAL}(VK, revisit 2026-11-05): not yet due
"""
        base = self.commit({'src/shape.py': notes}, 'docs: plant', 1)
        head = self.commit({'README.md': '# Demo\n'}, 'docs: readme', 2)

        result = self.scan(f'{base}..{head}')

        expected = [location_of(notes, needle, 'src/shape.py')
                    for needle in (f'# {DEFERRAL} fix', f'{DEFERRAL}: drop', f'- {DEFERRAL} write', 'after code',
                                   'is old')]
        self.assertEqual(self.locations(result), expected, result)
        with self.subTest('the passed key is reported as overdue'):
            self.assertIn('todo-overdue', [line for line in result[1].splitlines() if expected[-1] in line][0])

    def test_a_path_claim_is_live_when_a_tracked_path_equals_it_or_ends_with_it(self):
        """A claim found nowhere beside the CLAUDE.md or at the root is live when a tracked file or folder is the
        claim or ends with `/<claim>` (whole path parts only); it is dead when no tracked path matches."""
        claude = """# Demo

Use `scripts/tool.py` for it.
Read `GUIDE.md` first, and see the `vendor/` folder.
The old file `gone/missing.py` is gone.
So is `NOPE.md`.
A part of a name, `cripts/tool.py`, is not a path of the repo.
"""
        base = self.commit({'tools/scripts/tool.py': 'X = 1\n', 'docs/deep/GUIDE.md': '# Guide\n',
                            'lib/vendor/a.txt': 'a\n', 'CLAUDE.md': claude}, 'docs: plant', 1)
        head = self.commit({'README.md': '# Demo\n'}, 'docs: readme', 2)

        result = self.scan(f'{base}..{head}')

        expected = [location_of(claude, needle, 'CLAUDE.md')
                    for needle in ('gone/missing.py', 'So is', 'is not a path of the repo')]
        self.assertEqual(self.locations(result), expected, result)
        out = result[1]
        for live in ('scripts/tool.py', 'GUIDE.md', 'vendor/'):
            with self.subTest(live=live):
                self.assertNotIn(f'{live} does not exist', out)

    def test_a_profile_adr_folder_moves_where_overdue_adrs_are_found(self):
        """AC-50 with the `adr_folder` port: a profile `adr_folder: decisions/` makes the scan read overdue ADRs from
        `decisions/` and not from `docs/adr/`."""
        write_text(self.home / 'profile.md', '---\nadr_folder: decisions/\n---\n')
        base = self.commit({'docs/adr/0001-overdue.md': OVERDUE_ADR, 'decisions/0002-overdue.md': OVERDUE_ADR},
                           'docs: plant', 1)
        head = self.commit({'README.md': '# Demo\n'}, 'docs: readme', 2)

        result = self.scan(f'{base}..{head}')

        expected = [location_of(OVERDUE_ADR, 'Revisit-by: 2026-09-01', 'decisions/0002-overdue.md')]
        self.assertEqual(self.locations(result), expected, result)


class ScanTouchedFilesTest(DocsScanTestCase):
    """AC-50: the findings in files the range touches are marked, and the exit code is 1 on any of them."""

    def setUp(self):
        super().setUp()
        self.base = self.commit({
            'docs/adr/0001-overdue.md': OVERDUE_ADR, 'src/notes.py': NOTES, 'src/present.py': 'X = 1\n',
            'CLAUDE.md': CLAUDE_MD, 'README.md': '# Demo\n'}, 'docs: plant', 1)
        self.adr = location_of(OVERDUE_ADR, 'Revisit-by: 2026-09-01', 'docs/adr/0001-overdue.md')
        self.note = location_of(NOTES, f'# {DEFERRAL}: tidy', 'src/notes.py')
        self.claude = location_of(CLAUDE_MD, 'src/missing.py', 'CLAUDE.md')
        self.every = [self.adr, self.note, self.claude]

    def lines_of(self, out, location):
        return [line for line in out.splitlines() if location in line]

    def touch(self, relative, day):
        """Append a line to a file that holds a finding (the finding keeps its line number) and commit it dated
        2026-10-<day>; returns the new commit id."""
        current = (self.repo.root / relative).read_text(encoding='utf-8')
        return self.commit({relative: current + 'Added later.\n'}, f'docs: touch {relative}', day)

    def test_exit_1_on_a_finding_in_a_touched_file_and_0_when_findings_are_only_in_untouched_files(self):
        """A range that touches only a file without findings exits 0 and still lists every finding, none marked. A
        range that touches the file of one finding exits 1 and marks that finding and no other."""
        readme_commit = self.commit({'README.md': '# Demo\nChanged.\n'}, 'docs: readme', 2)
        untouched = self.scan(f'{self.base}..{readme_commit}')
        self.assertEqual((untouched[0], untouched[2]), (0, ''), untouched)
        self.assertEqual(sorted(self.locations(untouched)), sorted(self.every), untouched)

        previous = readme_commit
        for number, (relative, touched) in enumerate(
                [('src/notes.py', self.note), ('CLAUDE.md', self.claude),
                 ('docs/adr/0001-overdue.md', self.adr)], 1):
            with self.subTest(touched=relative):
                head = self.touch(relative, 2 + number)
                result = self.scan(f'{previous}..{head}')
                previous = head
                self.assertEqual((result[0], result[2]), (1, ''), result)
                self.assertEqual(sorted(self.locations(result)), sorted(self.every), result)
                self.assertNotEqual(self.lines_of(result[1], touched), self.lines_of(untouched[1], touched),
                                    'the finding in the touched file is not marked')
                for other in self.every:
                    if other != touched:
                        self.assertEqual(self.lines_of(result[1], other), self.lines_of(untouched[1], other),
                                         f'{other} is marked but its file is not touched')


if __name__ == '__main__':
    unittest.main()
