"""`worklog start` and `worklog add` through the CLI, in-process: one JSON line `{feature, stage, session, date,
ended}` (plus `started`, `doc_bytes`, `ticket`, `mode` when they apply) appended to `<home>/work-units.jsonl`;
feature, stage and session are single tokens; when home is inside a git repository only that path is committed.
`worklog start` keeps a start record in the data folder, never in home, that the next `add` for the same key and
stage reads and consumes."""
import contextlib
import io
import json
import os
import re
import tempfile
import unittest
from pathlib import Path

from anomaly_loop import cli
from tests.fixtures import (NOW, SID, GitFixture, assert_cli_error, metrics_row, run_cli, write_metrics_rows,
                            write_text)

TODAY = NOW.date().isoformat()
LATER = NOW.replace(day=9)
EARLIER = NOW.replace(hour=9, minute=30)
NO_START = 'warning: no start time'
ENDED = '2026-10-04 12:00'


class WorklogCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        self.home = self.root / 'home'
        self.data = self.root / 'data'

    @property
    def path(self):
        return self.home / 'work-units.jsonl'

    def add(self, feature='workflow-build', stage='build', session=SID, now=NOW, extra=(), data=True):
        where = ('--data', str(self.data)) if data else ()
        return run_cli('worklog', 'add', '--feature', feature, '--stage', stage, '--session', session,
                       '--home', str(self.home), *where, *extra, now=now)

    def add_ok(self, *args, warning=True, **kwargs):
        """The add must succeed, and its stdout holds the no-start warning exactly when `warning` is true
        (the default: no start record was made); stderr stays empty, like the warnings of `ticket`."""
        code, out, err = self.add(*args, **kwargs)
        self.assertEqual((code, err), (0, ''), out)
        lines = out.splitlines()
        self.assertEqual(lines.count(NO_START), 1 if warning else 0, out)
        return lines

    def start(self, key='workflow-build', stage='build', now=EARLIER, extra=()):
        return run_cli('worklog', 'start', key, stage, '--home', str(self.home), '--data', str(self.data),
                       *extra, now=now)

    def start_ok(self, *args, **kwargs):
        code, out, err = self.start(*args, **kwargs)
        self.assertEqual((code, err), (0, ''), out)
        return out.splitlines()

    def lines(self):
        return [json.loads(line) for line in self.path.read_bytes().decode('utf-8').splitlines()]


class RegistryTest(WorklogCase):
    def test_worklog_is_registered_once_with_the_add_report_and_start_actions(self):
        self.assertEqual(cli.COMMANDS.count('worklog'), 1)
        out = io.StringIO()
        with contextlib.redirect_stdout(out), self.assertRaises(SystemExit):
            cli.main(['worklog', '--help'], environ={})
        self.assertEqual(sorted(re.findall(r'^ {4}([\w-]+)\s{2,}\S', out.getvalue(), re.M)),
                         ['add', 'report', 'start'])

    def test_a_missing_action_is_a_usage_error_on_one_line(self):
        assert_cli_error(self, run_cli('worklog', '--home', str(self.home)))

    def test_every_option_is_required(self):
        base = ['worklog', 'add', '--feature', 'a', '--stage', 'build', '--session', SID]
        for drop in ('--feature', '--stage', '--session'):
            with self.subTest(missing=drop):
                argv = list(base)
                at = argv.index(drop)
                del argv[at:at + 2]
                assert_cli_error(self, run_cli(*argv, '--home', str(self.home)), drop.lstrip('-'))
        self.assertFalse(self.home.exists())


