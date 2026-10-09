"""Tests for `mr body <work unit folder | ad-hoc ticket>` (ticket 06), CLI in-process over a temporary git
repository. The unit fixture is a folder `.anomaly/demo-unit/` with stories.md, decisions.md and three tickets;
two tickets are merged with `--no-ff` merge commits whose subjects are `chore(<key>): merge <NN-slug>`, the third
is not merged. The ad-hoc fixture is a ticket written by `ticket adhoc` on a branch with three commits.

The body file starts with a `Title: <type>(<key>): <summary>` line and a blank line; the sections are markdown
headings (`## Why`, ...). Assertions name headings, ids and facts, never wording beyond what the ACs fix.
`--repo` names the fixture repository, as in `check` and `ticket`; the docs-gate flag of Tested is never passed."""
import re
import tempfile
import unittest
from datetime import date
from pathlib import Path

from anomaly_loop import mr
from anomaly_loop.files import RecordError
from tests.fixtures import GitFixture, run_cli, write_text
from tests.test_check import slice_ticket

DAY = date(2026, 10, 1)
UNIT = 'demo-unit'
KEY = 'ABC-7'
SECTIONS = ['why', 'what changed', 'acceptance criteria', 'still open', 'breaking changes', 'tested',
            'how to review']
WHY = 'readers of the widget list stop seeing stale rows'
OPEN_ITEM = 'flaky retry in alpha'
BREAKING = ('callers of the widget list must pass the new flag', 'the old widget flag is removed')
TITLES = {'01': 'Alpha adds the widget list', '02': 'Bravo renames the widget flag',
          '03': 'Charlie documents the widget'}
DIFF_WORD = 'zephyrquartz'      # only in the content of a tracked source file
INNER_WORD = 'quokkarefactor'   # only in the subject of a commit inside a merged branch
HEX_ID = re.compile(r'\b(?=[0-9a-f]*\d)[0-9a-f]{7,40}\b')
ATTRIBUTION = ('co-authored-by', 'generated with')
TRAILER = 'Co-Authored-By: Helper <helper@example.invalid>'


def sections(body):
    """{lower-case heading: its non-blank lines} for the markdown headings of a body."""
    found, current = {}, None
    for line in body.splitlines():
        heading = re.match(r'#{1,6}\s+(.*?)\s*:?\s*$', line)
        if heading:
            current = heading.group(1).lower()
            found[current] = []
        elif current is not None and line.strip():
            found[current].append(line)
    return found


class MrCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        self.home = self.root / 'home'
        self.home.mkdir()
        self.repo = GitFixture(self.root / 'repo')
        self.repo.write('README.md', 'base\n')
        self.repo.commit(['README.md'], 'chore: base', DAY)
        self.repo.git('branch', '-M', 'main')
        self.merges = []

    def run_body(self, target, *flags):
        return run_cli('mr', 'body', str(target), *flags, '--repo', str(self.repo.root), '--home', str(self.home))

    def make(self, target, *flags):
        """Run `mr body` and require exit 0; returns (stdout, stderr)."""
        code, out, err = self.run_body(target, *flags)
        self.assertEqual(code, 0, (out, err))
        return out, err

    def read(self, path):
        """(title, body) of a written body file: a Title line, a blank line, then the body."""
        lines = Path(path).read_text(encoding='utf-8').splitlines()
        self.assertTrue(lines and lines[0].startswith('Title: '), lines[:2])
        self.assertEqual(lines[1], '', lines[:3])
        return lines[0][len('Title: '):], '\n'.join(lines[2:])


