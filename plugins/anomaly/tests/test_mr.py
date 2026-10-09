"""Tests for `mr body <work unit folder | ad-hoc ticket>` (ticket 06), CLI in-process over a temporary git
repository. The unit fixture is a folder `.anomaly/demo-unit/` with stories.md, decisions.md and three tickets;
two tickets are merged with `--no-ff` merge commits whose subjects are `chore(<key>): merge <NN-slug>`, the third
is not merged. The ad-hoc fixture is a ticket written by `ticket adhoc` on a branch with three commits.

The body file starts with a `Title: <type>(<key>): <summary>` line and a blank line; the sections are markdown
headings (`## Why`, ...). Assertions name headings, ids and facts, never wording beyond what the ACs fix.
`--repo` names the fixture repository, as in `check` and `ticket`; the docs-gate flag of Tested is never passed.

Ticket 07 adds `mr put`, `ready`, `show`, `reviewed` and `verified`. The two adapters are faked at their wrappers
(`FakeGh` for `anomaly_loop.gh.run`, a `FakeGlab` subclass for `anomaly_loop.glab.run`), so no test runs `gh` or
`glab` or touches a remote; a stub `gh` and `glab` first on PATH fail any call that would get past a fake. The
fakes sort a call by the words of its arguments (create, update, ready or show), not by one argument list, so an
adapter may use `gh pr ...`, `glab mr ...` or `glab api ...`."""
import collections
import json
import os
import re
import subprocess
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

