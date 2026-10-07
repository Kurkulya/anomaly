import unittest

from shelf.hooks import run_hooks


class RunHooksTest(unittest.TestCase):
    def test_a_failing_hook_does_not_stop_the_next_one(self):
        seen = []

        def broken(event):
            raise RuntimeError('boom')

        failures = run_hooks([broken, seen.append], 'added')
        self.assertEqual(seen, ['added'])
        self.assertEqual([hook for hook, _ in failures], [broken])