class AddTest(WorklogCase):
    def test_one_line_with_feature_stage_session_the_clocks_date_and_the_end_time(self):
        out = self.add_ok('workflow-build', 'build')
        self.assertEqual(self.lines(), [dict(feature='workflow-build', stage='build', session=SID, date=TODAY,
                                             ended=ENDED)])
        self.assertEqual(out[0], 'work unit: workflow-build build')

    def test_the_date_is_the_injected_clocks_day(self):
        self.add_ok(now=LATER)
        self.assertEqual(self.lines()[0]['date'], LATER.date().isoformat())

    def test_every_run_appends_a_line_and_earlier_lines_stay_as_they_were(self):
        self.add_ok('workflow-build', 'build')
        first = self.path.read_bytes()
        self.add_ok('workflow-build', 'review')
        self.add_ok('2026-10-05-a-small-task', 'build')
        self.assertTrue(self.path.read_bytes().startswith(first))
        self.assertEqual([(row['feature'], row['stage']) for row in self.lines()],
                         [('workflow-build', 'build'), ('workflow-build', 'review'),
                          ('2026-10-05-a-small-task', 'build')])

    def test_the_file_uses_line_feeds_and_each_line_is_one_compact_object(self):
        self.add_ok()
        data = self.path.read_bytes()
        self.assertTrue(data.endswith(b'\n'))
        self.assertNotIn(b'\r', data)
        self.assertEqual(data.decode('utf-8').splitlines(),
                         [json.dumps(self.lines()[0], separators=(',', ':'))])

    def test_a_session_id_with_a_colon_is_a_single_token(self):
        self.add_ok('2026-10-05-fix-the-login', 'build', 'local_session:7')
        self.assertEqual(len(self.lines()), 1)

    def test_it_needs_no_data_folder_and_no_profile_and_then_has_no_start_to_read(self):
        self.add_ok(data=False)
        self.assertEqual(sorted(p.name for p in self.home.iterdir()), ['work-units.jsonl'])
        self.assertNotIn('started', self.lines()[0])

    def test_a_data_folder_inside_home_is_refused_and_no_line_is_written(self):
        """The throwaway start record must stay out of home, so `add` refuses such a data folder too
        (its env var, CLAUDE_PLUGIN_DATA, is read the same way)."""
        assert_cli_error(self, run_cli('worklog', 'add', '--feature', 'a', '--stage', 'build', '--session', SID,
                                       '--home', str(self.home), '--data', str(self.home / 'data')), 'home')
        environ = {'CLAUDE_PLUGIN_DATA': str(self.home / 'data')}
        assert_cli_error(self, run_cli('worklog', 'add', '--feature', 'a', '--stage', 'build', '--session', SID,
                                       '--home', str(self.home), environ=environ), 'home')
        self.assertFalse(self.home.exists())

    def test_home_comes_from_the_environment_when_not_given(self):
        environ = {'CLAUDE_PLUGIN_OPTION_HOME': str(self.home)}
        code, out, err = run_cli('worklog', 'add', '--feature', 'a', '--stage', 'build', '--session', SID,
                                 environ=environ)
        self.assertEqual((code, err), (0, ''), out)
        self.assertIn(NO_START, out.splitlines())
        self.assertTrue(self.path.is_file())

    def test_a_value_that_is_not_one_token_is_refused_by_name_and_nothing_is_written(self):
        bad = ('two words', 'line\nbreak', 'a · b', 'x' * 81, '', 'a/b', '.hidden')
        for key in ('feature', 'stage', 'session'):
            for value in bad:
                with self.subTest(key=key, value=value):
                    assert_cli_error(self, self.add(**{key: value}), key)
        self.assertFalse(self.home.exists())