from anomaly_loop import mr
from anomaly_loop.files import RecordError
from tests.fixtures import GitFixture, assert_cli_error, run_cli, write_text
from tests.test_check import slice_ticket
from tests.test_ci import FakeGlab

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
PRIVACY_PROBLEMS = ('write to jane.doe@example.com', 'see https://example.com/report?id=5')   # an email, a URL with a query


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

    def ticket(self, number, slug, covers, ac_ids, status='ready-for-agent', title=None, key=KEY):
        text = slice_ticket(number, covers=covers, status=status, key=key,
                            body='\n' + ''.join(f'- [ ] {ac}: criterion {ac}\n' for ac in ac_ids))
        if key is None:   # a ticket with no key line at all
            text = text.replace('Key: None\n', '', 1)
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
             decision_lines=(), keys=(KEY, KEY, KEY)):
        """The unit folder: AC-1 to AC-4, tickets 01 and 02 merged and done (01 covers AC-1 and AC-2, 02 covers
        AC-3), ticket 03 (AC-4) not merged. `long_text` gives the unit a long heading, Why and first ticket title;
        `first_title` sets that title; `decision_lines` are added to decisions.md; `keys` are the key lines of
        tickets 01, 02 and 03. The word MERGE in an open item or a breaking line becomes the id of the first merge
        commit."""
        folder = self.repo.root / '.anomaly' / UNIT
        heading = 'Make the widget list reliable and show it to every reader ' * (3 if long_text else 1)
        why = (WHY + ' and ') * (4 if long_text else 1) + 'then ship once'
        write_text(folder / 'stories.md', f'# {heading.strip()}\nSources: chat · Gathered: 2026-10-01\nWhy: {why}\n'
                                          'Rules for all stories: none\n\n## 1. As a dev, I want a, so that b.\n'
                                          '- AC-1: criterion AC-1\n- AC-2: criterion AC-2\n- AC-3: criterion AC-3\n'
                                          '- AC-4: criterion AC-4\n')
        first = self.ticket('01', 'alpha', 'AC-1, AC-2', ('AC-1', 'AC-2'), status='in-progress',
                            title=first_title or TITLES['01'] + (' with a very long title that goes on and on and on'
                                                                 if long_text else ''), key=keys[0])
        second = self.ticket('02', 'bravo', 'AC-3', ('AC-3',), status='in-progress', key=keys[1])
        self.ticket('03', 'charlie', 'AC-4', ('AC-4',), key=keys[2])
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
        self.assertIn(WHY[1:], ' '.join(found['why']))   # the first letter is a capital, see the capital-letter test
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
        self.assertIn(WHY[1:], body[0])   # the first letter is a capital, see the capital-letter test
        self.assertTrue(body[1].startswith('Work in progress'), body)

    def test_the_why_starts_with_a_capital_letter_in_the_body_and_in_the_draft_and_the_rest_is_unchanged(self):
        """Dogfood finding 3: the `Why:` line of the AC file is lower case; the full body Why section and the first
        line of the draft body both start with its capital form."""
        folder = self.unit()
        expected = f'{WHY[0].upper()}{WHY[1:]} and then ship once'
        _, body = self.body_of(folder)
        self.assertEqual(sections(body)['why'], [expected], body)
        self.make(folder, '--draft')
        lines = (folder / 'mr-body.md').read_text(encoding='utf-8').splitlines()
        self.assertEqual(lines[2], expected, lines)

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

    def assert_refused_for_privacy(self, folder, section):
        code, out, err = self.run_body(folder)
        self.assertEqual(code, 2, (out, err))
        self.assertTrue(err.startswith('anomaly: '), err)
        self.assertIn(section, err.lower())
        self.assertFalse((folder / 'mr-body.md').exists())

    def test_an_open_text_with_a_privacy_problem_is_refused_naming_the_section_and_writes_no_file(self):
        """AC-37 (Amended, cumulative review): facts that go to the MR are checked as `privacy` checks free text; an
        email address or a URL with a query string in an `Open:` text gives exit 2 and no body."""
        folder = self.unit()
        ticket = folder / 'tickets' / '01-alpha.md'
        original = ticket.read_text(encoding='utf-8')
        for problem in PRIVACY_PROBLEMS:
            with self.subTest(problem=problem):
                write_text(ticket, original.replace(OPEN_ITEM, f'{OPEN_ITEM}, {problem}'))
                self.assert_refused_for_privacy(folder, 'open')

    def test_a_why_line_with_a_privacy_problem_is_refused_naming_the_section_and_writes_no_file(self):
        """AC-37 (Amended, cumulative review): the same check for the Why line of the AC file."""
        folder = self.unit()
        stories = folder / 'stories.md'
        original = stories.read_text(encoding='utf-8')
        for problem in PRIVACY_PROBLEMS:
            with self.subTest(problem=problem):
                write_text(stories, original.replace(WHY, f'{WHY}, {problem}'))
                self.assert_refused_for_privacy(folder, 'why')

    def test_a_title_with_a_privacy_problem_is_refused_naming_the_title_and_writes_no_file(self):
        """AC-37 (Amended, cumulative review): the `Title:` line goes to the host too; its summary is the first heading
        of the AC file."""
        folder = self.unit()
        stories = folder / 'stories.md'
        original = stories.read_text(encoding='utf-8')
        for problem in PRIVACY_PROBLEMS:
            with self.subTest(problem=problem):
                write_text(stories, original.replace('# Make the widget list reliable and show it to every reader',
                                                     f'# {problem}'))
                self.assert_refused_for_privacy(folder, 'title')

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

    def assert_title_key(self, keys, expected):
        """Dogfood finding 2: tickets 01, 02 and 03 carry the key lines `keys`; the title holds `expected`."""
        title, _ = self.body_of(self.unit(keys=keys))
        self.assertTrue(title.startswith(f'feat({expected}): '), title)

    def title_on_branch(self, branch):
        """The title of a unit body made on `branch`, checked out after the unit is built (the build leaves main)."""
        folder = self.unit()
        self.repo.git('checkout', '-q', '-b', branch)
        title, _ = self.body_of(folder)
        return title

    def test_the_title_type_is_the_angular_type_before_the_first_slash_of_the_branch(self):
        self.assertTrue(self.title_on_branch('fix/widget-list').startswith(f'fix({KEY}): '))

    def test_the_title_type_is_feat_when_the_branch_prefix_is_no_angular_type(self):
        self.assertTrue(self.title_on_branch('widget/list').startswith(f'feat({KEY}): '))

    def test_the_title_key_is_the_key_every_keyed_ticket_shares(self):
        """Ticket 01 has no key line: a ticket without a key is skipped, the other two share the key."""
        self.assert_title_key((None, KEY, KEY), KEY)

    def test_the_title_key_is_the_unit_folder_name_when_the_keyed_tickets_have_different_keys(self):
        self.assert_title_key((KEY, 'ABC-9', KEY), UNIT)

    def test_a_no_ticket_key_counts_as_no_key_for_the_title(self):
        """The first ticket is the `no-ticket` one, so the old first-key rule would give `no-ticket`."""
        self.assert_title_key(('no-ticket', KEY, KEY), KEY)

    def test_the_title_key_is_no_ticket_when_no_ticket_has_a_key(self):
        self.assert_title_key(('no-ticket', 'no-ticket', 'no-ticket'), 'no-ticket')

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
        self.assertIn(self.TASK[1:], ' '.join(found.get('why', [])), body)
        self.assertEqual(found.get('why'), [self.TASK[0].upper() + self.TASK[1:]], body)   # a capital first letter, the rest as is
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
        self.assertIn(self.TASK[1:], lines[2])
        self.assertTrue(lines[3].startswith('Work in progress'), lines)