class UnitCase(MrCase):
    def merge_ticket(self, number, slug):
        """Merge a branch of one commit into main with a `chore(<key>): merge <NN-slug>` subject; returns the id."""
        branch = f'feat/{number}-{slug}'
        self.repo.git('checkout', '-q', '-b', branch)
        self.repo.write(f'src/{slug}.txt', f'{DIFF_WORD} in {slug}\n')
        self.repo.commit([f'src/{slug}.txt'], f'feat({KEY}): {INNER_WORD} {slug}\n\n{TRAILER}', DAY)
        self.repo.git('checkout', '-q', 'main')
        self.repo.git('merge', '--no-ff', '-q', '-m', f'chore({KEY}): merge {number}-{slug}', '-m', TRAILER,
                      branch, when=DAY)
        merge = self.repo.git('rev-parse', 'HEAD').strip()
        self.merges.append(merge)
        return merge

    def ticket(self, number, slug, covers, ac_ids, status='ready-for-agent', title=None):
        text = slice_ticket(number, covers=covers, status=status, jira=KEY, key_line='Key',
                            body='\n' + ''.join(f'- [ ] {ac}: criterion {ac}\n' for ac in ac_ids))
        path = self.repo.root / '.anomaly' / UNIT / 'tickets' / f'{number}-{slug}.md'
        write_text(path, text.replace(': A ticket\n', f': {title or TITLES[number]}\n', 1))
        return path

    def close(self, path, slug, merge, open_items):
        code, out, err = run_cli('ticket', 'result', str(path), '--branch', f'feat/{path.name[:2]}-{slug}',
                                 '--merge', merge, '--open', open_items, '--suites', '2', '--type-checks', '1',
                                 '--reviewer-passes', '1', '--high', '0', '--fix-rounds', '0',
                                 '--repo', str(self.repo.root), '--home', str(self.home))
        self.assertEqual((code, err), (0, ''), out)

    def unit(self, open_items=(OPEN_ITEM, 'none'), breaking=BREAKING, long_text=False, first_title=None,
             decision_lines=()):
        """The unit folder: AC-1 to AC-4, tickets 01 and 02 merged and done (01 covers AC-1 and AC-2, 02 covers
        AC-3), ticket 03 (AC-4) not merged. `long_text` gives the unit a long heading, Why and first ticket title;
        `first_title` sets that title; `decision_lines` are added to decisions.md. The word MERGE in an open item or
        a breaking line becomes the id of the first merge commit."""
        folder = self.repo.root / '.anomaly' / UNIT
        heading = 'Make the widget list reliable and show it to every reader ' * (3 if long_text else 1)
        why = (WHY + ' and ') * (4 if long_text else 1) + 'then ship once'
        write_text(folder / 'stories.md', f'# {heading.strip()}\nSources: chat · Gathered: 2026-10-01\nWhy: {why}\n'
                                          'Rules for all stories: none\n\n## 1. As a dev, I want a, so that b.\n'
                                          '- AC-1: criterion AC-1\n- AC-2: criterion AC-2\n- AC-3: criterion AC-3\n'
                                          '- AC-4: criterion AC-4\n')
        first = self.ticket('01', 'alpha', 'AC-1, AC-2', ('AC-1', 'AC-2'), status='in-progress',
                            title=first_title or TITLES['01'] + (' with a very long title that goes on and on and on'
                                                                 if long_text else ''))
        second = self.ticket('02', 'bravo', 'AC-3', ('AC-3',), status='in-progress')
        self.ticket('03', 'charlie', 'AC-4', ('AC-4',))
        self.close(first, 'alpha', self.merge_ticket('01', 'alpha'), open_items[0].replace('MERGE', self.merges[0]))
        self.close(second, 'bravo', self.merge_ticket('02', 'bravo'), open_items[1].replace('MERGE', self.merges[0]))
        write_text(folder / 'decisions.md', '- D-1: pick x. Why: simple. Source: user, 2026-10-01\n'
                   + ''.join(f'- Breaking: {line.replace("MERGE", self.merges[0])}\n' for line in breaking)
                   + ''.join(f'{line}\n' for line in decision_lines))
        return folder

    def body_of(self, folder, *flags):
        self.make(folder, *flags)
        return self.read(folder / 'mr-body.md')


