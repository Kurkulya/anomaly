"""`bench score`: the seeded-defect benchmark scorer, through the CLI in-process (seam 1), over small
synthetic defect lists and over the real fixtures under tests/bench/. A second group checks the
fixtures themselves: every planted place points at real text, the windows do not overlap, the
security fixture plants no credential."""
import ast
import contextlib
import io
import json
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

from anomaly_loop import bench, cli, constants, flags
from tests.fixtures import BENCH, assert_cli_error, run_cli, write_text

DASH = '\u2014'
FIXTURES = (   # (name, defect list, planted defects, decoys)
    ('code', BENCH / 'code' / 'defects.json', 10, 3),
    ('feature', BENCH / 'feature' / 'defects.json', 8, 3),
    ('feature rules mode', BENCH / 'feature' / 'rules' / 'defects.json', 5, 2),
    ('feature cumulative mode', BENCH / 'feature' / 'cumulative' / 'defects.json', 1, 1),
    ('security', BENCH / 'security' / 'defects.json', 10, 3),
)


def finding(severity, path, line, problem='a problem', state='observed', fix='a fix'):
    return f'- [{severity}] {path}:{line} {DASH} {problem} {DASH} fix: {fix} {DASH} {state}'


def defect(ident, file='a.py', lines=(10, 12), min_severity='High', **extra):
    return {'id': ident, 'min_severity': min_severity, 'places': [{'file': file, 'lines': list(lines)}], **extra}


def block(out):
    """The lines under `median of ...` as {name: value}."""
    lines = out.splitlines()
    starts = [number for number, line in enumerate(lines) if line.startswith('median of')]
    if not starts:
        raise AssertionError(f'no median block in the output: {out!r}')
    return dict(line.split(': ', 1) for line in lines[starts[0] + 1:])


class ScoreCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)

    def write_list(self, defects, decoys=(), name='fixture', **extra):
        path = self.root / f'{name}.json'
        write_text(path, json.dumps({'fixture': 'demo', 'defects': defects, 'decoys': list(decoys), **extra}))
        return path

    def write_run(self, *lines, name='run1.txt'):
        path = self.root / name
        write_text(path, '\n'.join(lines) + '\n')
        return path

    def score(self, defects, *runs):
        return run_cli('bench', 'score', str(defects), *(str(run) for run in runs))

    def scored(self, defects, *lines, decoys=(), **extra):
        """The median block of one run of these finding lines against these defects."""
        code, out, err = self.score(self.write_list(defects, decoys, **extra), self.write_run(*lines))
        self.assertEqual(code, 0, err)
        return block(out)

    def assert_error(self, result, *fragments):
        assert_cli_error(self, result, *fragments)


class RegistryTest(ScoreCase):
    def test_bench_is_registered_once_with_the_score_action(self):
        self.assertEqual(cli.COMMANDS.count('bench'), 1)
        out = io.StringIO()
        with contextlib.redirect_stdout(out), self.assertRaises(SystemExit):
            cli.main(['bench', '--help'], environ={})
        self.assertEqual(re.findall(r'^ {4}([a-z-]+)\s{2,}\S', out.getvalue(), re.M), ['score'])


class FoundTest(ScoreCase):
    def test_a_finding_in_the_planted_range_is_found_at_the_min_severity(self):
        result = self.scored([defect('D1')], finding('High', 'a.py', 11))
        self.assertEqual(result, {'found': '1 of 1', 'found at min severity': '1 of 1',
                                  'missed': '0 of 1', 'false High': '0'})

    def test_the_window_is_three_lines_on_each_side_of_the_range(self):
        window = constants.BENCH_WINDOW
        for line, found in ((10 - window, 1), (12 + window, 1), (10 - window - 1, 0), (12 + window + 1, 0)):
            with self.subTest(line=line):
                result = self.scored([defect('D1')], finding('High', 'a.py', line))
                self.assertEqual(result['found'], f'{found} of 1')

    def test_a_finding_below_the_min_severity_is_found_but_not_at_the_min_severity(self):
        result = self.scored([defect('D1')], finding('Medium', 'a.py', 11))
        self.assertEqual((result['found'], result['found at min severity']), ('1 of 1', '0 of 1'))

    def test_a_blocker_is_found_on_a_high_defect(self):
        result = self.scored([defect('D1')], finding('Blocker', 'a.py', 11))
        self.assertEqual(result['found at min severity'], '1 of 1')

    def test_a_low_or_a_nit_is_not_found(self):
        for severity in ('Low', 'Nit'):
            with self.subTest(severity=severity):
                result = self.scored([defect('D1', min_severity='Medium')], finding(severity, 'a.py', 11))
                self.assertEqual((result['found'], result['missed']), ('0 of 1', '1 of 1'))

    def test_a_finding_in_another_file_is_missed_whatever_its_line(self):
        result = self.scored([defect('D1')], finding('Medium', 'b.py', 11))
        self.assertEqual(result['missed'], '1 of 1')

    def test_a_defect_found_by_two_findings_counts_once(self):
        result = self.scored([defect('D1')], finding('High', 'a.py', 10), finding('High', 'a.py', 12))
        self.assertEqual(result['found'], '1 of 1')

    def test_a_defect_counts_at_min_severity_when_any_matching_finding_reaches_it(self):
        result = self.scored([defect('D1')], finding('Medium', 'a.py', 10), finding('High', 'a.py', 12))
        self.assertEqual((result['found'], result['found at min severity']), ('1 of 1', '1 of 1'))

    def test_a_defect_with_two_places_is_found_at_either(self):
        planted = {'id': 'D1', 'min_severity': 'High', 'places': [
            {'file': 'a.py', 'lines': [10, 10]}, {'file': 'b.py', 'lines': [40, 42]}]}
        for path, line in (('a.py', 10), ('b.py', 41)):
            with self.subTest(path=path):
                self.assertEqual(self.scored([planted], finding('High', path, line))['found'], '1 of 1')

    def test_a_path_is_read_with_forward_slashes_without_a_leading_dot_or_a_parent_folder(self):
        planted = [defect('D1', file='pkg/a.py')]
        for path, found in (('pkg/a.py', 1), ('./pkg/a.py', 1), ('pkg\\a.py', 1), ('C:/work/repo/pkg/a.py', 1),
                            ('xpkg/a.py', 0), ('a.py', 0)):
            with self.subTest(path=path):
                self.assertEqual(self.scored(planted, finding('High', path, 11))['found'], f'{found} of 1')

    def test_a_problem_that_holds_a_dash_and_a_line_that_is_not_a_finding_are_read_right(self):
        lines = ['## Findings', 'fine: no resource problems', '| rule | present | a.py:11 |',
                 finding('High', 'a.py', 11, problem=f'bad {DASH} very bad {DASH} fix: nothing', fix='change it')]
        self.assertEqual(self.scored([defect('D1')], *lines)['found'], '1 of 1')

    def test_an_indented_finding_line_is_read(self):
        self.assertEqual(self.scored([defect('D1')], '  ' + finding('High', 'a.py', 11))['found'], '1 of 1')

    def test_a_run_with_no_finding_line_misses_everything(self):
        result = self.scored([defect('D1'), defect('D2', lines=(30, 30))], 'fine: everything is fine')
        self.assertEqual((result['found'], result['missed'], result['false High']), ('0 of 2', '2 of 2', '0'))