# ---------- mr put, ready, show, reviewed and verified (ticket 07) ----------

PROJECT_PATH = 'example-owner/example-repo'
LINKS = {'gh': f'https://example.com/{PROJECT_PATH}/pull/7',
         'glab': f'https://example.com/{PROJECT_PATH}/-/merge_requests/7'}
ORIGINS = {'gh': f'git@github.com:{PROJECT_PATH}.git', 'glab': f'git@gitlab.com:{PROJECT_PATH}.git'}
SELF_HOSTED = f'git@git.example.com:{PROJECT_PATH}.git'
MR_TITLE = 'feat(ABC-7): show the widget list'
MR_BODY_LINE = 'readers of the widget list stop seeing stale rows'
MR_BODY_FILE = f'Title: {MR_TITLE}\n\n## Why\n\n{MR_BODY_LINE}\n'
TOOL_FAILURE = 'the tool refused: the title is not allowed here'
Call = collections.namedtuple('Call', 'args text kind')


def attached_text(arg):
    """The text of the file an argument names (`path`, `--flag=path` or `field=@path`), else ''."""
    try:
        path = Path(arg.split('=', 1)[-1].lstrip('@'))
        return path.read_text(encoding='utf-8') if path.is_file() else ''
    except (OSError, ValueError):
        return ''


def classify(args):
    """What a call does, by the words of its arguments: 'ready', 'create', 'update' or (anything else) 'show'.
    A `glab api` call is sorted by its method (-X), or by its fields when it has no method."""
    words = [arg.lower() for arg in args]
    if 'ready' in words or re.search(r'draft\W{0,3}false', ' '.join(words)):
        return 'ready'
    method = next((words[i + 1].upper() for i, word in enumerate(words[:-1]) if word in ('-x', '--method')), None)
    has_fields = any(word in ('-f', '--field', '--raw-field', '--input') for word in words)
    if 'create' in words or method == 'POST' or (words[:1] == ['api'] and method is None and has_fields):
        return 'create'
    if 'edit' in words or 'update' in words or method in ('PUT', 'PATCH'):
        return 'update'
    return 'show'


def record(args, kwargs):
    """A Call: the arguments, the text they carry (the arguments, any file they name read now, and a piped
    input) and the kind. A body file may be gone when the test looks, so its text is read at call time."""
    text = ' '.join([*args, *(attached_text(arg) for arg in args), str(kwargs.get('input') or '')])
    return Call(args, text, classify(args))


def finished(tool, args, stdout='', code=0, stderr=''):
    return subprocess.CompletedProcess([tool, *args], code, stdout, stderr)


