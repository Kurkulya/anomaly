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


class LockTest(unittest.TestCase):
    """files.file_lock(path, wait, stale): a context manager that yields True when it holds the lock file
    (made with O_CREAT|O_EXCL) and False when it gave up after `wait` seconds; it takes over a lock whose
    modification time is more than `stale` seconds old and removes its own lock when the block ends."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.lock = Path(tmp.name) / 'metrics.lock'

    def test_a_held_lock_that_is_released_during_the_wait_is_taken(self):
        import threading
        self.lock.write_text('other', encoding='utf-8')
        release = threading.Timer(0.1, self.lock.unlink)
        self.addCleanup(release.cancel)
        release.start()
        with files.file_lock(self.lock, 2, 600) as got:
            self.assertTrue(got)
            self.assertTrue(self.lock.exists())

    def test_a_lock_still_held_when_the_wait_ends_gives_a_skip_and_stays_in_place(self):
        self.lock.write_text('other', encoding='utf-8')
        with files.file_lock(self.lock, 0.2, 600) as got:
            self.assertFalse(got)
        self.assertEqual(self.lock.read_text(encoding='utf-8'), 'other')

    def test_a_lock_older_than_the_stale_age_is_taken_over(self):
        import os
        import time
        self.lock.write_text('dead run', encoding='utf-8')
        old = time.time() - 1000
        os.utime(self.lock, (old, old))
        with files.file_lock(self.lock, 0.2, 600) as got:
            self.assertTrue(got)

    def test_the_lock_file_is_gone_after_the_block_ends(self):
        with files.file_lock(self.lock, 0.2, 600) as got:
            self.assertTrue(got)
            self.assertTrue(self.lock.exists())
        self.assertFalse(self.lock.exists())

    def test_the_lock_file_is_gone_after_the_block_raises(self):
        with self.assertRaises(RuntimeError):
            with files.file_lock(self.lock, 0.2, 600) as got:
                self.assertTrue(got)
                raise RuntimeError('scan failed')
        self.assertFalse(self.lock.exists())


if __name__ == '__main__':
    unittest.main()
