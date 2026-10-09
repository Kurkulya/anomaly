"""Cases of `mr put`, `ready`, `show`, `reviewed` and `verified` that the acceptance tests of ticket 07 (test_mr.py)
leave open: the order and the keeping of the lines of mr.md, and the errors that say what to run first. The fakes
and the fixtures are those of test_mr.py; no test runs `gh` or `glab`."""
from tests.fixtures import assert_cli_error, run_cli
from tests.test_mr import (LINKS, MR_BODY_FILE, ORIGINS, UNIT, AdhocCase, MrCase, PutSetup, write_text)


class StateLinesTest(PutSetup, MrCase):
    ADAPTER = 'gh'
    SHA_A, SHA_B = 'a' * 40, 'b' * 40

    def test_put_keeps_the_gate_lines_and_writes_the_lines_in_the_order_mr_reviewed_verified(self):
        folder = self.unit()
        write_text(folder / 'mr.md', f'Verified: {self.SHA_B}\nReviewed: {self.SHA_A}\n')
        self.assertEqual(self.run_mr('put', folder)[0], 0)
        self.assertEqual(self.mr_md_lines(folder / 'mr.md'),
                         [f'MR: {self.link}', f'Reviewed: {self.SHA_A}', f'Verified: {self.SHA_B}'])

    def test_a_second_reviewed_replaces_the_line_and_leaves_the_others(self):
        folder = self.unit(link=self.link)
        head = self.repo.git('rev-parse', 'HEAD').strip()
        write_text(folder / 'mr.md', f'MR: {self.link}\nReviewed: {self.SHA_A}\nVerified: {self.SHA_B}\n')
        code, out, err = self.run_mr('reviewed', folder, 'HEAD')
        self.assertEqual(code, 0, (out, err))
        self.assertEqual(self.mr_md_lines(folder / 'mr.md'),
                         [f'MR: {self.link}', f'Reviewed: {head}', f'Verified: {self.SHA_B}'])


class WhatToRunFirstTest(PutSetup, MrCase):
    ADAPTER = 'gh'

    def test_ready_and_show_without_an_mr_line_say_to_run_put_first(self):
        folder = self.unit()
        for action in ('ready', 'show'):
            with self.subTest(action=action):
                assert_cli_error(self, self.run_mr(action, folder), 'mr put')
        self.assert_no_tool_call()

    def test_put_without_a_body_file_says_to_run_body_first(self):
        folder = self.repo.root / '.anomaly' / UNIT
        folder.mkdir(parents=True)
        assert_cli_error(self, self.run_mr('put', folder), 'mr body')
        self.assert_no_tool_call()

    def test_put_with_a_body_file_that_has_no_title_line_is_an_error(self):
        folder = self.unit()
        write_text(folder / 'mr-body.md', '## Why\n\nno title here\n')
        assert_cli_error(self, self.run_mr('put', folder), 'Title:')
        self.assert_no_tool_call()

    def test_ready_and_show_on_the_core_default_are_errors_that_call_nothing(self):
        self.set_port('')
        folder = self.unit(link=self.link)
        for action in ('ready', 'show'):
            with self.subTest(action=action):
                assert_cli_error(self, self.run_mr(action, folder), 'core default')
        self.assert_no_tool_call()


class UnusableStateTest(PutSetup, MrCase):
    ADAPTER = 'gh'

    def test_put_on_a_detached_head_is_an_error_and_calls_nothing(self):
        self.repo.git('checkout', '-q', '--detach')
        folder = self.unit()
        assert_cli_error(self, self.run_mr('put', folder), 'detached')
        self.assert_no_tool_call()
        self.assertFalse((folder / 'mr.md').exists())

    def test_an_mr_line_whose_link_has_no_number_is_an_error_for_show_ready_and_put(self):
        folder = self.unit(link='https://example.com/x')
        for action in ('show', 'ready', 'put'):
            with self.subTest(action=action):
                assert_cli_error(self, self.run_mr(action, folder), 'number')
        self.assert_no_tool_call()