class FalseHighTest(ScoreCase):
    def test_a_blocker_or_a_high_that_matches_no_defect_is_a_false_high(self):
        for severity in ('Blocker', 'High'):
            with self.subTest(severity=severity):
                result = self.scored([defect('D1')], finding(severity, 'b.py', 5))
                self.assertEqual(result['false High'], '1')

    def test_a_medium_that_matches_no_defect_is_not_a_false_high(self):
        self.assertEqual(self.scored([defect('D1')], finding('Medium', 'b.py', 5))['false High'], '0')

    def test_a_high_on_a_planted_defect_is_not_a_false_high(self):
        self.assertEqual(self.scored([defect('D1')], finding('High', 'a.py', 11))['false High'], '0')

    def test_a_high_on_a_decoy_is_a_false_high_and_the_run_line_names_the_decoy(self):
        decoy = {'id': 'X1', 'places': [{'file': 'c.py', 'lines': [30, 35]}]}
        out = self.score(self.write_list([defect('D1')], [decoy]), self.write_run(finding('High', 'c.py', 33)))[1]
        self.assertEqual(block(out)['false High'], '1')
        self.assertIn('  false High: c.py:33 (decoy X1)', out)

    def test_each_false_high_line_counts_and_is_listed(self):
        out = self.score(self.write_list([defect('D1')]),
                         self.write_run(finding('High', 'b.py', 5), finding('Blocker', 'b.py', 9)))[1]
        self.assertEqual(block(out)['false High'], '2')
        self.assertIn('  false High: b.py:5\n', out)
        self.assertIn('  false High: b.py:9\n', out)

    def test_a_finding_near_both_a_defect_and_a_decoy_matches_the_defect(self):
        decoy = {'id': 'X1', 'places': [{'file': 'a.py', 'lines': [14, 16]}]}
        result = self.scored([defect('D1')], finding('High', 'a.py', 15), decoys=[decoy])
        self.assertEqual((result['found'], result['false High']), ('1 of 1', '0'))


class UnverifiedTest(ScoreCase):
    def test_a_defect_that_must_be_unverified_is_found_only_by_an_unverified_finding(self):
        planted = [defect('F-D8', min_severity='Medium', unverified=True)]
        for state, found in (('unverified', 1), ('observed', 0)):
            with self.subTest(state=state):
                result = self.scored(planted, finding('Medium', 'a.py', 11, state=state))
                self.assertEqual(result['found'], f'{found} of 1')

    def test_the_state_is_the_word_after_the_last_dash_and_text_after_it_is_ignored(self):
        planted = [defect('F-D8', min_severity='Medium', unverified=True)]
        for state, found in (('unverified (not run)', 1), ('unverified.', 1), (f'observed {DASH} unverified', 1),
                             ('observed (pattern); the hang itself is unverified', 0)):
            with self.subTest(state=state):
                result = self.scored(planted, finding('Medium', 'a.py', 11, state=state))
                self.assertEqual(result['found'], f'{found} of 1')

    def test_a_finding_on_the_defect_that_is_not_unverified_is_still_no_false_high(self):
        planted = [defect('F-D8', min_severity='Medium', unverified=True)]
        result = self.scored(planted, finding('High', 'a.py', 11, state='observed'))
        self.assertEqual((result['found'], result['false High']), ('0 of 1', '0'))

    def test_an_ordinary_defect_is_found_either_way(self):
        for state in ('observed', 'unverified'):
            with self.subTest(state=state):
                self.assertEqual(self.scored([defect('D1')], finding('High', 'a.py', 11, state=state))['found'],
                                 '1 of 1')