class BodyTest(UnitCase):
    def test_a_unit_with_every_fact_has_the_seven_sections_with_their_facts(self):
        """AC-33."""
        title, body = self.body_of(self.unit())
        found = sections(body)
        self.assertEqual([name for name in found if name in SECTIONS], SECTIONS, body)
        self.assertIn(WHY, ' '.join(found['why']))
        what = found['what changed']
        self.assertEqual(len(what), 2, what)
        self.assertTrue(TITLES['01'] in what[0] and TITLES['02'] in what[1], what)
        self.assertNotIn(TITLES['03'], body)
        criteria = ' '.join(found['acceptance criteria'])
        self.assertIn('3 of 4', criteria)
        self.assertIn('AC-4', criteria)
        still_open = ' '.join(found['still open'])
        self.assertIn(OPEN_ITEM, still_open)
        self.assertNotIn('none', still_open)
        breaking = ' '.join(found['breaking changes'])
        self.assertTrue(all(line in breaking for line in BREAKING), breaking)
        tested = ' '.join(found['tested'])
        self.assertIn('type-checks 2', tested)   # 1 on each of the two merged tickets
        self.assertTrue(found['how to review'])
        self.assertIn('no CI ran', body)

    def test_a_unit_with_no_open_item_and_no_breaking_line_leaves_those_sections_out(self):
        """AC-33: every Result line says `Open: none` and decisions.md has no `Breaking:` line."""
        _, body = self.body_of(self.unit(open_items=('none', 'none'), breaking=()))
        found = sections(body)
        self.assertNotIn('still open', found, body)
        self.assertNotIn('breaking changes', found, body)
        for name in ('why', 'what changed', 'acceptance criteria', 'tested'):
            self.assertTrue(found.get(name), (name, body))

    def test_no_ci_ran_is_left_out_when_the_ci_port_is_set(self):
        """AC-33: the words belong to the core default of the `ci` port."""
        write_text(self.home / 'profile.md', '---\nci: some-ci-tool\n---\n')
        _, body = self.body_of(self.unit())
        self.assertNotIn('no CI ran', body)

    def test_draft_writes_the_why_then_work_in_progress(self):
        """AC-34."""
        folder = self.unit()
        self.make(folder, '--draft')
        lines = (folder / 'mr-body.md').read_text(encoding='utf-8').splitlines()
        self.assertTrue(lines[0].startswith('Title: '), lines[:2])
        self.assertEqual(lines[1], '')
        body = lines[2:]
        self.assertEqual(len(body), 2, body)
        self.assertIn(WHY, body[0])
        self.assertTrue(body[1].startswith('Work in progress'), body)

    def test_the_body_holds_no_commit_id_table_row_or_attribution_line(self):
        """AC-36: the Result lines hold merge ids and the merge commits carry a trailer; none gets in."""
        title, body = self.body_of(self.unit())
        for text in (title, body):
            for merge in self.merges:
                self.assertNotIn(merge[:7], text)
            self.assertIsNone(HEX_ID.search(text), text)
            self.assertFalse([line for line in text.splitlines() if line.count('|') >= 2], text)
            self.assertFalse([name for name in ATTRIBUTION if name in text.lower()], text)

    def test_a_commit_id_or_a_pipe_in_an_open_item_or_a_breaking_line_is_scrubbed(self):
        """AC-36: the full merge id, a 7-character id and `a|b` are written into an open item and a breaking line."""
        short = '1a2b3c4'
        folder = self.unit(open_items=(f'retry MERGE and {short} fails', 'a|b stays'),
                           breaking=(f'drops MERGE and {short} for a|b',))
        title, body = self.body_of(folder)
        self.assertIn('retry', body)
        self.assertIn('drops', body)
        self.assertIn('a/b', body)
        for text in (title, body):
            self.assertNotIn(self.merges[0][:7], text)
            self.assertNotIn(short, text)
            self.assertNotIn('|', text)

    def test_a_title_that_only_mentions_attribution_words_stays_in_what_changed(self):
        """AC-36: only a line that starts as an attribution line is dropped."""
        title = 'Show reports generated with the new engine'
        _, body = self.body_of(self.unit(first_title=title))
        self.assertIn(title, ' '.join(sections(body)['what changed']))

    def test_the_docs_gate_result_is_in_tested(self):
        """AC-33."""
        _, body = self.body_of(self.unit(), '--docs-gate', 'no stale doc found')
        self.assertIn('no stale doc found', ' '.join(sections(body)['tested']))

    def test_a_decision_line_with_a_number_before_the_prefix_is_a_breaking_line(self):
        """AC-33 and formats.md: a prefix may follow the D-n id; the fact is the decision, not its Why or Source."""
        _, body = self.body_of(self.unit(breaking=(), decision_lines=(
            '- D-4: Breaking: callers must pass the numbered flag. Why: tests. Source: user, 2026-10-01',)))
        breaking = ' '.join(sections(body)['breaking changes'])
        self.assertIn('callers must pass the numbered flag', breaking)
        self.assertNotIn('Source:', breaking)

    def test_a_target_inside_a_unit_ticket_folder_is_refused_and_writes_nothing(self):
        """A file target is an ad-hoc ticket: a ticket of a unit never gets a sibling body file."""
        folder = self.unit()
        ticket = folder / 'tickets' / '01-alpha.md'
        code, out, err = self.run_body(ticket)
        self.assertEqual(code, 2, (out, err))
        self.assertTrue(err.startswith('anomaly: '), err)
        self.assertEqual(sorted(p.name for p in ticket.parent.iterdir()),
                         ['01-alpha.md', '02-bravo.md', '03-charlie.md'])

    def test_a_body_over_2_5_kb_prints_a_warning_and_is_still_written(self):
        """AC-36."""
        breaking = [f'change number {n} that every caller of the widget api has to absorb before it upgrades'
                    for n in range(30)]
        folder = self.unit(breaking=breaking)
        out, err = self.make(folder)
        self.assertIn('warning', (out + err).lower())
        self.assertGreater((folder / 'mr-body.md').stat().st_size, 2560)

    def test_a_small_body_prints_no_warning(self):
        """AC-36."""
        folder = self.unit()
        out, err = self.make(folder)
        self.assertLess((folder / 'mr-body.md').stat().st_size, 2500)
        self.assertNotIn('warning', (out + err).lower())

    def test_the_title_is_type_key_summary_and_under_70_characters(self):
        """AC-36: a long heading, Why and ticket title force a cut."""
        title, _ = self.body_of(self.unit(long_text=True))
        self.assertRegex(title, rf'^[a-z]+\({re.escape(KEY)}\): \S')
        self.assertLess(len(title), 70, title)

    def test_facts_come_from_the_files_and_merge_subjects_and_never_the_diff(self):
        """AC-37: a word only in a tracked source file, and one only in the subject of a commit inside a merged branch."""
        title, body = self.body_of(self.unit())
        for word in (DIFF_WORD, INNER_WORD):
            self.assertNotIn(word, title + body)