class FakeGh:
    """Stands for `gh.run`: records every call and answers as gh does (the link for a create or an edit, nothing
    for a ready, JSON for a view). `failure` set to a text makes every call fail with it."""

    def __init__(self):
        self.records, self.environs, self.failure = [], [], None
        self.source = None   # the source branch of the MR a view answers (`headRefName`); PutSetup sets the current branch

    def run(self, *args, environ=None, **kwargs):
        self.records.append(record(args, kwargs))
        self.environs.append(environ)
        if self.failure:
            return finished('gh', args, code=1, stderr=self.failure)
        kind = self.records[-1].kind
        stdout = {'create': LINKS['gh'] + '\n', 'update': LINKS['gh'] + '\n', 'ready': '',
                  'show': json.dumps({'url': LINKS['gh'], 'number': 7, 'state': 'OPEN', 'isDraft': True,
                                      'headRefName': self.source})}[kind]
        return finished('gh', args, stdout)


class FakeMrGlab(FakeGlab):
    """FakeGlab for the MR calls: the same recording and the same patch point (`glab.run`), answers by the kind of
    call instead of by API path (a `glab api` call gets JSON, a `glab mr` call the link or nothing)."""

    def __init__(self):
        super().__init__()
        self.records, self.failure = [], None
        self.source = None   # the source branch of the MR a view answers (`source_branch`); PutSetup sets the current branch
        self.ready_answer = json.dumps({'data': {'mergeRequestSetDraft': {'errors': []}}})   # the GraphQL answer

    def run(self, *args, environ=None, **kwargs):
        self.calls.append(args)
        self.environs.append(environ)
        self.records.append(record(args, kwargs))
        if self.failure:
            return finished('glab', args, code=1, stderr=self.failure)
        kind = self.records[-1].kind
        if kind == 'ready':
            return finished('glab', args, self.ready_answer)
        if args[:1] == ('api',) or kind == 'show':
            return finished('glab', args, json.dumps({'web_url': LINKS['glab'], 'iid': 7, 'state': 'opened',
                                                      'draft': True, 'source_branch': self.source}))
        return finished('glab', args, LINKS['glab'] + '\n' if kind in ('create', 'update') else '')


class PutSetup:
    """Mixin for MrCase or AdhocCase: both adapters faked at their wrappers, stub tools first on PATH, and (for a
    class with ADAPTER) the `mr` port and the `origin` remote of that adapter."""
    ADAPTER = None

    def setUp(self):
        super().setUp()
        self.gh, self.glab = FakeGh(), FakeMrGlab()
        self.has_origin = False
        self.block_real_tools()
        for target, replacement in (('anomaly_loop.glab.run', self.glab.run),
                                    ('anomaly_loop.glab.pause', self.glab.pauses.append),
                                    ('anomaly_loop.gh.run', self.gh.run)):
            patcher = mock.patch(target, replacement)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.gh.source = self.glab.source = self.repo.git('branch', '--show-current').strip()
        if self.ADAPTER:
            self.use(self.ADAPTER)

    def block_real_tools(self):
        """Stub `gh` and `glab` first on PATH that exit 97, so a call that got past a fake fails and reaches nothing."""
        bin_dir = self.root / 'bin'
        for name in ('gh', 'glab'):
            write_text(bin_dir / name, '#!/bin/sh\nexit 97\n')
            (bin_dir / name).chmod(0o755)
        patcher = mock.patch.dict(os.environ, {'PATH': os.pathsep.join([str(bin_dir), os.environ.get('PATH', '')])})
        patcher.start()
        self.addCleanup(patcher.stop)

    def set_port(self, adapter):
        write_text(self.home / 'profile.md', f'---\nmr_tool: {adapter}\n---\n')

    def point_origin(self, url):
        self.repo.git('remote', 'set-url' if self.has_origin else 'add', 'origin', url)
        self.has_origin = True

    def use(self, adapter, origin=None):
        self.set_port(adapter)
        self.point_origin(origin or ORIGINS[adapter])

    @property
    def fake(self):
        return {'gh': self.gh, 'glab': self.glab}[self.ADAPTER]

    @property
    def link(self):
        return LINKS[self.ADAPTER]

    def calls(self, kind):
        return [call for call in self.fake.records if call.kind == kind]

    def assert_no_tool_call(self):
        self.assertEqual((self.gh.records, self.glab.records), ([], []))

    def unit(self, link=None):
        """The unit folder with its body file, and an mr.md holding the MR line when a link is given."""
        folder = self.repo.root / '.anomaly' / UNIT
        write_text(folder / 'mr-body.md', MR_BODY_FILE)
        if link:
            write_text(folder / 'mr.md', f'MR: {link}\n')
        return folder

    def run_mr(self, action, target, *flags):
        return run_cli('mr', action, str(target), *flags, '--repo', str(self.repo.root), '--home', str(self.home))

    def mr_md_lines(self, mr_md):
        """The non-blank lines of an mr.md file."""
        return [line.strip() for line in Path(mr_md).read_text(encoding='utf-8').splitlines() if line.strip()]