class RuleModeTest(ScoreCase):
    RULES = [{'id': 'F-R1', 'rule': 'K02', 'min_severity': 'High'},
             {'id': 'F-R2', 'rule': 'K1', 'min_severity': 'Medium'}]

    def test_a_defect_with_a_rule_id_is_found_by_a_finding_that_quotes_it_in_any_file(self):
        result = self.scored(self.RULES, finding('High', 'whatever.md', 3, problem='keep rule K02 is missing'))
        self.assertEqual((result['found'], result['found at min severity']), ('1 of 2', '1 of 2'))

    def test_the_rule_id_is_a_whole_token(self):
        result = self.scored(self.RULES, finding('High', 'x.md', 3, problem='rule K10 is missing'))
        self.assertEqual(result['found'], '0 of 2')

    def test_the_rule_id_may_stand_in_the_fix_text(self):
        result = self.scored(self.RULES, finding('High', 'x.md', 3, problem='a rule is missing', fix='restore K02'))
        self.assertEqual(result['found'], '1 of 2')

    def test_a_rule_finding_still_needs_the_min_severity_floor_of_medium(self):
        result = self.scored(self.RULES, finding('Low', 'x.md', 3, problem='rule K02 is missing'))
        self.assertEqual(result['found'], '0 of 2')

    def test_a_high_that_quotes_no_planted_rule_is_a_false_high(self):
        self.assertEqual(self.scored(self.RULES, finding('High', 'x.md', 3, problem='rule K07'))['false High'], '1')

    def test_a_defect_with_a_rule_and_a_place_is_found_by_either(self):
        planted = [{'id': 'F-R3', 'rule': 'X2', 'min_severity': 'High', 'places': [{'file': 'SKILL.md', 'lines': [19, 19]}]}]
        for line in (finding('High', 'SKILL.md', 20), finding('High', 'other.md', 1, problem='drop rule X2 present')):
            with self.subTest(line=line):
                self.assertEqual(self.scored(planted, line)['found'], '1 of 1')

    def test_a_decoy_rule_id_makes_a_high_that_quotes_it_a_false_high(self):
        out = self.score(self.write_list(self.RULES, [{'id': 'Z1', 'rule': 'K05'}]),
                         self.write_run(finding('High', 'x.md', 3, problem='rule K05 is absent')))[1]
        self.assertEqual(block(out)['false High'], '1')
        self.assertIn('(decoy Z1)', out)


class CategoryTest(ScoreCase):
    PLANTED = [defect('S-D1', category='A03', min_severity='Blocker'),
               defect('S-D2', file='b.py', category='A01')]

    def test_category_right_counts_a_found_defect_whose_finding_carries_the_category(self):
        result = self.scored(self.PLANTED, finding('Blocker', 'a.py', 11, problem='A03 Injection: SQL from a field'),
                             finding('High', 'b.py', 11, problem='A02 Cryptographic Failures: wrong label'))
        self.assertEqual((result['found'], result['category right']), ('2 of 2', '1 of 2'))

    def test_a_list_without_categories_prints_no_category_line(self):
        self.assertNotIn('category right', self.scored([defect('D1')], finding('High', 'a.py', 11)))

    def test_a_missed_defect_is_not_category_right(self):
        result = self.scored(self.PLANTED, finding('High', 'z.py', 1, problem='A03 Injection'))
        self.assertEqual(result['category right'], '0 of 2')

    def test_the_label_is_read_as_a_whole_token(self):
        result = self.scored(self.PLANTED[:1], finding('Blocker', 'a.py', 11, problem='HEAD03 and A030 are no labels'))
        self.assertEqual(result['category right'], '0 of 1')

    def test_the_label_in_the_fix_text_does_not_count(self):
        result = self.scored(self.PLANTED[:1], finding('Blocker', 'a.py', 11, problem='no label', fix='see A03'))
        self.assertEqual(result['category right'], '0 of 1')

    def test_a_finding_below_medium_gives_no_category(self):
        result = self.scored(self.PLANTED[:1], finding('Low', 'a.py', 11, problem='A03 Injection'))
        self.assertEqual(result['category right'], '0 of 1')

    def test_other_written_forms_of_the_label_are_read(self):
        for problem in ('A03 SQL from a field', 'A3:2021 SQL from a field', 'OWASP-A3 SQL from a field',
                        'OWASP-A03 SQL from a field', 'A03:2021 SQL from a field', 'A03-Injection SQL from a field'):
            with self.subTest(problem=problem):
                result = self.scored(self.PLANTED[:1], finding('Blocker', 'a.py', 11, problem=problem))
                self.assertEqual(result['category right'], '1 of 1')

    def test_a_bare_one_digit_label_is_no_label(self):
        """`A1` is a spreadsheet cell as often as a category."""
        result = self.scored([defect('S-D1', category='A01')], finding('High', 'a.py', 11, problem='cell A1 holds it'))
        self.assertEqual(result['category right'], '0 of 1')

    def test_category_of_reads_the_first_label_or_name_and_nothing_else(self):
        for text, label in (('A03 Injection', 'A03'), ('A3:2021', 'A03'), ('OWASP A9', 'A09'), ('A10:2021', 'A10'),
                            ('A1 and A2', ''), ('A030', ''), ('HEAD03', ''), ('no label here', ''),
                            ('server-side request forgery', 'A10'), ('Injection then A01', 'A03'),
                            ('A01 then Injection', 'A01')):
            with self.subTest(text=text):
                self.assertEqual(bench.category_of(text), label)

    def test_the_public_category_name_alone_is_read_for_every_category(self):
        for label, name in constants.OWASP_2021:
            for written in (name, name.upper()):
                with self.subTest(label=label, written=written):
                    planted = [defect('S-D1', category=label)]
                    result = self.scored(planted, finding('High', 'a.py', 11, problem=f'{written}: a problem'))
                    self.assertEqual(result['category right'], '1 of 1')

    def test_the_first_label_or_name_in_the_problem_text_is_the_one_read(self):
        result = self.scored(self.PLANTED[:1], finding('Blocker', 'a.py', 11, problem='A01 Broken Access Control, not A03'))
        self.assertEqual(result['category right'], '0 of 1')

    def test_a_defect_with_a_list_of_categories_is_right_for_any_of_them(self):
        planted = [defect('S-D6', category=['A01', 'A07'])]
        for problem, right in (('A01 no session check', 1), ('Identification and Authentication Failures', 1),
                               ('A02 wrong', 0)):
            with self.subTest(problem=problem):
                result = self.scored(planted, finding('High', 'a.py', 11, problem=problem))
                self.assertEqual(result['category right'], f'{right} of 1')

    def test_a_problem_that_holds_a_fix_marker_keeps_its_label_when_the_last_marker_splits_the_line(self):
        problem = f'dull {DASH} fix: no {DASH} A03 Injection'
        result = self.scored(self.PLANTED[:1], finding('Blocker', 'a.py', 11, problem=problem, fix='escape it'))
        self.assertEqual(result['category right'], '1 of 1')