class StartTest(WorklogCase):
    """AC-92: `worklog start <key> <stage>` stamps the CLI clock; `add` for the same key and stage reads it."""

    @property
    def records(self):
        return sorted(self.data.rglob('*'))

    def test_start_prints_one_line_and_writes_only_in_the_data_folder(self):
        out = self.start_ok('workflow-build', 'build')
        self.assertEqual(out, ['start: workflow-build build 2026-10-04 09:30'])
        self.assertTrue(any(path.is_file() for path in self.records))
        self.assertFalse(self.home.exists())

    def test_add_after_start_has_started_and_ended_and_no_warning(self):
        self.start_ok('workflow-build', 'build', now=EARLIER)
        self.add_ok('workflow-build', 'build', warning=False)
        row = self.lines()[0]
        self.assertEqual((row['started'], row['ended']), ('2026-10-04 09:30', ENDED))
        self.assertEqual(list(row), ['feature', 'stage', 'session', 'date', 'started', 'ended'])

    def test_a_light_path_key_without_md_is_stamped_by_start_and_read_by_add(self):
        self.start_ok('2026-10-05-a-small-task', 'build', now=EARLIER)
        self.add_ok('2026-10-05-a-small-task', 'build', warning=False)
        row = self.lines()[0]
        self.assertEqual((row['feature'], row['started']), ('2026-10-05-a-small-task', '2026-10-04 09:30'))

    def test_a_start_for_another_stage_or_another_key_is_not_read(self):
        self.start_ok('workflow-build', 'review')
        self.start_ok('other-feature', 'build')
        self.add_ok('workflow-build', 'build')
        self.assertNotIn('started', self.lines()[0])

    def test_add_consumes_the_record_so_a_second_add_warns_and_the_others_survive(self):
        self.start_ok('workflow-build', 'build', now=EARLIER)
        self.start_ok('other-feature', 'build', now=EARLIER.replace(hour=10))
        self.add_ok('workflow-build', 'build', warning=False)
        self.add_ok('workflow-build', 'build')
        self.add_ok('other-feature', 'build', warning=False)
        rows = self.lines()
        self.assertEqual([row.get('started') for row in rows], ['2026-10-04 09:30', None, '2026-10-04 10:30'])

    def test_a_second_start_for_the_same_key_and_stage_replaces_the_first(self):
        self.start_ok(now=EARLIER)
        self.start_ok(now=EARLIER.replace(hour=11))
        self.add_ok(warning=False)
        self.assertEqual(self.lines()[0]['started'], '2026-10-04 11:30')
        self.add_ok()
        self.assertNotIn('started', self.lines()[1])

    def start_file(self):
        return self.data / 'worklog-starts.jsonl'

    def start_rows(self):
        return [json.loads(line) for line in self.start_file().read_bytes().decode('utf-8').splitlines()]

    def test_the_start_file_is_append_only_add_writes_a_consumed_marker_after_the_start(self):
        self.start_ok('workflow-build', 'build', now=EARLIER)
        before = self.start_file().read_bytes()
        self.add_ok('workflow-build', 'build', warning=False)
        self.assertTrue(self.start_file().read_bytes().startswith(before))
        self.assertEqual(self.start_rows(), [
            dict(feature='workflow-build', stage='build', started='2026-10-04 09:30'),
            dict(feature='workflow-build', stage='build', consumed=ENDED)])

    def test_the_consumed_marker_is_written_before_the_home_line_so_a_failed_home_write_never_duplicates(self):
        """A failed home write loses the start (the marker is already there); the retry writes the line
        without `started` and warns. The durable file never gets the line twice."""
        self.start_ok()
        self.home.mkdir()
        self.path.mkdir()   # a folder where the file goes: the home append fails
        code, out, err = self.add()
        self.assertEqual(code, 2, (out, err))
        self.assertEqual([('consumed' in row) for row in self.start_rows()], [False, True])
        self.path.rmdir()
        self.add_ok(warning=True)
        self.assertEqual(len(self.lines()), 1)
        self.assertNotIn('started', self.lines()[0])

    def test_a_failed_marker_write_writes_no_home_line_and_keeps_the_start(self):
        self.start_ok()
        os.chmod(self.start_file(), 0o444)
        self.addCleanup(os.chmod, self.start_file(), 0o644)
        if os.access(self.start_file(), os.W_OK):
            self.skipTest('this system lets the start file be written although it is read-only')
        code, out, err = self.add()
        self.assertEqual(code, 2, (out, err))
        self.assertFalse(self.path.exists())
        os.chmod(self.start_file(), 0o644)
        self.add_ok(warning=False)
        self.assertEqual(self.lines()[0]['started'], '2026-10-04 09:30')

    def test_a_line_in_the_start_file_that_is_not_json_is_kept(self):
        self.data.mkdir()
        self.start_file().write_bytes(b'not json\n')
        self.start_ok()
        self.add_ok(warning=False)
        self.assertTrue(self.start_file().read_bytes().startswith(b'not json\n'))

    def test_a_start_after_a_consumed_marker_is_read_by_the_next_add(self):
        self.start_ok(now=EARLIER)
        self.add_ok(warning=False)
        self.start_ok(now=EARLIER.replace(hour=11))
        self.add_ok(warning=False)
        self.assertEqual([row['started'] for row in self.lines()], ['2026-10-04 09:30', '2026-10-04 11:30'])

    def test_a_start_with_a_ticket_is_read_only_by_an_add_with_the_same_ticket(self):
        self.start_ok(extra=('--ticket', '07'))
        self.add_ok(warning=True)
        self.add_ok(extra=('--ticket', '08'), warning=True)
        self.assertFalse(any('started' in row for row in self.lines()))
        self.add_ok(extra=('--ticket', '07'), warning=False)
        self.assertEqual(self.lines()[-1]['started'], '2026-10-04 09:30')

    def test_a_start_without_a_ticket_is_read_only_by_an_add_without_one(self):
        self.start_ok()
        self.add_ok(extra=('--ticket', '07'), warning=True)
        self.add_ok(warning=False)
        self.assertEqual(self.lines()[-1]['started'], '2026-10-04 09:30')

    def test_parallel_tickets_of_one_feature_each_read_their_own_start(self):
        self.start_ok(now=EARLIER, extra=('--ticket', '07'))
        self.start_ok(now=EARLIER.replace(hour=10), extra=('--ticket', '08'))
        self.add_ok(extra=('--ticket', '08'), warning=False)
        self.add_ok(extra=('--ticket', '07'), warning=False)
        self.assertEqual([(row['ticket'], row['started']) for row in self.lines()],
                         [('08', '2026-10-04 10:30'), ('07', '2026-10-04 09:30')])
        self.assertEqual([row.get('ticket') for row in self.start_rows()], ['07', '08', '08', '07'])

    def test_a_ticket_on_start_is_checked_like_add_and_only_for_build_and_review(self):
        for value in ('7', '007', 'ab', '07\n08', '', '٠٧'):
            with self.subTest(value=value):
                assert_cli_error(self, self.start(extra=('--ticket', value)), 'ticket')
        assert_cli_error(self, self.start(stage='ship', extra=('--ticket', '07')), 'ticket', 'build', 'review')
        self.assertFalse(self.data.exists())

    def test_a_refused_add_keeps_the_start_record(self):
        self.start_ok()
        assert_cli_error(self, self.add(extra=('--docs', str(self.root / 'no-such-folder'))), 'docs')
        self.add_ok(warning=False)
        self.assertEqual(self.lines()[0]['started'], '2026-10-04 09:30')

    def test_the_model_passes_no_time(self):
        for flag in ('--started', '--ended'):
            with self.subTest(flag=flag):
                assert_cli_error(self, self.add(extra=(flag, '2026-10-04 08:00')), flag.lstrip('-'))
        assert_cli_error(self, run_cli('worklog', 'start', 'a', 'build', '--at', '08:00', '--home', str(self.home),
                                       '--data', str(self.data)), '--at')
        self.assertFalse(self.path.exists())

    def test_start_needs_a_data_folder_outside_home(self):
        assert_cli_error(self, run_cli('worklog', 'start', 'a', 'build', '--home', str(self.home)), 'data')
        assert_cli_error(self, run_cli('worklog', 'start', 'a', 'build', '--home', str(self.home),
                                       '--data', str(self.home / 'data')), 'home')
        self.assertFalse(self.home.exists())

    def test_start_needs_a_key_and_a_stage(self):
        assert_cli_error(self, run_cli('worklog', 'start', '--home', str(self.home), '--data', str(self.data)))
        assert_cli_error(self, run_cli('worklog', 'start', 'a', '--home', str(self.home), '--data', str(self.data)))

    def test_key_and_stage_are_single_tokens_like_add_requires(self):
        bad = ('two words', 'line\nbreak', 'a · b', 'x' * 81, '', 'a/b', '.hidden')
        for position, name in ((0, 'key'), (1, 'stage')):
            for value in bad:
                with self.subTest(name=name, value=value):
                    args = ['workflow-build', 'build']
                    args[position] = value
                    assert_cli_error(self, self.start(*args), name)
        self.assertFalse(self.data.exists())