class PutTests:
    """The behaviours of `mr put`, `ready` and `show` that hold for each adapter."""

    def test_put_creates_a_draft_mr_from_the_body_file_and_writes_the_link(self):
        """AC-42: the create call is a draft with the project, the title (not the Title: line) and the body."""
        folder = self.unit()
        code, out, err = self.run_mr('put', folder)
        self.assertEqual(code, 0, (out, err))
        creates = self.calls('create')
        self.assertTrue(creates, self.fake.records)
        text = creates[0].text
        self.assertIn('draft', text.lower())
        self.assertIn(MR_TITLE, text)
        self.assertIn(MR_BODY_LINE, text)
        self.assertNotIn('Title:', text)
        self.assertIn(PROJECT_PATH, text.replace('%2F', '/'))
        self.assertEqual(self.mr_md_lines(folder / 'mr.md'), [f'MR: {self.link}'])

    def test_put_updates_the_body_and_creates_nothing_when_mr_md_has_an_mr_line(self):
        """AC-42."""
        folder = self.unit(link=self.link)
        code, out, err = self.run_mr('put', folder)
        self.assertEqual(code, 0, (out, err))
        self.assertEqual(self.calls('create'), [])
        updates = self.calls('update')
        self.assertTrue(updates, self.fake.records)
        self.assertTrue(any(MR_BODY_LINE in call.text and 'Title:' not in call.text for call in updates), updates)
        self.assertEqual(self.mr_md_lines(folder / 'mr.md'), [f'MR: {self.link}'])

    def test_ready_marks_the_mr_of_mr_md_ready(self):
        """AC-43."""
        folder = self.unit(link=self.link)
        code, out, err = self.run_mr('ready', folder)
        self.assertEqual(code, 0, (out, err))
        ready = self.calls('ready')
        self.assertTrue(ready, self.fake.records)
        self.assertRegex(ready[0].text, r'\b7\b')
        self.assertEqual(self.calls('create'), [])

    def test_show_prints_the_link_and_the_state_and_changes_nothing(self):
        """AC-43: the fake says the MR is open."""
        folder = self.unit(link=self.link)
        code, out, err = self.run_mr('show', folder)
        self.assertEqual(code, 0, (out, err))
        self.assertIn(self.link, out)
        self.assertIn('open', out.lower())
        self.assertTrue(self.fake.records)
        self.assertEqual([call for call in self.fake.records if call.kind != 'show'], [])

    def test_a_failed_adapter_call_prints_the_tool_message_and_exits_non_zero(self):
        """AC-45: put (no mr.md yet, so a create), ready and show; a failed put writes no mr.md."""
        self.fake.failure = TOOL_FAILURE
        for action in ('put', 'ready', 'show'):
            with self.subTest(action=action):
                folder = self.unit(link=None if action == 'put' else self.link)
                code, out, err = self.run_mr(action, folder)
                self.assertNotEqual(code, 0, (out, err))
                self.assertIn(TOOL_FAILURE, out + err)
                self.assertNotIn('Traceback', out + err)
                if action == 'put':
                    self.assertFalse((folder / 'mr.md').exists())

    def test_a_self_hosted_origin_is_an_error_and_nothing_is_called(self):
        """Notes: the project is read from a github.com or a gitlab.com remote only; any other host is never guessed."""
        self.point_origin(SELF_HOSTED)
        folder = self.unit()
        assert_cli_error(self, self.run_mr('put', folder))
        self.assert_no_tool_call()
        self.assertFalse((folder / 'mr.md').exists())


    def test_put_refuses_a_body_file_with_a_privacy_problem_and_calls_nothing(self):
        """AC-37 (Amended, cumulative review): a body file edited by hand is checked again before it leaves the machine."""
        for problem in PRIVACY_PROBLEMS:
            with self.subTest(problem=problem):
                folder = self.unit()
                write_text(folder / 'mr-body.md', f'{MR_BODY_FILE}\n{problem}\n')
                code, out, err = self.run_mr('put', folder)
                self.assertEqual(code, 2, (out, err))
                self.assertTrue(err.startswith('anomaly: '), err)
                self.assert_no_tool_call()
                self.assertFalse((folder / 'mr.md').exists())
        with self.subTest('the Title: line'):
            folder = self.unit()
            write_text(folder / 'mr-body.md', f'Title: feat(no-ticket): {PRIVACY_PROBLEMS[0]}\n\n## Why\n\n{MR_BODY_LINE}\n')
            code, out, err = self.run_mr('put', folder)
            self.assertEqual(code, 2, (out, err))
            self.assertIn('title', err.lower())
            self.assert_no_tool_call()
            self.assertFalse((folder / 'mr.md').exists())

    def test_put_and_ready_refuse_an_mr_link_of_another_project_and_change_nothing(self):
        """AC-42 and AC-43 (Amended, cumulative review): the `MR:` link names another project than the origin."""
        other = self.link.replace(PROJECT_PATH, 'other-owner/other-repo')
        folder = self.unit(link=other)
        for action in ('put', 'ready'):
            with self.subTest(action=action):
                code, out, err = self.run_mr(action, folder)
                self.assertEqual(code, 2, (out, err))
                self.assertEqual([call for call in self.fake.records if call.kind != 'show'], [])

    def test_put_and_ready_refuse_an_mr_whose_source_branch_is_not_the_current_branch_and_change_nothing(self):
        """AC-42 and AC-43 (Amended, cumulative review): the view of the MR answers another source branch."""
        self.fake.source = 'feat/another-branch'
        folder = self.unit(link=self.link)
        for action in ('put', 'ready'):
            with self.subTest(action=action):
                code, out, err = self.run_mr(action, folder)
                self.assertEqual(code, 2, (out, err))
                self.assertEqual([call for call in self.fake.records if call.kind != 'show'], [])