class FactTest(unittest.TestCase):
    def test_a_line_that_starts_as_an_attribution_line_is_dropped(self):
        """AC-36."""
        for text in ('Co-Authored-By: Helper <helper@example.invalid>', 'Generated with Some Tool', '  generated with x'):
            with self.subTest(text=text):
                self.assertEqual(mr.plain(text), '')

    def test_a_word_of_digits_only_is_not_a_commit_id(self):
        """AC-36: a commit id holds a digit and a letter a-f; a long count stays."""
        self.assertEqual(mr.plain('raise the limit to 10000000 rows'), 'raise the limit to 10000000 rows')
        self.assertEqual(mr.plain('fixed in 1a2b3c4 today'), 'fixed in today')

    def test_a_summary_that_is_only_punctuation_has_no_title(self):
        """AC-36."""
        with self.assertRaises(RecordError):
            mr.title_line('feat', KEY, '---')


class AdhocCase(MrCase):
    TASK = 'make the widget list handle empty input'
    SUBJECTS = ('handle empty widget list', 'cover the empty widget list', 'note the widget list rule')

    def setUp(self):
        super().setUp()
        self.repo.write('earlier.txt', 'x\n')
        self.repo.commit(['earlier.txt'], 'feat: earlier main work on gadgets', DAY)
        code, out, err = run_cli('ticket', 'adhoc', self.TASK, '--slug', 'fix-widget-list',
                                 '--repo', str(self.repo.root), '--home', str(self.home))
        self.assertEqual((code, err), (0, ''))
        self.ticket = Path(out.strip())
        self.repo.git('checkout', '-q', '-b', 'fix/widget-list')
        for index, subject in enumerate(self.SUBJECTS):
            self.repo.write(f'src/part{index}.txt', f'{DIFF_WORD} {index}\n')
            trailer = '\n\nGenerated with Some Tool' if index == 0 else ''
            self.repo.commit([f'src/part{index}.txt'], f'{("fix", "test", "docs")[index]}(no-ticket): {subject}{trailer}', DAY)

    def body_file(self):
        return self.ticket.with_name(self.ticket.stem + '.mr-body.md')


