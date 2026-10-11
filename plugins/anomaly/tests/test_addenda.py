"""The addenda owner (`anomaly_loop.addenda`): where a user's addenda file lives, the stamp of the
text it adds to, the tagged line and the cap. The routing and the `calibrate fix --addendum` command
are in test_calibrate.py.

Signatures this file pins:
  addendum_path(home, name, agent=False) -> Path
  stamp(target) -> str                       target: a skill folder or one agent file
  read_lines(path) -> list[str]              the lines of the file; [] when it is missing
  append_line(path, line, signature, stamp)  -> str, the tagged line it wrote; RecordError past the cap
  log_line(anomaly, line) -> None            appends `- <line>` under the anomaly's `## Addenda log`
  print_addenda(home, skill) -> None         prints to stdout the addenda of `skill` and of the agents it dispatches
  constants.SKILL_AGENTS                     dict: skill name -> the agent names it dispatches (D-39)
"""
import contextlib
import io
import re
import tempfile
import unittest
from pathlib import Path

from anomaly_loop import addenda, constants, records
from anomaly_loop.files import RecordError
from tests.fixtures import PLUGIN, write_text


class AddendaCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.home = self.root / 'home'

    def skill(self, name='observe', root=None, **files):
        """A skill folder under `root` (default: self.root / 'plugin') holding these files (relative path -> text)."""
        folder = (root or self.root / 'plugin') / 'skills' / name
        for relative, text in (files or {'SKILL.md': '# observe\n'}).items():
            write_text(folder / relative, text)
        return folder


class PathTest(AddendaCase):
    def test_a_skill_addendum_is_one_file_under_home_and_an_agent_addendum_is_under_agents(self):
        self.assertEqual(constants.ADDENDA_DIR, 'addenda')
        self.assertEqual(addenda.addendum_path(self.home, 'observe'), self.home / 'addenda' / 'observe.md')
        self.assertEqual(addenda.addendum_path(self.home, 'facts', agent=True),
                         self.home / 'addenda' / 'agents' / 'facts.md')


class StampTest(AddendaCase):
    def test_a_stamp_is_8_hex_characters_and_the_same_for_the_same_text(self):
        folder = self.skill(**{'SKILL.md': '# observe\n', 'references/steps.md': 'one\n'})
        self.assertRegex(addenda.stamp(folder), r'[0-9a-f]{8}')
        self.assertEqual(addenda.stamp(folder), addenda.stamp(folder))

    def test_a_stamp_depends_on_relative_paths_so_a_copy_elsewhere_has_the_same_stamp(self):
        files = {'SKILL.md': '# observe\n', 'references/steps.md': 'one\n'}
        self.assertEqual(addenda.stamp(self.skill(**files)),
                         addenda.stamp(self.skill(root=self.root / 'copy', **files)))

    def test_a_stamp_changes_when_one_byte_of_a_file_changes(self):
        folder = self.skill(**{'SKILL.md': '# observe\n', 'references/steps.md': 'one\n'})
        before = addenda.stamp(folder)
        write_text(folder / 'references' / 'steps.md', 'One\n')
        self.assertNotEqual(addenda.stamp(folder), before)

    def test_a_stamp_changes_when_a_file_is_added_or_renamed(self):
        folder = self.skill(**{'SKILL.md': '# observe\n', 'steps.md': 'one\n'})
        before = addenda.stamp(folder)
        write_text(folder / 'more.md', 'two\n')
        added = addenda.stamp(folder)
        self.assertNotEqual(added, before)
        (folder / 'more.md').rename(folder / 'other.md')
        self.assertNotEqual(addenda.stamp(folder), added)

    def test_the_stamp_of_an_agent_file_changes_with_its_bytes(self):
        agent = self.root / 'plugin' / 'agents' / 'facts.md'
        write_text(agent, 'You answer questions.\n')
        before = addenda.stamp(agent)
        self.assertRegex(before, r'[0-9a-f]{8}')
        write_text(agent, 'You answer question.\n')
        self.assertNotEqual(addenda.stamp(agent), before)