class GhPutTest(PutTests, PutSetup, MrCase):
    ADAPTER = 'gh'

    def test_an_origin_project_of_three_parts_is_refused_and_nothing_is_called(self):
        """AC-42 (Amended, cumulative review): the gh adapter works with `owner/name` only; a group path is a gitlab shape."""
        self.point_origin('git@github.com:a/b/c.git')
        folder = self.unit()
        assert_cli_error(self, self.run_mr('put', folder))
        self.assert_no_tool_call()
        self.assertFalse((folder / 'mr.md').exists())


class GlabPutTest(PutTests, PutSetup, MrCase):
    ADAPTER = 'glab'


class PrintOnlyTest(PutSetup, MrCase):
    def assert_printed_and_unchanged(self, folder):
        code, out, err = self.run_mr('put', folder)
        self.assertEqual(code, 0, (out, err))
        self.assertIn(MR_TITLE, out)
        self.assertIn(MR_BODY_LINE, out)
        self.assert_no_tool_call()
        self.assertFalse((folder / 'mr.md').exists())

    def test_with_the_mr_port_on_its_core_default_put_prints_the_title_and_body_and_calls_nothing(self):
        """AC-44: a github.com origin, no profile."""
        self.point_origin(ORIGINS['gh'])
        self.assert_printed_and_unchanged(self.unit())

    def test_with_no_origin_put_prints_the_title_and_body_and_calls_nothing(self):
        """AC-44: the port names an adapter, the repository has no origin."""
        self.set_port('gh')
        self.assert_printed_and_unchanged(self.unit())


