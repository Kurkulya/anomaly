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

from anomaly_loop import docscan, gitrepo
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
        with self.subTest('the count line is singular for one finding'):
            self.assertEqual(result[1].splitlines()[-1], 'docs scan: 1 finding, 0 in files the range changes')


    def test_the_output_has_one_line_naming_the_resolved_adr_folder(self):
        """AC-50 (Amended, cumulative review): a port value that names no folder of the repo (a URL, `..`) is read as
        `docs/adr`, and the one line says so, so a wrong value is not silent. The repo has no finding."""
        base = self.commit({'README.md': '# Demo\n'}, 'docs: plant', 1)
        head = self.commit({'README.md': '# Demo\nChanged.\n'}, 'docs: readme', 2)
        for value, resolved in (('docs/adr/', 'docs/adr'), ('decisions/', 'decisions'),
                                ('https://wiki.example.invalid/adr', 'docs/adr'), ('..', 'docs/adr')):
            with self.subTest(adr_folder=value):
                write_text(self.home / 'profile.md', f'---\nadr_folder: {value}\n---\n')
                code, out, err = self.scan(f'{base}..{head}')
                self.assertEqual((code, err), (0, ''), out)
                self.assertEqual(len([line for line in out.splitlines() if resolved in line]), 1, out)


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


TODAY = date(2026, 10, 4)


class DeferralRuleTest(unittest.TestCase):
    """Unit: `deferral_findings` reads a deferral only where one is written, and a key by its own shape."""

    def found(self, *lines):
        return [(finding.line, finding.kind) for finding in docscan.deferral_findings('f.py', list(lines), TODAY)]

    def test_the_word_is_a_deferral_as_the_first_word_of_a_comment_a_line_or_a_list_item(self):
        lines = [f'# {DEFERRAL} fix the parser', f'{DEFERRAL}: drop this', f'- {DEFERRAL} write this',
                 f'value = 1  // {DEFERRAL} after code', f'* [ ] {DEFERRAL} a box', f'- [x] {DEFERRAL} a ticked box',
                 f'> {DEFERRAL} quoted', f'1. {DEFERRAL} numbered', f'  <!-- {DEFERRAL} html -->',
                 f'-- {DEFERRAL} sql', f'/* {DEFERRAL} c */']
        self.assertEqual(self.found(*lines), [(number, docscan.TODO_UNKEYED) for number in range(1, len(lines) + 1)])

    def test_a_mention_in_the_middle_of_code_or_of_a_sentence_or_the_key_shape_is_not_one(self):
        self.assertEqual(self.found(
            f"pattern = re.compile(r'{DEFERRAL}\\(')", f'"""A sentence with no {DEFERRAL} key here."""',
            f"owner = f'{DEFERRAL}(VK, revisit {{date}})'", f'# {DEFERRAL}(<owner>, revisit YYYY-MM-DD) is the shape',
            f'# the note `{DEFERRAL}: later` is quoted'), [])

    def test_a_key_with_a_date_that_is_not_real_counts_as_no_key(self):
        self.assertEqual(self.found(f'# {DEFERRAL}(VK, revisit 2026-13-45): later'), [(1, docscan.TODO_UNKEYED)])

    def test_a_key_is_overdue_only_before_today_and_is_read_wherever_it_stands(self):
        self.assertEqual(self.found(
            f'# {DEFERRAL}(VK, revisit 2026-09-01): old', f'# {DEFERRAL}(VK, revisit 2026-10-04): today',
            f'# {DEFERRAL}(VK, revisit 2026-11-05): not yet', f'the key `{DEFERRAL}(VK, revisit 2026-09-01)` is old'),
            [(1, docscan.TODO_OVERDUE), (4, docscan.TODO_OVERDUE)])


class AdrRevisitTest(unittest.TestCase):
    """Unit: `adr_findings` takes the revisit date from the status line, else from the front block."""

    def found(self, *lines):
        return [(finding.line, finding.kind) for finding in docscan.adr_findings('docs/adr/0001-x.md', list(lines), TODAY)]

    def test_a_superseded_adr_is_skipped(self):
        self.assertEqual(self.found('# ADR-0001: x', '', 'Status: Superseded by ADR-0009 · Revisit-by: 2026-09-01'), [])

    def test_the_revisit_by_field_wins_over_the_front_block_line(self):
        past, future = '2026-08-15', '2026-12-01'
        with self.subTest('a future field and a past front-block line: not overdue'):
            self.assertEqual(self.found('# ADR-0001: x', f'Status: Accepted · Revisit-by: {future}', '',
                                        f'Revisit: {past}.'), [])
        with self.subTest('a past field and a future front-block line: overdue at the status line'):
            self.assertEqual(self.found('# ADR-0001: x', f'Status: Accepted · Revisit-by: {past}', '',
                                        f'Revisit: {future}.'), [(2, docscan.ADR_OVERDUE)])

    def test_a_revisit_line_below_the_first_heading_is_not_read(self):
        self.assertEqual(self.found('# ADR-0001: x', 'Status: Accepted', '', '## Revisit', 'Revisit: 2026-08-15.'), [])


