"""Offline tests for the `terms-grep` command (AC-20).

The command is driven through the CLI entry (`run_cli`) with a `file://` URL on a temporary file,
so no test reaches the network.
"""
import tempfile
import unittest
import urllib.parse
import urllib.request
from pathlib import Path
from unittest import mock

from anomaly_loop import pkg_facts
from tests.fixtures import run_cli

DEFAULT_CONTEXT = 300


class TermsGrepTest(unittest.TestCase):
    def page(self, body, name='terms.html'):
        """A temporary HTML page holding `body`; returns its file:// URL."""
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        path = Path(folder.name) / name
        path.write_text(f'<html><body><p>{body}</p></body></html>', encoding='utf-8', newline='\n')
        return path.as_uri()

    def hit_lines(self, out):
        """The printed context lines of the hits (the lines that start with the ellipsis marker)."""
        return [line for line in out.splitlines() if line.lstrip().startswith('…')]

    def test_a_match_prints_context_characters_each_side_default_300(self):
        url = self.page('A' * 500 + 'needle' + 'B' * 500)
        code, out, _ = run_cli('terms-grep', '--terms', 'needle', url)
        self.assertEqual(code, 0)
        (line,) = self.hit_lines(out)
        self.assertIn('A' * DEFAULT_CONTEXT + 'needle', line)
        self.assertNotIn('A' * (DEFAULT_CONTEXT + 1), line)
        self.assertIn('needle' + 'B' * (DEFAULT_CONTEXT - len('needle')), line)
        self.assertNotIn('B' * (DEFAULT_CONTEXT + 1), line)

    def test_context_sets_the_characters_each_side(self):
        url = self.page('A' * 500 + 'needle' + 'B' * 500)
        code, out, _ = run_cli('terms-grep', '--terms', 'needle', '--context', '20', url)
        self.assertEqual(code, 0)
        (line,) = self.hit_lines(out)
        self.assertIn('A' * 20 + 'needle', line)
        self.assertNotIn('A' * 21, line)
        self.assertNotIn('B' * 21, line)

    def test_word_matches_whole_words_only(self):
        url = self.page('foo food foobar')
        _, plain, _ = run_cli('terms-grep', '--terms', 'foo', url)
        _, whole, _ = run_cli('terms-grep', '--terms', 'foo', '--word', url)
        self.assertIn("'foo': 3 hit(s)", plain)
        self.assertIn("'foo': 1 hit(s)", whole)

    def test_an_unreadable_url_prints_fetch_failed_and_exits_1(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        missing = (Path(folder.name) / 'nowhere.html').as_uri()
        code, out, _ = run_cli('terms-grep', '--terms', 'needle', missing)
        self.assertEqual(code, 1)
        self.assertIn('FETCH FAILED', out)

    def assert_one_anomaly_line(self, result):
        """Exit 2, nothing on stdout, one `anomaly:` line on stderr."""
        code, out, err = result
        self.assertEqual((code, out), (2, ''))
        self.assertTrue(err.startswith('anomaly: '), err)
        self.assertEqual(len(err.splitlines()), 1, err)

    def test_terms_without_a_word_is_one_anomaly_line(self):
        self.assert_one_anomaly_line(run_cli('terms-grep', '--terms', ' , ', self.page('needle')))

    def test_a_url_of_another_scheme_is_refused_before_any_fetch(self):
        # data: is one urllib reads with no network, so the red run needs none either
        result = run_cli('terms-grep', '--terms', 'needle', self.page('needle'), 'data:text/html,needle')
        self.assert_one_anomaly_line(result)
        self.assertIn('data:text/html,needle', result[2])

    def test_a_pdf_page_prints_fetch_failed_and_exits_1(self):
        code, out, _ = run_cli('terms-grep', '--terms', 'needle', self.page('needle', name='terms.pdf'))
        self.assertEqual(code, 1)
        self.assertIn('FETCH FAILED', out)

    def test_a_page_at_or_over_the_cap_prints_fetch_failed(self):
        url = self.page('needle')
        size = Path(urllib.request.url2pathname(urllib.parse.urlsplit(url).path)).stat().st_size
        for cap, expected_code in ((size - 1, 1), (size, 1), (size + 1, 0)):
            with self.subTest(cap=cap), mock.patch.object(pkg_facts, 'MAX_RESPONSE_BYTES', cap):
                code, out, _ = run_cli('terms-grep', '--terms', 'needle', url)
                self.assertEqual(code, expected_code)
                self.assertEqual('FETCH FAILED' in out, expected_code == 1)

    def test_a_control_character_in_a_hit_prints_as_a_question_mark(self):
        code, out, _ = run_cli('terms-grep', '--terms', 'needle', self.page('needle\x1bend'))
        self.assertEqual(code, 0)
        (line,) = self.hit_lines(out)
        self.assertIn('needle?end', line)
        self.assertNotIn('\x1b', out)


if __name__ == '__main__':
    unittest.main()