class MedianTest(ScoreCase):
    def runs(self, *counts):
        """One run for each count: that many of five defects found, and one false High per run after the first."""
        defects = [defect(f'D{n}', file=f'f{n}.py') for n in range(5)]
        paths = []
        for number, found in enumerate(counts, start=1):
            lines = ['fine: the rest'] + [finding('High', f'f{n}.py', 11) for n in range(found)]
            lines += [finding('High', 'other.py', 1)] * (number - 1)
            paths.append(self.write_run(*lines, name=f'run{number}.txt'))
        return self.score(self.write_list(defects, [], 'five'), *paths)

    def test_three_runs_print_each_run_and_the_median(self):
        code, out, err = self.runs(2, 5, 3)
        self.assertEqual(code, 0, err)
        lines = out.splitlines()
        self.assertEqual(lines[0], 'fixture demo: 5 planted defects, 0 decoys')
        self.assertIn('run 1: found 2, found at min severity 2, missed 3 (D2, D3, D4), false High 0', lines)
        self.assertIn('run 2: found 5, found at min severity 5, missed 0, false High 1', lines)
        self.assertEqual(block(out), {'found': '3 of 5', 'found at min severity': '3 of 5',
                                      'missed': '2 of 5', 'false High': '1'})
        self.assertIn('median of 3 runs', lines)

    def test_the_median_is_not_the_mean(self):
        self.assertEqual(block(self.runs(0, 0, 5)[1])['found'], '0 of 5')

    def test_two_runs_give_the_mean_of_the_two(self):
        self.assertEqual(block(self.runs(2, 3)[1])['found'], '2.5 of 5')

    def test_one_run_is_its_own_median(self):
        out = self.runs(4)[1]
        self.assertIn('median of 1 run', out.splitlines())
        self.assertEqual(block(out)['found'], '4 of 5')

    def test_the_runs_are_scored_in_the_order_given(self):
        out = self.runs(1, 4, 2)[1]
        self.assertEqual([line.split(':')[0] for line in out.splitlines() if line.startswith('run ')],
                         ['run 1', 'run 2', 'run 3'])