class DocsTest(WorklogCase):
    """AC-91: `--docs <folder>` adds `doc_bytes`, summed in Python over every `.md` file below the folder."""

    def setUp(self):
        super().setUp()
        self.docs = self.root / 'docs'

    def put(self, name, data):
        path = self.docs / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def doc_bytes(self):
        self.add_ok(extra=('--docs', str(self.docs)))
        return self.lines()[-1]['doc_bytes']

    def test_the_total_covers_md_files_in_the_folder_and_every_sub_folder(self):
        self.put('spec.md', b'x' * 100)
        self.put('issues/01-a.md', b'y' * 20)
        self.put('issues/deeper/02-b.md', b'z' * 3)
        self.assertEqual(self.doc_bytes(), 123)

    def test_other_files_and_folders_named_like_md_are_not_counted(self):
        self.put('spec.md', b'x' * 10)
        self.put('notes.txt', b'y' * 500)
        self.put('seams.md.bak', b'y' * 500)
        self.put('data.json', b'y' * 500)
        (self.docs / 'folder.md').mkdir()
        self.assertEqual(self.doc_bytes(), 10)

    def test_a_symbolic_link_to_a_md_file_is_not_counted(self):
        target = self.root / 'outside.md'
        target.write_bytes(b'y' * 500)
        self.put('spec.md', b'x' * 10)
        try:
            os.symlink(target, self.docs / 'linked.md')
        except (OSError, NotImplementedError):
            self.skipTest('this system does not allow a symbolic link here')
        self.assertEqual(self.doc_bytes(), 10)

    def test_bytes_not_characters_and_line_endings_as_stored(self):
        self.put('a.md', 'é\r\n'.encode('utf-8'))
        self.assertEqual(self.doc_bytes(), 4)

    def test_an_empty_folder_counts_0(self):
        self.docs.mkdir()
        self.assertEqual(self.doc_bytes(), 0)

    def test_without_docs_the_line_has_no_doc_bytes(self):
        self.add_ok()
        self.assertNotIn('doc_bytes', self.lines()[0])

    def test_a_folder_that_does_not_exist_or_is_a_file_is_refused_and_nothing_is_written(self):
        self.put('a.md', b'x')
        for value in (self.root / 'missing', self.docs / 'a.md'):
            with self.subTest(value=value):
                assert_cli_error(self, self.add(extra=('--docs', str(value))), 'docs')
        self.assertFalse(self.home.exists())


