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
        with files.file_lock(self.lock, 0, 600) as got:
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

    def test_a_lock_that_another_run_took_over_meanwhile_is_not_removed(self):
        with files.file_lock(self.lock, 0.2, 600) as got:
            self.assertTrue(got)
            self.lock.write_text('another run', encoding='utf-8')
        self.assertEqual(self.lock.read_text(encoding='utf-8'), 'another run')

    def test_a_permission_error_with_a_lock_file_in_place_is_polled_again(self):
        import os
        from unittest import mock
        self.lock.write_text('other', encoding='utf-8')
        real_open = os.open
        calls = []

        def open_once_denied(*args, **kwargs):
            calls.append(args[0])
            if len(calls) == 1:
                raise PermissionError('lock is being deleted')
            self.lock.unlink()
            return real_open(*args, **kwargs)

        with mock.patch.object(files.os, 'open', side_effect=open_once_denied):
            with files.file_lock(self.lock, 2, 600) as got:
                self.assertTrue(got)
        self.assertEqual(len(calls), 2)

    def test_a_permission_error_with_no_lock_file_is_raised_at_once(self):
        from unittest import mock
        with mock.patch.object(files.os, 'open', side_effect=PermissionError('read-only folder')):
            with self.assertRaises(PermissionError):
                with files.file_lock(self.lock, 5, 600):
                    self.fail('the block must not run')

    def test_a_permission_error_with_no_lock_file_that_clears_on_the_retry_yields_true(self):
        import os
        from unittest import mock
        real_open = os.open
        calls = []

        def open_once_denied(*args, **kwargs):
            calls.append(args[0])
            if len(calls) == 1:
                raise PermissionError('lock was being deleted')
            return real_open(*args, **kwargs)

        with mock.patch.object(files.os, 'open', side_effect=open_once_denied):
            with files.file_lock(self.lock, 0.2, 600) as got:
                self.assertTrue(got)
        self.assertEqual(len(calls), 2)

    def test_a_permission_error_with_no_lock_file_is_retried_again_after_a_held_lock_was_met(self):
        import os
        from unittest import mock
        real_open = os.open
        calls = []

        def open_denied_three_times(*args, **kwargs):
            calls.append(args[0])
            if len(calls) == 2:
                self.lock.write_text('other', encoding='utf-8')
            if len(calls) == 3:
                self.lock.unlink()
            if len(calls) <= 3:
                raise PermissionError('lock was being deleted')
            return real_open(*args, **kwargs)

        with mock.patch.object(files.os, 'open', side_effect=open_denied_three_times):
            with files.file_lock(self.lock, 2, 600) as got:
                self.assertTrue(got)
        self.assertEqual(len(calls), 4)

    def test_only_the_first_stale_lock_is_taken_over_at_once_and_the_wait_still_ends(self):
        import time
        from unittest import mock
        real_time, calls = time.time, []

        def always_a_new_stale_lock(*args, **kwargs):
            calls.append(args[0])
            if len(calls) > 1000:
                raise AssertionError('the wait does not end')
            self.lock.write_text('another run', encoding='utf-8')
            raise FileExistsError(args[0])

        with mock.patch.object(files.os, 'open', side_effect=always_a_new_stale_lock):
            with mock.patch.object(files.time, 'time', side_effect=lambda: real_time() + 1000):
                with files.file_lock(self.lock, 0.2, 600) as got:
                    self.assertFalse(got)
        self.assertLess(len(calls), 20)

    def test_a_failing_token_write_leaves_no_lock_file_and_raises(self):
        from unittest import mock
        with mock.patch.object(files.os, 'write', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                with files.file_lock(self.lock, 0.2, 600):
                    self.fail('the block must not run')
        self.assertFalse(self.lock.exists())

    def test_a_lock_that_cannot_be_removed_at_the_end_is_left_and_the_block_exits_cleanly(self):
        from unittest import mock
        with mock.patch.object(Path, 'unlink', side_effect=PermissionError('file in use')):
            with files.file_lock(self.lock, 0.2, 600) as got:
                self.assertTrue(got)
        self.assertTrue(self.lock.exists())


if __name__ == '__main__':
    unittest.main()