class ErrorTest(ScoreCase):
    def test_a_missing_defect_list_is_one_anomaly_line(self):
        self.assert_error(self.score(self.root / 'none.json', self.write_run('x')), 'none.json')

    def test_a_missing_finding_file_is_one_anomaly_line(self):
        self.assert_error(self.score(self.write_list([defect('D1')]), self.root / 'none.txt'), 'none.txt')

    def test_a_defect_list_that_is_not_json_names_the_file(self):
        path = self.root / 'bad.json'
        write_text(path, '{not json')
        self.assert_error(self.score(path, self.write_run('x')), 'bad.json', 'JSON')

    def test_a_defect_list_with_a_bad_entry_names_the_file_and_the_entry(self):
        broken = {'fixture': 'demo', 'defects': [{'id': 'D1', 'min_severity': 'Severe', 'places': []}]}
        cases = (
            ('a severity that is not in the scale', broken),
            ('no defects key', {'fixture': 'demo'}),
            ('no id', {'fixture': 'demo', 'defects': [{'min_severity': 'High', 'places': [{'file': 'a', 'lines': [1, 2]}]}]}),
            ('no place and no rule', {'fixture': 'demo', 'defects': [{'id': 'D1', 'min_severity': 'High'}]}),
            ('a range that runs backwards', {'fixture': 'demo', 'defects': [defect('D1', lines=(9, 3))]}),
            ('a range of one number', {'fixture': 'demo', 'defects': [defect('D1', lines=(9,))]}),
            ('a repeated id', {'fixture': 'demo', 'defects': [defect('D1'), defect('D1', file='b.py')]}),
            ('a category that is not a label', {'fixture': 'demo', 'defects': [defect('D1', category='Injection')]}),
            ('a category list with a name in it', {'fixture': 'demo', 'defects': [defect('D1', category=['A01', 'Injection'])]}),
            ('an empty category list', {'fixture': 'demo', 'defects': [defect('D1', category=[])]}),
            ('no defects at all', {'fixture': 'demo', 'defects': []}),
            ('a list at the top', []),
        )
        for name, content in cases:
            with self.subTest(name):
                path = self.root / 'case.json'
                write_text(path, json.dumps(content))
                self.assert_error(self.score(path, self.write_run('x')), 'case.json')

    def test_a_finding_line_of_the_wrong_shape_names_the_file_and_the_line_number(self):
        run = self.write_run('fine', '- [High] a.py:11 - one dash only - fix: x - observed')
        self.assert_error(self.score(self.write_list([defect('D1')]), run), 'run1.txt:2')

    def test_each_wrong_finding_shape_is_refused(self):
        wrong = (
            f'- [High] a.py {DASH} no line {DASH} fix: x {DASH} observed',
            f'- [High] a.py:11 {DASH} no fix {DASH} observed',
            f'- [High] a.py:11 {DASH} a problem {DASH} fix: x {DASH} maybe',
            f'- [High] a.py:11 {DASH} a problem {DASH} fix: x {DASH} observedly',
            f'- [High] a.py:11 {DASH} a problem {DASH} fix: x {DASH} observed {DASH} maybe',
            f'- [High] a.py:11 {DASH} a problem {DASH} fix: x',
            f'- [High] a.py:11-14 {DASH} a range {DASH} fix: x {DASH} observed',
        )
        for line in wrong:
            with self.subTest(line=line):
                self.assert_error(self.score(self.write_list([defect('D1')]), self.write_run(line)), 'run1.txt:1')

    def test_a_bracket_word_that_is_not_a_severity_is_prose_and_is_ignored(self):
        prose = ('- [README](README.md) updated', '- [Done] all good', '- [fine] nothing to report',
                 f'- [Critical] a.py:11 {DASH} a problem {DASH} fix: x {DASH} observed', '- [x] ticked', '- [ ] open')
        result = self.scored([defect('D1')], *prose, finding('High', 'a.py', 11))
        self.assertEqual((result['found'], result['false High']), ('1 of 1', '0'))

    def test_a_near_miss_bullet_form_of_a_finding_is_refused_by_line(self):
        for line in (f'* [High] a.py:11 {DASH} a problem {DASH} fix: x {DASH} observed',
                     f'+ [High] a.py:11 {DASH} a problem {DASH} fix: x {DASH} observed',
                     f'1. [High] a.py:11 {DASH} a problem {DASH} fix: x {DASH} observed',
                     f'2) [Blocker] a.py:11 {DASH} a problem {DASH} fix: x {DASH} observed',
                     f'- **[High]** a.py:11 {DASH} a problem {DASH} fix: x {DASH} observed',
                     f'- [high] a.py:11 {DASH} a problem {DASH} fix: x {DASH} observed',
                     f'- [HIGH] a.py:11 {DASH} a problem {DASH} fix: x {DASH} observed'):
            with self.subTest(line=line):
                self.assert_error(self.score(self.write_list([defect('D1')]), self.write_run(line)), 'run1.txt:1')

    def test_the_refusal_names_the_dash_so_a_console_that_cannot_show_it_still_reads_it(self):
        run = self.write_run('- [High] a.py:11 - a problem - fix: x - observed')
        self.assert_error(self.score(self.write_list([defect('D1')]), run), 'em dash (U+2014)')

    def test_a_blank_finding_file_is_refused(self):
        path = self.root / 'blank.txt'
        write_text(path, '\n  \n')
        self.assert_error(self.score(self.write_list([defect('D1')]), path), 'blank.txt')

    def test_more_than_three_runs_are_refused(self):
        runs = [self.write_run('fine', name=f'run{n}.txt') for n in range(4)]
        self.assert_error(self.score(self.write_list([defect('D1')]), *runs), '1 to 3 runs, got 4')

    def test_a_missing_argument_is_a_usage_error_on_one_line(self):
        self.assert_error(run_cli('bench', 'score'))
        self.assert_error(run_cli('bench', 'score', str(self.write_list([defect('D1')]))))
        self.assert_error(run_cli('bench'))

    def test_a_file_that_is_not_utf8_is_refused_by_name(self):
        path = self.root / 'latin.txt'
        path.write_bytes(b'- [High] caf\xe9')
        self.assert_error(self.score(self.write_list([defect('D1')]), path), 'latin.txt')

    def test_a_failure_writes_nothing_to_standard_output(self):
        self.assertEqual(self.score(self.root / 'none.json', self.write_run('x'))[1], '')


def fixture_run(spec, severity=None):
    """The finding lines of a perfect run: one at each defect's first place (or quoting its rule id),
    at its min severity, labelled with its category, unverified where the defect asks for it."""
    lines = []
    for item in spec['defects']:
        place = (item.get('places') or [{'file': 'SKILL.md', 'lines': [1, 1]}])[0]
        category = item.get('category', '')
        problem = ' '.join(filter(None, [category if isinstance(category, str) else category[-1],
                                         item.get('rule'), item['what']]))
        lines.append(finding(severity or item['min_severity'], place['file'], place['lines'][0], problem,
                             'unverified' if item.get('unverified') else 'observed'))
    return lines