class AdhocBodyTest(AdhocCase):
    def test_the_body_has_the_why_and_the_commit_subjects_in_a_sibling_file(self):
        """AC-35."""
        self.make(self.ticket)
        self.assertEqual(self.body_file().parent.name, 'adhoc')
        self.assertTrue(self.body_file().is_file())
        _, body = self.read(self.body_file())
        found = sections(body)
        self.assertIn(self.TASK, ' '.join(found.get('why', [])), body)
        changed = ' '.join(found.get('what changed', []))
        self.assertTrue(all(subject in changed for subject in self.SUBJECTS), changed)
        self.assertNotIn('earlier main work on gadgets', body)
        self.assertFalse((self.ticket.parent / 'mr-body.md').exists())

    def test_the_light_path_body_holds_no_commit_id_table_row_or_attribution_line(self):
        """AC-36: a commit of the branch carries a trailer; it stays out."""
        self.make(self.ticket)
        title, body = self.read(self.body_file())
        for text in (title, body):
            self.assertIsNone(HEX_ID.search(text), text)
            self.assertFalse([line for line in text.splitlines() if line.count('|') >= 2], text)
            self.assertFalse([name for name in ATTRIBUTION if name in text.lower()], text)

    def test_the_light_path_title_is_type_key_summary_and_under_70_characters(self):
        """AC-36."""
        long_task = 'make the widget list handle empty input and also keep every row in the same order as before'
        code, out, err = run_cli('ticket', 'adhoc', long_task, '--slug', 'long-task',
                                 '--repo', str(self.repo.root), '--home', str(self.home))
        self.assertEqual((code, err), (0, ''))
        other = Path(out.strip())
        self.make(other)
        title, _ = self.read(other.with_name(other.stem + '.mr-body.md'))
        self.assertRegex(title, r'^[a-z]+\([^)\s]+\): \S')
        self.assertLess(len(title), 70, title)

    def test_the_light_path_title_takes_its_type_from_the_branch_prefix(self):
        """AC-36: branch `fix/widget-list`, a ticket with no key line."""
        self.make(self.ticket)
        title, _ = self.read(self.body_file())
        self.assertTrue(title.startswith('fix(no-ticket): '), title)

    def test_the_docs_gate_flag_is_refused_for_an_adhoc_ticket(self):
        """The light-path body has no Tested section."""
        code, out, err = self.run_body(self.ticket, '--docs-gate', 'clean')
        self.assertEqual(code, 2, (out, err))
        self.assertIn('--docs-gate', err)
        self.assertFalse(self.body_file().exists())

    def test_draft_writes_the_why_then_work_in_progress_for_an_adhoc_ticket(self):
        """AC-34."""
        self.make(self.ticket, '--draft')
        lines = self.body_file().read_text(encoding='utf-8').splitlines()
        self.assertEqual(lines[1], '')
        self.assertEqual(len(lines[2:]), 2, lines)
        self.assertIn(self.TASK, lines[2])
        self.assertTrue(lines[3].startswith('Work in progress'), lines)


if __name__ == '__main__':
    unittest.main()