class AppendTest(AddendaCase):
    def setUp(self):
        super().setUp()
        self.path = addenda.addendum_path(self.home, 'observe')

    def test_a_line_is_written_with_its_experiment_and_stamp_and_read_back(self):
        written = addenda.append_line(self.path, 'Ask which repo before logging.', 'slow-check', '0a1b2c3d')
        self.assertEqual(written, 'Ask which repo before logging. [exp: slow-check · 0a1b2c3d]')
        self.assertEqual(self.path.read_text(encoding='utf-8'), written + '\n')
        addenda.append_line(self.path, 'Name the skill in the note.', 'late-note', '0a1b2c3d')
        self.assertEqual(addenda.read_lines(self.path), [
            'Ask which repo before logging. [exp: slow-check · 0a1b2c3d]',
            'Name the skill in the note. [exp: late-note · 0a1b2c3d]'])

    def test_a_missing_file_has_no_lines_and_the_first_line_creates_its_folders(self):
        self.assertEqual(addenda.read_lines(self.path), [])
        agent = addenda.addendum_path(self.home, 'facts', agent=True)
        addenda.append_line(agent, 'Cite the line.', 'vague-answer', '0a1b2c3d')
        self.assertEqual(addenda.read_lines(agent), ['Cite the line. [exp: vague-answer · 0a1b2c3d]'])

    def test_a_second_line_of_the_same_experiment_is_refused_and_another_experiment_is_accepted(self):
        addenda.append_line(self.path, 'Ask which repo before logging.', 'slow-check', '0a1b2c3d')
        before = self.path.read_bytes()
        with self.assertRaises(RecordError) as refused:
            addenda.append_line(self.path, 'Name the skill in the note.', 'slow-check', '0a1b2c3d')
        self.assertIn('slow-check', str(refused.exception))
        self.assertIn('observe.md', str(refused.exception))
        self.assertRegex(str(refused.exception), r'(?i)remove')   # how to clear the old line
        self.assertEqual(self.path.read_bytes(), before)
        addenda.append_line(self.path, 'Name the skill in the note.', 'slow', '0a1b2c3d')   # a prefix is another experiment
        self.assertEqual(len(addenda.read_lines(self.path)), 2)

    def test_a_sixth_line_is_refused_naming_the_file_and_the_cap_and_the_file_is_unchanged(self):
        self.assertEqual(constants.ADDENDA_MAX_LINES, 5)
        for number in range(constants.ADDENDA_MAX_LINES):
            addenda.append_line(self.path, f'Rule number {number}.', f'sig-{number}', '0a1b2c3d')
        before = self.path.read_bytes()
        with self.assertRaises(RecordError) as refused:
            addenda.append_line(self.path, 'One rule too many.', 'sig-5', '0a1b2c3d')
        self.assertIn('observe.md', str(refused.exception))
        self.assertRegex(str(refused.exception), rf'\b{constants.ADDENDA_MAX_LINES}\b')
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(len(addenda.read_lines(self.path)), constants.ADDENDA_MAX_LINES)


class LogTest(unittest.TestCase):
    def test_a_log_line_goes_last_in_the_existing_addenda_log_whatever_the_heading_case_and_no_other_section(self):
        anomaly = records.Anomaly(signature='slow-check', sections=[
            ('addenda log', '- dropped 2026-10-01 · first'), ('Merged', 'Merged into other on 2026-10-02.')])
        addenda.log_line(anomaly, 'dropped 2026-10-04 · second')
        self.assertEqual(anomaly.sections, [
            ('addenda log', '- dropped 2026-10-01 · first\n- dropped 2026-10-04 · second'),
            ('Merged', 'Merged into other on 2026-10-02.')])