class RealFixtureTest(ScoreCase):
    def load(self, path):
        return json.loads(path.read_text(encoding='utf-8'))

    def test_a_perfect_run_finds_every_planted_defect_at_its_min_severity_with_no_false_high(self):
        for name, path, planted, decoys in FIXTURES:
            with self.subTest(name):
                spec = self.load(path)
                code, out, err = self.score(path, self.write_run(*fixture_run(spec)))
                self.assertEqual(code, 0, err)
                self.assertEqual(out.splitlines()[0], f'fixture {name}: {flags.plural(planted, "planted defect")}, '
                                                      f'{flags.plural(decoys, "decoy")}')
                result = block(out)
                self.assertEqual((result['found'], result['found at min severity'], result['missed'],
                                  result['false High']), (f'{planted} of {planted}',) * 2 + (f'0 of {planted}', '0'))
                if any('category' in item for item in spec['defects']):
                    self.assertEqual(result['category right'], f'{planted} of {planted}')

    def test_a_run_of_medium_findings_finds_the_defects_but_not_at_min_severity_where_it_is_higher(self):
        for name, path, planted, _ in FIXTURES:
            with self.subTest(name):
                spec = self.load(path)
                result = block(self.score(path, self.write_run(*fixture_run(spec, 'Medium')))[1])
                wanted = sum(1 for item in spec['defects'] if item['min_severity'] == 'Medium')
                self.assertEqual((result['found'], result['found at min severity']),
                                 (f'{planted} of {planted}', f'{wanted} of {planted}'))

    def test_a_high_on_each_decoy_is_a_false_high_and_finds_nothing(self):
        for name, path, planted, decoys in FIXTURES:
            with self.subTest(name):
                spec = self.load(path)
                lines = []
                for item in spec['decoys']:
                    place = (item.get('places') or [{'file': 'SKILL.md', 'lines': [1, 1]}])[0]
                    lines.append(finding('High', place['file'], place['lines'][0], f"{item.get('rule', '')} {item['what']}"))
                result = block(self.score(path, self.write_run(*lines))[1])
                self.assertEqual((result['found'], result['false High']), (f'0 of {planted}', str(decoys)))

    def test_a_finding_on_the_use_of_the_unrequested_flag_is_the_planted_defect_not_a_false_high(self):
        path = BENCH / 'feature' / 'defects.json'
        result = block(self.score(path, self.write_run(
            finding('High', 'tally/cli.py', 19, 'the --verbose flag is used and nobody asked for it')))[1])
        self.assertEqual((result['found'], result['false High']), ('1 of 8', '0'))

    def test_a_clean_report_misses_every_defect(self):
        for name, path, planted, _ in FIXTURES:
            with self.subTest(name):
                result = block(self.score(path, self.write_run('fine: nothing to report'))[1])
                self.assertEqual((result['found'], result['missed'], result['false High']),
                                 (f'0 of {planted}', f'{planted} of {planted}', '0'))

    def test_the_unverified_feature_defect_needs_the_unverified_mark(self):
        spec = self.load(BENCH / 'feature' / 'defects.json')
        lines = [line.replace(f'{DASH} unverified', f'{DASH} observed') for line in fixture_run(spec)]
        result = block(self.score(BENCH / 'feature' / 'defects.json', self.write_run(*lines))[1])
        self.assertEqual(result['found'], '7 of 8')

    def test_three_runs_of_a_fixture_print_the_median(self):
        spec = self.load(BENCH / 'code' / 'defects.json')
        full, half = fixture_run(spec), fixture_run(spec)[:4]
        runs = [self.write_run(*lines, name=f'r{n}.txt') for n, lines in enumerate((half, full, half), 1)]
        self.assertEqual(block(self.score(BENCH / 'code' / 'defects.json', *runs)[1])['found'], '4 of 10')


def head_file(root, relative):
    """The file as the reviewed branch has it: the change tree laid over the base tree; a fixture
    without trees (the rules-mode set) keeps its files beside its defect list."""
    for folder in (root / 'change', root / 'base', root):
        if (folder / relative).is_file():
            return folder / relative
    return None