class ReviewFieldsTest(WorklogCase):
    """AC-93: on stage review, `--ticket <NN>` and `--mode <mode>` (the modes of AC-45) go on the line."""

    def review(self, *extra, stage='review'):
        return self.add(stage=stage, extra=extra)

    def test_both_fields_go_on_the_line_after_ended(self):
        code, out, err = self.review('--ticket', '07', '--mode', 'delta')
        self.assertEqual((code, err), (0, ''), out)
        self.assertEqual(self.lines()[0], dict(feature='workflow-build', stage='review', session=SID, date=TODAY,
                                               ended=ENDED, ticket='07', mode='delta'))

    def test_each_field_is_optional_on_its_own(self):
        self.review('--ticket', '07')
        self.review('--mode', 'cumulative')
        self.review()
        rows = self.lines()
        self.assertEqual([(row.get('ticket'), row.get('mode')) for row in rows],
                         [('07', None), (None, 'cumulative'), (None, None)])

    def test_every_mode_of_ac_45_is_accepted(self):
        for mode in ('ticket', 'delta', 'cumulative', 'combined', 'rules'):
            with self.subTest(mode=mode):
                code, out, err = self.review('--mode', mode)
                self.assertEqual(code, 0, err)
        self.assertEqual([row['mode'] for row in self.lines()],
                         ['ticket', 'delta', 'cumulative', 'combined', 'rules'])

    def test_a_mode_outside_the_list_is_refused_and_nothing_is_written(self):
        for mode in ('full', 'Delta', '', 'delta\ncumulative'):
            with self.subTest(mode=mode):
                assert_cli_error(self, self.review('--mode', mode), 'mode')
        self.assertFalse(self.home.exists())

    def test_a_ticket_that_is_not_two_digits_is_refused_and_nothing_is_written(self):
        for value in ('7', '007', 'ab', '0x', '07\n08', '', '-1', '٠٧'):
            with self.subTest(value=value):
                assert_cli_error(self, self.review('--ticket', value), 'worklog: --ticket')   # the text start gives
        self.assertFalse(self.home.exists())

    def test_the_mode_is_for_review_only_and_the_ticket_for_build_and_review(self):
        assert_cli_error(self, self.review('--mode', 'delta', stage='build'), 'mode', 'review')
        assert_cli_error(self, self.review('--ticket', '07', stage='ship'), 'ticket', 'build', 'review')
        self.assertFalse(self.home.exists())
        code, out, err = self.review('--ticket', '07', stage='build')
        self.assertEqual((code, err), (0, ''), out)
        self.assertEqual(self.lines()[0]['ticket'], '07')

    def test_a_review_round_can_carry_a_start_and_docs_too(self):
        self.start_ok('workflow-build', 'review', now=EARLIER, extra=('--ticket', '03'))
        self.docs = self.root / 'docs'
        self.docs.mkdir()
        (self.docs / 'a.md').write_bytes(b'12345')
        code, out, err = self.review('--ticket', '03', '--mode', 'ticket', '--docs', str(self.docs))
        self.assertEqual((code, err), (0, ''), out)
        self.assertEqual(self.lines()[0], dict(feature='workflow-build', stage='review', session=SID, date=TODAY,
                                               started='2026-10-04 09:30', ended=ENDED, doc_bytes=5,
                                               ticket='03', mode='ticket'))


class AdditiveTest(WorklogCase):
    """AC-95: the new fields only add; an old line stays as it was and is never renamed."""

    OLD = '{"feature":"old-feature","stage":"build","session":"s0","date":"2026-09-01"}\n'

    def test_an_old_four_key_line_stays_byte_for_byte_before_the_new_one(self):
        self.home.mkdir()
        self.path.write_bytes(self.OLD.encode('utf-8'))
        self.add_ok()
        data = self.path.read_bytes().decode('utf-8')
        self.assertTrue(data.startswith(self.OLD))
        self.assertEqual(len(self.lines()), 2)