class PrintTest(AddendaCase):
    """AC-11, AC-14, AC-15, D-15, D-39: what `print_addenda` writes; where each skill's call places it is in the
    tests of those commands."""
    HEADER = 'Extra rules for {skill}. They add or narrow; the core rules and invariants win on a clash.'
    HAND_OVER = 'add these lines to the brief of `anomaly:{agent}`'

    def printed(self, skill):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            addenda.print_addenda(self.home, skill)
        return out.getvalue()

    def add(self, name, rule, agent=False):
        addenda.append_line(addenda.addendum_path(self.home, name, agent=agent), rule, f'sig-{name}', '0a1b2c3d')

    def test_a_skill_addendum_is_printed_under_the_core_wins_header(self):
        self.add('observe', 'Ask which repo before logging.')
        lines = self.printed('observe').splitlines()
        header = next(at for at, line in enumerate(lines) if self.HEADER.format(skill='observe') in line)
        rule = next(at for at, line in enumerate(lines) if 'Ask which repo before logging.' in line)
        self.assertLess(header, rule)

    def test_each_agent_the_skill_dispatches_is_printed_under_its_hand_over_line_and_no_other_agent(self):
        self.add('assess', 'Name the source first.')
        self.add('digest', 'Keep the digest under 100 words.', agent=True)
        self.add('facts', 'Cite the line.', agent=True)   # `assess` does not dispatch facts (D-39)
        lines = self.printed('assess').splitlines()
        hand_over = next(at for at, line in enumerate(lines) if self.HAND_OVER.format(agent='digest') in line)
        rule = next(at for at, line in enumerate(lines) if 'Keep the digest under 100 words.' in line)
        self.assertLess(hand_over, rule)
        self.assertFalse(any('Cite the line.' in line or 'anomaly:facts' in line for line in lines), lines)

    def test_each_skill_in_the_table_names_each_of_its_agents_in_its_own_files(self):
        """D-39: the table follows the skills; a skill that stops dispatching an agent fails here."""
        for skill, agents in constants.SKILL_AGENTS.items():
            texts = [path.read_text(encoding='utf-8') for path in (PLUGIN / 'skills' / skill).rglob('*')
                     if path.is_file()]
            for agent in agents:
                with self.subTest(skill=skill, agent=agent):
                    self.assertTrue(any(re.search(rf'anomaly:{agent}\b', text) for text in texts))

    def test_a_line_without_the_experiment_tag_is_not_printed_and_one_warning_names_the_file(self):
        self.add('observe', 'Ask which repo before logging.')
        path = addenda.addendum_path(self.home, 'observe')
        write_text(path, path.read_text(encoding='utf-8') + 'A rule with no tag.\n')
        out = self.printed('observe')
        self.assertIn('Ask which repo before logging.', out)
        self.assertNotIn('A rule with no tag.', out)
        warnings = [line for line in out.splitlines() if line.startswith('warning:')]
        self.assertEqual(len(warnings), 1, out)
        self.assertIn('observe.md', warnings[0])

    def test_a_file_that_cannot_be_read_is_one_warning_line_and_not_a_stop(self):
        for case, make in (('not-utf8', lambda path: path.write_bytes(b'\xe9\n')), ('folder', Path.mkdir)):
            with self.subTest(case):
                self.home = self.root / case
                path = addenda.addendum_path(self.home, 'observe')
                path.parent.mkdir(parents=True)
                make(path)
                lines = self.printed('observe').splitlines()
                self.assertEqual(len(lines), 1, lines)
                self.assertRegex(lines[0], r'^warning: .*observe\.md: not read \(.+\)$')

    def test_with_no_addenda_file_nothing_is_printed(self):
        self.assertEqual(self.printed('review'), '')

    def test_a_skill_that_takes_no_addenda_prints_none_even_with_a_file(self):
        """D-25 Amended: `worklog start <key> measure` must not print a measure.md."""
        self.add('measure', 'A rule for measure.')
        self.assertEqual(self.printed('measure'), '')


if __name__ == '__main__':
    unittest.main()