class EnvironmentTest(PutSetup, MrCase):
    ADAPTER = 'gh'

    def test_the_environment_of_the_command_reaches_every_adapter_call(self):
        marker = {'ANOMALY_TEST_MARKER': '1'}
        folder = self.unit()
        for action in ('put', 'put', 'show', 'ready'):   # create, update, view, ready
            code, out, err = run_cli('mr', action, str(folder), '--repo', str(self.repo.root), '--home', str(self.home),
                                     environ=marker)
            self.assertEqual(code, 0, (action, out, err))
        self.assertEqual([call.kind for call in self.gh.records], ['create', 'update', 'show', 'ready'])
        self.assertEqual(self.gh.environs, [marker] * 4)


class GlabReadyAnswerTest(PutSetup, MrCase):
    ADAPTER = 'glab'

    def test_a_ready_answer_with_no_mutation_result_is_an_error_not_a_success(self):
        folder = self.unit(link=self.link)
        for answer in ('{"data": {"mergeRequestSetDraft": null}}', '{"data": null}', '{}',
                       '{"data": {"mergeRequestSetDraft": {"errors": ["not allowed"]}}}'):
            with self.subTest(answer=answer):
                self.glab.ready_answer = answer
                code, out, err = self.run_mr('ready', folder)
                self.assertEqual(code, 2, (out, err))
                self.assertNotIn('ready for review', out)


class TargetKindTest(PutSetup, AdhocCase):
    ADAPTER = 'gh'

    def test_reviewed_and_verified_refuse_an_adhoc_ticket_and_name_the_ticket_command(self):
        for action in ('reviewed', 'verified'):
            with self.subTest(action=action):
                assert_cli_error(self, self.run_mr(action, self.ticket, 'HEAD'), f'ticket {action}')
        self.assertFalse(self.ticket.with_name(self.ticket.stem + '.mr.md').exists())

    def test_a_folder_that_is_no_work_unit_folder_is_refused_by_every_action(self):
        elsewhere = self.repo.root / 'docs' / UNIT
        write_text(elsewhere / 'mr-body.md', MR_BODY_FILE)
        for folder in (elsewhere, self.ticket.parent):
            for action in ('body', 'put', 'ready', 'show', 'reviewed'):
                with self.subTest(folder=folder.name, action=action):
                    assert_cli_error(self, self.run_mr(action, folder, *(('HEAD',) if action == 'reviewed' else ())),
                                     'work-unit folder')
        self.assertFalse((elsewhere / 'mr.md').exists())
        self.assert_no_tool_call()


class AdapterHostTest(PutSetup, MrCase):
    def test_each_adapter_refuses_the_origin_of_the_other_and_names_the_host(self):
        for adapter, other in (('gh', 'glab'), ('glab', 'gh')):
            with self.subTest(adapter=adapter):
                self.use(adapter, origin=ORIGINS[other])
                folder = self.unit(link=LINKS[adapter])
                for action in ('put', 'ready', 'show'):
                    assert_cli_error(self, self.run_mr(action, folder), ORIGINS[other].split('@')[1].split(':')[0])
        self.assert_no_tool_call()


class AdhocActionsTest(PutSetup, AdhocCase):
    ADAPTER = 'gh'

    def test_ready_and_show_read_the_sibling_mr_file(self):
        sibling = self.ticket.with_name(self.ticket.stem + '.mr.md')
        write_text(sibling, f'MR: {self.link}\n')
        write_text(self.body_file(), MR_BODY_FILE)
        for action in ('ready', 'show'):
            with self.subTest(action=action):
                code, out, err = self.run_mr(action, self.ticket)
                self.assertEqual(code, 0, (out, err))
                self.assertIn(self.link, out)
        self.assertEqual(len(self.calls('ready')), 1)