class AdrPathsTest(unittest.TestCase):
    """Unit: `adr_paths` finds `NNNN-*.md` in the ADR folder and in the adr/ of every unit folder."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        for relative in ('docs/adr/0001-a.md', 'docs/adr/notes.md', 'decisions/0005-e.md', '.anomaly/u/adr/0002-b.md',
                         '.scratch/u/adr/0003-c.md', 'other/0004-d.md'):
            write_text(self.root / relative, 'x\n')

    def test_the_adr_folder_and_the_unit_adr_folders_are_read_and_nothing_else(self):
        units = {'.anomaly/u/adr/0002-b.md', '.scratch/u/adr/0003-c.md'}
        for adr_folder, expected in (('docs/adr/', {'docs/adr/0001-a.md'}), ('decisions/', {'decisions/0005-e.md'}),
                                     ('https://wiki.example.invalid/adr', {'docs/adr/0001-a.md'})):
            with self.subTest(adr_folder=adr_folder):
                self.assertEqual(docscan.adr_paths(self.root, adr_folder), expected | units)


class PathClaimTest(unittest.TestCase):
    """Unit: `path_claims` reads the relative path claims of a line."""

    def test_a_backticked_path_a_bare_file_and_a_link_target_are_claims(self):
        self.assertEqual(docscan.path_claims('Use `src/a.py` and `README.md`, see [it](docs/b.md#top) and `a b/c`.'),
                         ['src/a.py', 'README.md', 'docs/b.md'])

    def test_urls_anchors_globs_placeholders_and_plain_words_are_not_claims(self):
        self.assertEqual(docscan.path_claims(
            'See [x](https://example.invalid/a/b.md), [y](#top), `src/*.py`, `<dir>/x.py`, `file:line`, `word`, '
            '`/abs/p.py`, `python -m unittest`.'), [])

    def test_a_trailing_line_number_or_range_is_cut_off_the_claim(self):
        self.assertEqual(docscan.path_claims('Cites `src/gone.py:12` and `docs/b.md:3-9`.'),
                         ['src/gone.py', 'docs/b.md'])


class PathLivenessTest(unittest.TestCase):
    """Unit: `dead_path_findings` calls a claim live beside the CLAUDE.md or at the root, or when a tracked file or
    folder equals it or ends with `/<claim>`; a path git ignores is live; a fenced block is not read."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.repo = GitFixture(Path(tmp.name).resolve() / 'repo')
        files = {'tools/scripts/tool.py': 'X = 1\n', 'docs/deep/GUIDE.md': '# Guide\n', 'lib/vendor/a.txt': 'a\n',
                 'sub/helper.py': 'X = 1\n', 'top.py': 'X = 1\n', 'README.md': '# Demo\n'}
        for relative, text in files.items():
            self.repo.write(relative, text)
        self.repo.commit(list(files), 'docs: plant', date(2026, 10, 1))

    def dead(self, path, *lines):
        tracked = gitrepo.tracked_files(self.repo.root)
        return [finding.detail for finding in docscan.dead_path_findings(self.repo.root, path, list(lines), tracked)]

    def test_a_tracked_file_or_folder_that_is_the_claim_or_ends_with_it_makes_it_live(self):
        self.assertEqual(self.dead(
            'CLAUDE.md', 'Use `scripts/tool.py`, read `GUIDE.md`, see `vendor/` and `lib/vendor`.'), [])

    def test_a_claim_no_tracked_path_matches_by_whole_parts_is_dead(self):
        self.assertEqual(self.dead('CLAUDE.md', 'Is `gone/missing.py`, `NOPE.md`, `cripts/tool.py`, `ool.py`.'),
                         ['gone/missing.py does not exist', 'NOPE.md does not exist', 'cripts/tool.py does not exist',
                          'ool.py does not exist'])

    def test_a_claim_beside_the_claude_file_or_at_the_root_is_live(self):
        self.assertEqual(self.dead('sub/CLAUDE.md', 'Uses `helper.py` and `top.py`.'), [])

    def test_a_claim_inside_a_fenced_block_is_not_read(self):
        self.assertEqual(self.dead('CLAUDE.md', '```', 'See `gone/missing.py`.', '```', 'After `NOPE.md`.'),
                         ['NOPE.md does not exist'])

    def test_a_path_under_a_unit_home_folder_is_live_when_it_is_neither_on_disk_nor_ignored(self):
        """`.anomaly/` and `.scratch/` hold local work units: a clone has neither, and does not ignore them."""
        self.assertEqual(self.dead('CLAUDE.md', 'Units: `.anomaly/`, `.scratch/x.md`, `.anomaly/u/tickets/`, `.other/`.'),
                         ['.other/ does not exist'])

    def test_a_claim_outside_the_repository_is_not_checked(self):
        """A path that climbs out of the repo cannot be checked against it, so it is no finding; a dead claim in
        the same line still is."""
        self.assertEqual(self.dead('CLAUDE.md', 'See `../../outside.md`, [up](../up.md) and `gone/missing.py`.'),
                         ['gone/missing.py does not exist'])

    def test_a_path_that_git_ignores_is_live_whether_or_not_it_is_on_disk(self):
        """An ignored folder that is not a unit home is in one checkout only: a clone must not report it. Without the
        git check, `build/` and `build/out.js` are on no disk, in no unit home and in no tracked path, so dead."""
        self.repo.write('.git/info/exclude', 'build/\n')
        self.assertEqual(self.dead('CLAUDE.md', 'Local output: `build/`, `build/out.js`, and `.other/`.'),
                         ['.other/ does not exist'])


if __name__ == '__main__':
    unittest.main()
