"""The addenda owner (`anomaly_loop.addenda`): where a user's addenda file lives, the stamp of the
text it adds to, the tagged line and the cap. The routing and the `calibrate fix --addendum` command
are in test_calibrate.py.

Signatures this file pins:
  addendum_path(home, name, agent=False) -> Path
  stamp(target) -> str                       target: a skill folder or one agent file
  read_lines(path) -> list[str]              the lines of the file; [] when it is missing
  append_line(path, line, signature, stamp)  -> str, the tagged line it wrote; RecordError past the cap
"""
import tempfile
import unittest
from pathlib import Path

from anomaly_loop import addenda, constants
from anomaly_loop.files import RecordError
from tests.fixtures import write_text


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


if __name__ == '__main__':
    unittest.main()