def number_in(text, number):
    """True when `number` stands alone in `text` (thousands commas and a trailing .0 allowed)."""
    plain = re.sub(r'(?<=\d),(?=\d{3}\b)', '', text)
    return re.search(rf'(?<![\d.]){number}(?:\.0+)?(?![\d.])', plain) is not None


class ReportCase(WorklogCase):
    """AC-4 to AC-9: `worklog report <work unit>` joins `work-units.jsonl` with `metrics.jsonl` by session.

    The fixture unit `track-f` has three merged tickets (a `build` line each: 01, 02, 03), a ticket that was only
    reviewed (04, so not merged), five sessions and three lines without a start. Session values: alpha 900,
    bravo 600, charlie 1200, echo 300 weighted tokens; delta has no metrics row. Build minutes: ticket 01 30,
    ticket 02 60, ticket 03 30 (the lines without a start add none), so 120 in all.
    """
    DAY = '2026-10-01'
    UNIT = 'track-f'
    WEIGHTED = {'sess-alpha': 900.0, 'sess-bravo': 600.0, 'sess-charlie': 1200.0, 'sess-echo': 300.0}

    def line(self, stage, session, ended, started=None, ticket=None, mode=None, doc_bytes=None, feature=None):
        """A work-unit line as `worklog add` writes it; `started` and `ended` are clock times of DAY."""
        row = {'feature': feature or self.UNIT, 'stage': stage, 'session': session, 'date': self.DAY}
        if started is not None:
            row['started'] = f'{self.DAY} {started}'
        row['ended'] = f'{self.DAY} {ended}'
        for key, value in (('doc_bytes', doc_bytes), ('ticket', ticket), ('mode', mode)):
            if value is not None:
                row[key] = value
        return row

    def unit_lines(self):
        return [
            self.line('build', 'sess-alpha', '10:40', started='10:10', ticket='01'),
            self.line('build', 'sess-alpha', '12:05', started='11:05', ticket='02'),
            self.line('review', 'sess-alpha', '12:16', started='12:06', ticket='01', mode='ticket'),
            self.line('build', 'sess-bravo', '15:40', started='15:10', ticket='03'),
            self.line('build', 'sess-charlie', '14:01', ticket='01'),
            self.line('build', 'sess-charlie', '14:06', ticket='03'),
            self.line('review', 'sess-charlie', '14:27', started='14:07', ticket='01', mode='delta', doc_bytes=4096),
            self.line('review', 'sess-delta', '16:12', started='16:02', ticket='04', mode='ticket'),
            self.line('build', 'sess-echo', '17:03', ticket='02'),
            self.line('build', 'sess-zulu', '09:30', started='09:00', ticket='01', feature='other-unit'),
        ]

    def write_files(self, lines=None, weighted=None):
        lines = self.unit_lines() if lines is None else lines
        weighted = self.WEIGHTED if weighted is None else weighted
        write_text(self.path, ''.join(json.dumps(row, separators=(',', ':')) + '\n' for row in lines))
        rows = [metrics_row(session, self.DAY, weighted=value) for session, value in weighted.items()]
        write_metrics_rows(self.home, rows + [metrics_row('sess-zulu', self.DAY, weighted=7777.0)])

    def report(self, unit=None):
        return run_cli('worklog', 'report', unit or self.UNIT, '--home', str(self.home))

    def report_lines(self, unit=None):
        code, out, err = self.report(unit)
        self.assertEqual((code, err), (0, ''), out)
        return out.splitlines()

    def line_with(self, lines, *needles):
        return next((line for line in lines if all(needle in line for needle in needles)), '')