class FixtureShapeTest(unittest.TestCase):
    """The fixtures themselves: they are data, so these checks keep them honest as they are edited."""

    def spec(self, path):
        return json.loads(path.read_text(encoding='utf-8'))

    def places(self, path):
        spec = self.spec(path)
        return [(item, place) for kind in ('defects', 'decoys') for item in spec[kind] for place in item.get('places', [])]

    def test_each_fixture_plants_the_briefed_number_of_defects_and_decoys(self):
        for name, path, planted, decoys in FIXTURES:
            with self.subTest(name):
                spec = self.spec(path)
                self.assertEqual((len(spec['defects']), len(spec['decoys'])), (planted, decoys))
                self.assertEqual(spec['fixture'], name)

    def test_every_defect_list_loads_through_its_one_reader(self):
        """Unique ids and a min severity in the scale are rules of bench.load_fixture, which refuses a list
        that breaks one; the test does not restate them."""
        for name, path, _, _ in FIXTURES:
            with self.subTest(name):
                self.assertEqual(bench.load_fixture(path).name, name)

    def test_every_planted_place_points_at_real_non_blank_text_of_the_reviewed_files(self):
        for name, path, _, _ in FIXTURES:
            for item, place in self.places(path):
                with self.subTest(name=name, item=item['id']):
                    target = head_file(path.parent, place['file'])
                    self.assertIsNotNone(target, place['file'])
                    lines = target.read_text(encoding='utf-8').splitlines()
                    first, last = place['lines']
                    self.assertTrue(1 <= first <= last <= len(lines), (place, len(lines)))
                    self.assertTrue(any(line.strip() for line in lines[first - 1:last]))

    def test_the_windows_of_two_items_in_one_file_do_not_overlap(self):
        """Defects and decoys alike: a finding in two windows would be credited to the defect, and a
        correct High on the decoy's own lines would not count as a decoy hit."""
        window = constants.BENCH_WINDOW
        for name, path, _, _ in FIXTURES:
            found = [(item['id'], place['file'], place['lines'][0] - window, place['lines'][1] + window)
                     for kind in ('defects', 'decoys') for item in self.spec(path)[kind]
                     for place in item.get('places', [])]
            for number, (first_id, file, start, end) in enumerate(found):
                for other_id, other_file, other_start, other_end in found[number + 1:]:
                    if file == other_file and first_id != other_id:
                        with self.subTest(name=name, pair=(first_id, other_id)):
                            self.assertTrue(end < other_start or other_end < start)

    def test_a_defect_has_a_place_or_a_rule_and_a_security_defect_has_a_category(self):
        for name, path, _, _ in FIXTURES:
            for item in self.spec(path)['defects']:
                with self.subTest(name=name, item=item['id']):
                    self.assertTrue(item.get('places') or item.get('rule'))
                    if name == 'security':
                        for label in [item['category']] if isinstance(item['category'], str) else item['category']:
                            self.assertIn(label, [known for known, _ in constants.OWASP_2021])

    def test_no_fixture_source_file_can_be_found_by_unittest_discover(self):
        for path in BENCH.rglob('*.py'):
            with self.subTest(path=path.relative_to(BENCH).as_posix()):
                self.assertFalse(path.name.startswith('test'))

    def test_every_python_fixture_file_is_valid_python(self):
        for path in BENCH.rglob('*.py'):
            with self.subTest(path=path.relative_to(BENCH).as_posix()):
                compile(path.read_text(encoding='utf-8'), str(path), 'exec')

    def test_the_security_fixture_plants_no_credential_key_token_or_password(self):
        pattern = re.compile(r'(?i)pass(?:word|wd)|secret|token|api[_-]?key|private[_ -]?key|credential'
                             r'|-----BEGIN|AKIA[0-9A-Z]{8,}|[A-Za-z0-9+/=_-]{32,}')
        for path in sorted((BENCH / 'security').rglob('*')):
            if path.is_file():
                with self.subTest(path=path.relative_to(BENCH).as_posix()):
                    text = path.read_text(encoding='utf-8')
                    self.assertEqual([match.group() for match in pattern.finditer(text)], [])

    def test_the_rules_fixture_has_ten_keep_and_three_drop_rules_and_a_skill_text_over_its_budget(self):
        brief = (BENCH / 'feature' / 'rules' / 'brief.md').read_text(encoding='utf-8')
        verdicts = re.findall(r'^\| (\w+) \| .* \| (keep|drop) \|$', brief, re.M)
        self.assertEqual(sum(1 for _, verdict in verdicts if verdict == 'keep'), 10)
        self.assertEqual(sum(1 for _, verdict in verdicts if verdict == 'drop'), 3)
        budget = int(re.search(r'at most (\d+) bytes', brief).group(1))
        self.assertGreater((BENCH / 'feature' / 'rules' / 'SKILL.md').stat().st_size, budget)

    def test_the_code_fixture_has_two_rules_and_one_seam_owner(self):
        base = BENCH / 'code' / 'base'
        rules = re.findall(r'^- ', (base / 'CLAUDE.md').read_text(encoding='utf-8'), re.M)
        owners = re.findall(r'^- ', (base / 'seams.md').read_text(encoding='utf-8'), re.M)
        self.assertEqual((len(rules), len(owners)), (2, 1))

    def test_the_change_of_the_code_fixture_stays_a_small_diff(self):
        total = sum(len(path.read_text(encoding='utf-8').splitlines())
                    for path in (BENCH / 'code' / 'change').rglob('*') if path.is_file())
        self.assertTrue(150 <= total <= 450, total)

    def test_the_code_fixture_follows_its_own_rule_that_every_new_public_function_has_a_check(self):
        """Only the planted D8 function, fines.overdue_days, has none."""
        root = BENCH / 'code'
        checks = [path.read_text(encoding='utf-8') for tree in ('base', 'change')
                  for path in (root / tree / 'checks').glob('check_*.py')]
        unchecked = []
        for path in sorted((root / 'change' / 'shelf').glob('*.py')):
            for node in ast.walk(ast.parse(path.read_text(encoding='utf-8'))):
                if isinstance(node, ast.FunctionDef) and not node.name.startswith('_'):
                    if not any(re.search(rf'\b{path.stem}\b', text) and re.search(rf'\b{node.name}\b', text)
                               for text in checks):
                        unchecked.append(f'{path.stem}.{node.name}')
        self.assertEqual(unchecked, ['fines.overdue_days'])

    def test_the_cards_decoy_is_correct_code_every_row_of_a_card_is_as_wide_as_its_frame(self):
        book = {'title': 'A Long Title That Does Not Fit In The Frame At All', 'author': 'An Author With A Long Name',
                'shelf': 'B4', 'year': 1999, 'price_cents': 1250, 'pages': 300, 'language': 'en',
                'isbn': '9780000000000', 'copies': 3, 'out': 1, 'late': 0}
        with tempfile.TemporaryDirectory() as tmp:
            for tree in ('base', 'change'):
                shutil.copytree(BENCH / 'code' / tree, tmp, dirs_exist_ok=True)
            sys.path.insert(0, tmp)
            self.addCleanup(sys.path.remove, tmp)
            self.addCleanup(lambda: [sys.modules.pop(name) for name in list(sys.modules) if name.split('.')[0] == 'shelf'])
            from shelf import cards
            rows = cards.render_card(book).splitlines()
        self.assertEqual({len(row) for row in rows}, {cards.WIDTH})

    def test_the_security_change_never_reads_the_session_header_so_no_live_session_id_is_stored_or_logged(self):
        """The session id is a bearer credential: only the auth module of the base reads it. A change
        that stored it would be a real defect nobody planted."""
        for path in sorted((BENCH / 'security' / 'change').rglob('*.py')):
            with self.subTest(path=path.relative_to(BENCH).as_posix()):
                self.assertNotIn('X-Session', path.read_text(encoding='utf-8'))

    def test_the_security_change_reads_no_column_the_notes_table_does_not_get(self):
        """The notes table gets a title and a body only; a query on an owner column would be a
        defect nobody planted."""
        for path in sorted((BENCH / 'security' / 'change').rglob('*.py')):
            with self.subTest(path=path.relative_to(BENCH).as_posix()):
                self.assertNotIn('owner', path.read_text(encoding='utf-8'))

    def test_the_security_decoy_window_holds_no_client_value_and_no_call_the_scorer_would_take_for_it(self):
        """A High on code that merely sits near the decoy must not land on the decoy: the window around
        the placeholder decoy holds neither the webhook call nor a value read from the query."""
        spec = json.loads((BENCH / 'security' / 'defects.json').read_text(encoding='utf-8'))
        decoy = next(item for item in spec['decoys'] if item['id'] == 'Q1')
        place = decoy['places'][0]
        lines = (BENCH / 'security' / 'change' / place['file']).read_text(encoding='utf-8').splitlines()
        window = '\n'.join(lines[max(place['lines'][0] - constants.BENCH_WINDOW - 1, 0):
                                 place['lines'][1] + constants.BENCH_WINDOW])
        self.assertNotIn('webhook', window)
        self.assertNotIn('query[', window)


