"""The exact-text reader and writer of files.py: no byte order mark removal on request, no line
ending translation, whole-file replacement."""
import tempfile
import unittest
from pathlib import Path

from anomaly_loop import files

BOM = chr(0xFEFF)


class ExactTextTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)

    def test_write_text_keeps_every_byte_and_makes_the_parent_folder(self):
        path = self.root / 'a' / 'b.txt'
        files.write_text(path, 'one\r\ntwo\nthree' + BOM)
        self.assertEqual(path.read_bytes(), ('one\r\ntwo\nthree' + BOM).encode('utf-8'))

    def test_write_text_replaces_the_file_and_leaves_no_temporary_file(self):
        path = self.root / 'b.txt'
        files.write_text(path, 'old')
        files.write_text(path, 'new')
        self.assertEqual([p.name for p in self.root.iterdir()], ['b.txt'])
        self.assertEqual(path.read_text(encoding='utf-8'), 'new')

    def test_write_lines_still_ends_each_line_with_lf(self):
        path = self.root / 'c.txt'
        files.write_lines(path, ['a', 'b'])
        self.assertEqual(path.read_bytes(), b'a\nb\n')

    def test_read_input_drops_a_byte_order_mark_unless_asked_to_keep_it(self):
        path = self.root / 'd.txt'
        path.write_bytes(b'\xef\xbb\xbfone\r\ntwo')
        self.assertEqual(files.read_input(path), 'one\r\ntwo')
        self.assertEqual(files.read_input(path, keep_bom=True), BOM + 'one\r\ntwo')

    def test_read_input_still_refuses_text_that_is_not_utf8(self):
        path = self.root / 'e.txt'
        path.write_bytes(b'\xff\xfe\x00')
        with self.assertRaises(files.RecordError):
            files.read_input(path, keep_bom=True)


if __name__ == '__main__':
    unittest.main()