class ReportTest(ReportCase):
    def test_it_joins_the_unit_by_session_and_prints_a_header_the_stage_lines_and_one_cost_line(self):
        """AC-4 and AC-5: each session counts once however many lines it holds; no per-ticket token number."""
        self.write_files()
        lines = self.report_lines()
        self.assertIn(self.UNIT, lines[0])
        self.assertTrue(number_in(lines[0], 3) and number_in(lines[0], 5), lines[0])   # merged tickets, sessions
        for shown in ('10:10', '10:40', '11:05', '12:05', '15:40', '4096'):
            self.assertTrue(self.line_with(lines, shown), shown)
        costs = [line for line in lines if line.startswith('cost:')]
        self.assertEqual(len(costs), 1, lines)
        # 3000 in all (900 + 600 + 1200 + 300), 1000 per merged ticket, 120 minutes in all, 40 per ticket
        for number in (3000, 1000, 40):
            self.assertTrue(number_in(costs[0], number), (number, costs[0]))
        for line in lines:
            if not line.startswith('cost:'):
                for number in (900, 600, 1200, 300, 3000, 1000, 7777):
                    self.assertFalse(number_in(line, number), (number, line))
        self.assertNotIn('7777', costs[0])
        # alpha holds tickets 01 and 02, charlie holds 01 and 03
        multi = [line for line in lines if 'session' in line and 'ticket' in line and number_in(line, 2)]
        self.assertTrue(multi, lines)

    def test_a_merged_ticket_is_a_build_line_and_its_minutes_come_from_its_build_lines_only(self):
        """AC-6: the review-only ticket 04 is not merged; a build line without a start adds no minutes and is
        counted; a ticket's review rounds are its review lines."""
        self.write_files()
        lines = self.report_lines()
        self.assertTrue(number_in(lines[0], 3), lines[0])
        self.assertTrue(number_in(self.line_with(lines, '10:10'), 30), lines)
        self.assertTrue(number_in(self.line_with(lines, '11:05'), 60), lines)
        self.assertTrue(number_in(self.line_with(lines, '15:10'), 30), lines)
        missing = [line for line in lines if 'start' in line.lower() and number_in(line, 3)]
        self.assertTrue(missing, lines)
        rounds = [line for line in lines if 'review' in line.lower() and number_in(line, 2)]
        self.assertTrue(rounds, lines)

    def test_a_session_without_a_metrics_row_is_left_out_of_the_sums_and_counted_with_a_measure_hint(self):
        """AC-7: delta (never measured) and, here, echo too."""
        self.write_files(weighted={key: value for key, value in self.WEIGHTED.items() if key != 'sess-echo'})
        lines = self.report_lines()
        hint = [line for line in lines if 'measure' in line]
        self.assertEqual(len(hint), 1, lines)
        self.assertTrue(number_in(hint[0], 2), hint)
        cost = self.line_with(lines, 'cost:')
        self.assertTrue(number_in(cost, 2700) and number_in(cost, 900), cost)

    def test_a_unit_with_no_lines_stops_with_an_anomaly_line_naming_the_units_that_exist(self):
        self.write_files()
        assert_cli_error(self, self.report('no-such-unit'), self.UNIT, 'other-unit')

    def test_a_unit_with_no_merged_ticket_prints_no_per_ticket_numbers(self):
        """AC-7: only reviewed or planned, so nothing to divide by."""
        self.write_files(self.unit_lines() + [
            self.line('grill', 'sess-alpha', '08:20', started='08:00', feature='review-only'),
            self.line('review', 'sess-alpha', '08:50', started='08:30', ticket='04', mode='ticket',
                      feature='review-only')])
        code, out, err = self.report('review-only')
        self.assertEqual((code, err), (0, ''), out)
        self.assertNotIn('Traceback', out)
        self.assertEqual([line for line in out.splitlines() if re.search(r'\bper\b.*ticket', line, re.I)], [])

    def test_a_build_line_without_a_ticket_is_the_one_merged_ticket_of_an_ad_hoc_unit(self):
        """An ad-hoc unit has no numbered tickets: its `build` line counts as 1 merged ticket, prints as
        `adhoc build`, and the cost line gives the per-merged-ticket numbers (47 build minutes; the review
        line adds none)."""
        unit = 'a-small-task'
        self.write_files([
            self.line('build', 'sess-kilo', '09:52', started='09:05', feature=unit),
            self.line('review', 'sess-lima', '10:13', started='09:53', mode='ticket', feature=unit)],
            weighted={'sess-kilo': 1234.0, 'sess-lima': 800.0})
        lines = self.report_lines(unit)
        self.assertIn(unit, lines[0])
        self.assertTrue(number_in(lines[0], 1) and number_in(lines[0], 2), lines[0])   # merged tickets, sessions
        adhoc = [line for line in lines if line.startswith('adhoc build')]
        self.assertEqual(len(adhoc), 1, lines)
        self.assertIn('09:05', adhoc[0])
        self.assertIn('09:52', adhoc[0])
        self.assertTrue(number_in(adhoc[0], 47), adhoc[0])
        costs = [line for line in lines if line.startswith('cost:')]
        self.assertEqual(len(costs), 1, lines)
        self.assertEqual(costs[0].count('per merged ticket'), 2, costs[0])   # tokens and minutes
        self.assertTrue(number_in(costs[0], 2034) and number_in(costs[0], 47), costs[0])