class DocsFixtureTest(ScoreCase):
    """AC-53: the docs fixture plants one unrecorded decision commit and one drifted ADR claim. It is not a row of
    FIXTURES: the briefed number of decoys is not set, and the decoy checks need at least one. It reuses the
    shared reader, the perfect-run builder and the place resolver."""
    PATH = BENCH / 'docs' / 'defects.json'

    def spec(self):
        self.assertTrue(self.PATH.is_file(), self.PATH.relative_to(BENCH.parent).as_posix())
        return json.loads(self.PATH.read_text(encoding='utf-8'))

    def test_the_fixture_loads_and_plants_two_defects_a_decision_commit_and_a_drifted_adr_claim(self):
        spec = self.spec()
        self.assertEqual(bench.load_fixture(self.PATH).name, 'docs')
        self.assertEqual(spec['fixture'], 'docs')
        self.assertEqual(len(spec['defects']), 2)
        kinds = [('commit' if re.search(r'commit', item['what'], re.I) else
                  'drift' if re.search(r'drift|no longer', item['what'], re.I) else '?')
                 for item in spec['defects']]
        self.assertEqual(sorted(kinds), ['commit', 'drift'])

    def test_each_planted_place_points_at_real_text_and_the_two_windows_do_not_overlap(self):
        window = constants.BENCH_WINDOW
        found = []
        for item in self.spec()['defects']:
            for place in item.get('places', []):
                with self.subTest(item=item['id']):
                    target = head_file(self.PATH.parent, place['file'])
                    self.assertIsNotNone(target, place['file'])
                    lines = target.read_text(encoding='utf-8').splitlines()
                    first, last = place['lines']
                    self.assertTrue(1 <= first <= last <= len(lines), (place, len(lines)))
                    self.assertTrue(any(line.strip() for line in lines[first - 1:last]))
                found.append((item['id'], place['file'], first - window, last + window))
        for number, (first_id, file, start, end) in enumerate(found):
            for other_id, other_file, other_start, other_end in found[number + 1:]:
                if file == other_file and first_id != other_id:
                    self.assertTrue(end < other_start or other_end < start, (first_id, other_id))

    def test_a_run_that_names_both_defects_finds_2_of_2_and_each_defect_alone_finds_1_of_2(self):
        spec = self.spec()
        both = fixture_run(spec)
        result = block(self.score(self.PATH, self.write_run(*both))[1])
        self.assertEqual((result['found'], result['found at min severity'], result['missed'], result['false High']),
                         ('2 of 2', '2 of 2', '0 of 2', '0'))
        for number, line in enumerate(both):
            with self.subTest(defect=spec['defects'][number]['id']):
                alone = block(self.score(self.PATH, self.write_run(line, name=f'alone{number}.txt'))[1])
                self.assertEqual((alone['found'], alone['missed']), ('1 of 2', '1 of 2'))

    def test_a_run_that_names_neither_defect_finds_0_of_2(self):
        self.spec()
        result = block(self.score(self.PATH, self.write_run('fine: nothing to report'))[1])
        self.assertEqual((result['found'], result['missed'], result['false High']), ('0 of 2', '2 of 2', '0'))


if __name__ == '__main__':
    unittest.main()