class UnknownAdapterTest(PutSetup, MrCase):
    def test_an_mr_port_value_that_is_no_adapter_is_one_error_naming_the_known_ones(self):
        """AC-45: `put`, `ready` and `show` all check the value before any call."""
        self.use('carrier-pigeon', origin=ORIGINS['gh'])
        folder = self.unit(link=LINKS['gh'])
        for action in ('put', 'ready', 'show'):
            with self.subTest(action=action):
                result = self.run_mr(action, folder)
                assert_cli_error(self, result, 'carrier-pigeon')
                self.assertRegex(result[2], r'\bglab\b')
                self.assertRegex(result[2], r'\bgh\b')
                self.assertEqual(result[1], '')
        self.assert_no_tool_call()


class AdhocPutTest(PutSetup, AdhocCase):
    ADAPTER = 'gh'

    def test_put_for_an_adhoc_ticket_reads_and_writes_the_sibling_files(self):
        """AC-42 and the Amended line: `<stem>.mr-body.md` in, `<stem>.mr.md` out, no `mr.md` in the adhoc folder."""
        write_text(self.body_file(), MR_BODY_FILE)
        code, out, err = self.run_mr('put', self.ticket)
        self.assertEqual(code, 0, (out, err))
        creates = self.calls('create')
        self.assertTrue(creates, self.fake.records)
        self.assertIn(MR_TITLE, creates[0].text)
        self.assertIn(MR_BODY_LINE, creates[0].text)
        sibling = self.ticket.with_name(self.ticket.stem + '.mr.md')
        self.assertEqual(self.mr_md_lines(sibling), [f'MR: {self.link}'])
        self.assertFalse((self.ticket.parent / 'mr.md').exists())


class GateLineTest(MrCase):
    """AC-46 in a temporary git repository: c1 (base), c2 (the tip of branch `feat/gate-demo`), c3 on main."""

    def setUp(self):
        super().setUp()
        self.c1 = self.repo.git('rev-parse', 'HEAD').strip()
        self.repo.write('src/two.txt', 'two\n')
        self.c2 = self.repo.commit(['src/two.txt'], 'feat: two', DAY)
        self.repo.git('branch', 'feat/gate-demo')
        self.repo.write('src/three.txt', 'three\n')
        self.repo.commit(['src/three.txt'], 'feat: three', DAY)
        self.folder = self.repo.root / '.anomaly' / UNIT
        write_text(self.folder / 'stories.md', '# A unit\n')

    def run_gate(self, action, ref):
        return run_cli('mr', action, str(self.folder), ref, '--repo', str(self.repo.root), '--home', str(self.home))

    def test_reviewed_and_verified_write_the_full_id_of_a_short_ref_and_of_a_branch_name(self):
        """AC-46."""
        for action, ref in (('reviewed', self.c1[:7]), ('verified', 'feat/gate-demo')):
            code, out, err = self.run_gate(action, ref)
            self.assertEqual(code, 0, (action, out, err))
        lines = [line.strip() for line in (self.folder / 'mr.md').read_text(encoding='utf-8').splitlines()]
        self.assertIn(f'Reviewed: {self.c1}', lines)
        self.assertIn(f'Verified: {self.c2}', lines)

    def test_a_ref_that_names_no_commit_is_an_error_and_writes_nothing(self):
        """AC-46."""
        for action in ('reviewed', 'verified'):
            with self.subTest(action=action):
                assert_cli_error(self, self.run_gate(action, 'no-such-ref'), 'no-such-ref')
                self.assertFalse((self.folder / 'mr.md').exists())


if __name__ == '__main__':
    unittest.main()