class ReportReadOnlyTest(ReportCase):
    def setUp(self):
        super().setUp()
        self.repo = GitFixture(self.root / 'repo')
        self.home = self.repo.root / 'anomaly-home'

    def snapshot(self):
        return {path.relative_to(self.home): path.read_bytes() for path in sorted(self.home.rglob('*'))
                if path.is_file()}

    def test_it_writes_no_file_and_makes_no_commit(self):
        """AC-9."""
        self.write_files()
        self.repo.commit(['anomaly-home/work-units.jsonl', 'anomaly-home/metrics.jsonl'], 'chore: start', NOW.date())
        before, head = self.snapshot(), self.repo.git('rev-parse', 'HEAD')
        code, out, err = self.report()
        self.assertEqual((code, err), (0, ''), out)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.repo.git('rev-parse', 'HEAD'), head)
        self.assertEqual(self.repo.status(), [])
        self.assertFalse([line for line in out.splitlines() if line.startswith('commit')], out)


class CommitTest(WorklogCase):
    def setUp(self):
        super().setUp()
        self.repo = GitFixture(self.root / 'repo')
        self.home = self.repo.root / 'anomaly-home'
        self.repo.write('README.md', 'x\n')
        self.repo.write('anomaly-home/anomalies/older.md', 'an older anomaly\n')
        self.repo.commit(['README.md', 'anomaly-home/anomalies/older.md'], 'chore: start', NOW.date())

    def last_commit_files(self):
        return sorted(self.repo.git('show', '--name-only', '--format=', 'HEAD').split())

    def test_only_the_work_units_file_is_committed_and_foreign_edits_stay_out(self):
        self.repo.write('README.md', 'edited elsewhere\n')
        self.repo.write('anomaly-home/anomalies/older.md', 'edited in home\n')
        self.repo.write('anomaly-home/ideas/unrelated.md', 'draft\n')
        before = self.repo.git('rev-parse', 'HEAD').strip()
        out = self.add_ok('workflow-build', 'build')
        self.assertNotEqual(self.repo.git('rev-parse', 'HEAD').strip(), before)
        self.assertEqual(self.last_commit_files(), ['anomaly-home/work-units.jsonl'])
        self.assertEqual(sorted(self.repo.status()),
                         [' M README.md', ' M anomaly-home/anomalies/older.md', '?? anomaly-home/ideas/unrelated.md'])
        self.assertEqual(self.repo.git('log', '-1', '--format=%s').strip(),
                         'chore(anomaly): log work unit workflow-build build')
        commit = [line for line in out if line.startswith('commit: ')]
        self.assertEqual(len(commit), 1, out)
        self.assertEqual(commit[0], f'commit: {self.repo.git("rev-parse", "HEAD").strip()[:7]}')

    def test_start_commits_nothing_and_the_start_record_stays_out_of_home(self):
        before = self.repo.git('rev-parse', 'HEAD').strip()
        out = self.start_ok('workflow-build', 'build')
        self.assertEqual(self.repo.git('rev-parse', 'HEAD').strip(), before)
        self.assertEqual(self.repo.status(), [])
        self.assertFalse([line for line in out if line.startswith('commit')], out)

    def test_each_run_is_its_own_commit_of_the_same_path(self):
        self.add_ok('workflow-build', 'build')
        self.add_ok('workflow-build', 'review')
        self.assertEqual(self.repo.git('rev-list', '--count', 'HEAD').strip(), '3')
        self.assertEqual(self.last_commit_files(), ['anomaly-home/work-units.jsonl'])
        self.assertEqual(self.repo.status(), [])

    def test_a_home_outside_git_says_so_and_still_writes(self):
        self.home = self.root / 'plain-home'
        out = self.add_ok()
        self.assertIn('commit: none, home is not in a git repository', out)
        self.assertEqual(len(self.lines()), 1)

    def test_a_failing_commit_keeps_the_line_and_reports_one_line(self):
        hook = self.repo.root / '.git' / 'hooks' / 'pre-commit'
        hook.write_bytes(b'#!/bin/sh\nexit 1\n')
        hook.chmod(0o755)
        out = self.add_ok()
        self.assertEqual(len(self.lines()), 1)
        failed = [line for line in out if line.startswith('commit: failed')]
        self.assertEqual(len(failed), 1, out)
