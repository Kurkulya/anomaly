"""Offline tests for the `pkg-facts` command (AC-17 to AC-19, AC-21).

The command is driven through the CLI entry (`run_cli`). Its one network call is the module-level
`pkg_facts.fetch(url)`; the tests replace it with a reader of the files in pkg_facts/ and make an
unknown URL raise, so a wrong URL shows up as a failure. One opt-in live test runs only when LIVE=1
is set.

Fixtures, recorded 2026-10-10 with `curl -s <url>` and trimmed to the fields the command reads
(field names and nesting kept as recorded; the versions lists are cut to a few entries, the
isDefault one kept; the riverpod score is recorded in full, with its license:mit, license:fsf-libre
and license:osi-approved tags). Every host other than the two API hosts was then rewritten to a
host under example.com, in the fixtures and the expected values alike:
  depsdev-npm-zod-package.json   the deps.dev package endpoint for zod
  depsdev-npm-zod-version.json   the deps.dev version endpoint for zod 4.6.5
  depsdev-project-zod.json       the deps.dev project endpoint for the zod repository
  pub-riverpod.json              the pub.dev package endpoint for riverpod
  pub-riverpod-score.json        the pub.dev score endpoint for riverpod
Hand-made (not recorded), with the real field names and nesting, for the cases a recording cannot give:
  depsdev-pypi-handmade-*.json         a second deps.dev system (package "examplepkg")
  depsdev-npm-handmade-norepo-*.json   a version with no SOURCE_REPO related project (package "norepo")
  depsdev-npm-handmade-nokey-package.json   a default version with no versionKey (package "nokey")
  depsdev-npm-handmade-nodefault-package.json   versions with none marked isDefault (package "nodefault")
  pub-handmade-nohomepage-repo*.json   a pubspec with a homepage but no repository (package "homeonly")
  pub-handmade-malformed.json          a package response whose "latest" is null (package "brokenpkg")
  pub-handmade-pipecell*.json          a licence tag with "|" and a repository with a newline (package "pipecell")
  pub-handmade-discontinued*.json      a package endpoint with isDiscontinued: true and replacedBy, as probed
                                       for pedantic on 2026-10-10 (package "pedantic")
  pub-handmade-badflag*.json           isDiscontinued as the string "false", a wrong type (package "badflag")

Standard library only.
"""
import ast
import json
import os
import re
import sys
import tempfile
import unittest
import urllib.request
from pathlib import Path
from unittest import mock

from anomaly_loop import pkg_facts, terms_grep
from tests.fixtures import GitFixture, run_cli

FIXTURES = Path(__file__).resolve().parent / "pkg_facts"

HEADER_NAMES = ["package", "latest version", "date", "licence", "deprecated", "repository",
                "stars", "open issues", "scorecard", "downloads"]
HEADER_LINE = "| " + " | ".join(HEADER_NAMES) + " |"

ZOD_PACKAGE_URL = "https://api.deps.dev/v3/systems/NPM/packages/zod"
ZOD_VERSION_URL = "https://api.deps.dev/v3/systems/NPM/packages/zod/versions/4.6.5"
ZOD_PROJECT_URL = "https://api.deps.dev/v3/projects/github.example.com%2Fcolinhacks%2Fzod"
RIVERPOD_URL = "https://pub.dev/api/packages/riverpod"
RIVERPOD_SCORE_URL = "https://pub.dev/api/packages/riverpod/score"
PYPI_PACKAGE_URL = "https://api.deps.dev/v3/systems/PYPI/packages/examplepkg"
PYPI_VERSION_URL = "https://api.deps.dev/v3/systems/PYPI/packages/examplepkg/versions/1.2.3"
PYPI_PROJECT_URL = "https://api.deps.dev/v3/projects/github.example.com%2Fexample%2Fexamplepkg"
NOREPO_PACKAGE_URL = "https://api.deps.dev/v3/systems/NPM/packages/norepo"
NOREPO_VERSION_URL = "https://api.deps.dev/v3/systems/NPM/packages/norepo/versions/2.0.0"
NOKEY_PACKAGE_URL = "https://api.deps.dev/v3/systems/NPM/packages/nokey"
NODEFAULT_PACKAGE_URL = "https://api.deps.dev/v3/systems/NPM/packages/nodefault"
PIPECELL_URL = "https://pub.dev/api/packages/pipecell"
PIPECELL_SCORE_URL = "https://pub.dev/api/packages/pipecell/score"
HOMEONLY_URL = "https://pub.dev/api/packages/homeonly"
HOMEONLY_SCORE_URL = "https://pub.dev/api/packages/homeonly/score"
BROKEN_URL = "https://pub.dev/api/packages/brokenpkg"
BROKEN_SCORE_URL = "https://pub.dev/api/packages/brokenpkg/score"
PEDANTIC_URL = "https://pub.dev/api/packages/pedantic"
PEDANTIC_SCORE_URL = "https://pub.dev/api/packages/pedantic/score"
BADFLAG_URL = "https://pub.dev/api/packages/badflag"
BADFLAG_SCORE_URL = "https://pub.dev/api/packages/badflag/score"

URL_TO_FIXTURE = {
    ZOD_PACKAGE_URL: "depsdev-npm-zod-package.json",
    ZOD_VERSION_URL: "depsdev-npm-zod-version.json",
    ZOD_PROJECT_URL: "depsdev-project-zod.json",
    RIVERPOD_URL: "pub-riverpod.json",
    RIVERPOD_SCORE_URL: "pub-riverpod-score.json",
    PYPI_PACKAGE_URL: "depsdev-pypi-handmade-package.json",
    PYPI_VERSION_URL: "depsdev-pypi-handmade-version.json",
    PYPI_PROJECT_URL: "depsdev-pypi-handmade-project.json",
    NOREPO_PACKAGE_URL: "depsdev-npm-handmade-norepo-package.json",
    NOREPO_VERSION_URL: "depsdev-npm-handmade-norepo-version.json",
    NOKEY_PACKAGE_URL: "depsdev-npm-handmade-nokey-package.json",
    NODEFAULT_PACKAGE_URL: "depsdev-npm-handmade-nodefault-package.json",
    PIPECELL_URL: "pub-handmade-pipecell.json",
    PIPECELL_SCORE_URL: "pub-handmade-pipecell-score.json",
    HOMEONLY_URL: "pub-handmade-nohomepage-repo.json",
    HOMEONLY_SCORE_URL: "pub-handmade-nohomepage-repo-score.json",
    BROKEN_URL: "pub-handmade-malformed.json",
    BROKEN_SCORE_URL: "pub-riverpod-score.json",
    PEDANTIC_URL: "pub-handmade-discontinued.json",
    PEDANTIC_SCORE_URL: "pub-handmade-discontinued-score.json",
    BADFLAG_URL: "pub-handmade-badflag.json",
    BADFLAG_SCORE_URL: "pub-handmade-badflag-score.json",
}

# The values the recorded fixtures hold, per column, in header order after "package".
ZOD_VALUES = ["4.6.5", "2026-09-13", "MIT", "no", "github.example.com/colinhacks/zod", "44064", "86", "5.1", "Unknown"]
RIVERPOD_VALUES = ["3.4.3", "2026-09-03", "mit", "Unknown", "https://github.example.com/rrousselGit/riverpod",
                   "Unknown", "Unknown", "Unknown", "3647805"]
PYPI_VALUES = ["1.2.3", "2024-05-06", "Apache-2.0, MIT", "yes", "github.example.com/example/examplepkg",
               "1234", "7", "7.5", "Unknown"]
NOREPO_VALUES = ["2.0.0", "2025-03-04", "ISC", "no", "Unknown", "Unknown", "Unknown", "Unknown", "Unknown"]
HOMEONLY_VALUES = ["1.0.0", "2025-02-03", "bsd-3-clause", "Unknown", "Unknown", "Unknown", "Unknown", "Unknown", "42"]
PEDANTIC_VALUES = ["1.11.1", "2021-08-09", "bsd-3-clause", "yes", "https://github.example.com/dart-lang/pedantic",
                   "Unknown", "Unknown", "Unknown", "99"]
ALL_UNKNOWN = ["Unknown"] * 9


def fixture_fetch(calls=None, fail=()):
    """A `fetch` that reads the fixture mapped to the URL, raises for a URL in `fail` or an unknown URL."""
    def fetch(url):
        if calls is not None:
            calls.append(url)
        if url in fail:
            raise OSError(f"simulated network failure for {url}")
        if url not in URL_TO_FIXTURE:
            raise AssertionError(f"unexpected URL: {url}")
        return (FIXTURES / URL_TO_FIXTURE[url]).read_bytes()
    return fetch


def crafted_fetch(package):
    """A `fetch` that answers the pub.dev package endpoint of "crafted" with `package` (built in the
    test, as JSON) and its score endpoint with no tags."""
    responses = {"https://pub.dev/api/packages/crafted": json.dumps(package).encode("utf-8"),
                 "https://pub.dev/api/packages/crafted/score": b'{"tags": []}'}
    return responses.__getitem__


def table_rows(stdout):
    """The data rows of the markdown table: a list of cell lists (package first). Checks header and separator."""
    lines = [ln.strip() for ln in stdout.splitlines() if ln.strip().startswith("|")]
    assert lines, f"no markdown table in stdout: {stdout!r}"
    assert lines[0] == HEADER_LINE, f"header differs: {lines[0]!r}"
    assert re.fullmatch(r"\|(\s*:?-{3,}:?\s*\|){10}", lines[1]), f"separator row differs: {lines[1]!r}"
    return [[cell.strip() for cell in ln.strip("|").split("|")] for ln in lines[2:]]


class CommandTestCase(unittest.TestCase):
    def run_main(self, argv, fetch=None):
        """`anomaly pkg-facts` through the CLI with `fetch` replaced; returns (exit code, stdout, stderr)."""
        with mock.patch.object(pkg_facts, "fetch", fetch or fixture_fetch()):
            return run_cli("pkg-facts", *argv)

    def folder_with(self, *manifests):
        """A temporary folder (outside git) holding these empty manifest files; returns its path."""
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        for name in manifests:
            Path(folder.name, name).write_text("", encoding="utf-8")
        return Path(folder.name)

    def chdir(self, path):
        previous = os.getcwd()
        os.chdir(path)
        self.addCleanup(os.chdir, previous)

    def assert_one_anomaly_line(self, result):
        """AC-19: exit 2, nothing on stdout, one `anomaly:` line on stderr."""
        code, out, err = result
        self.assertEqual((code, out), (2, ""))
        self.assertTrue(err.startswith("anomaly: "), err)
        self.assertEqual(len(err.splitlines()), 1, err)


class TableTests(CommandTestCase):
    def test_two_packages_print_header_and_one_row_each(self):
        # AC-17: table shape and order; deps.dev npm values; pub values (licence from the license: tag);
        # Unknown cells
        code, out, _ = self.run_main(["npm:zod", "pub:riverpod"])
        self.assertEqual(code, 0)
        self.assertEqual(table_rows(out), [["npm:zod"] + ZOD_VALUES, ["pub:riverpod"] + RIVERPOD_VALUES])

    def test_pub_repository_has_no_homepage_fallback(self):
        code, out, _ = self.run_main(["pub:homeonly"])
        self.assertEqual(code, 0)
        self.assertEqual(table_rows(out), [["pub:homeonly"] + HOMEONLY_VALUES])

    def test_pub_discontinued_package_fills_deprecated_with_yes(self):
        # isDiscontinued: true -> "yes" (the deps.dev rendering)
        code, out, _ = self.run_main(["pub:pedantic"])
        self.assertEqual(code, 0)
        self.assertEqual(table_rows(out), [["pub:pedantic"] + PEDANTIC_VALUES])

    def test_pipe_and_newline_in_a_cell_keep_the_row_one_line_of_ten_cells(self):
        code, out, _ = self.run_main(["pub:pipecell"])
        self.assertEqual(code, 0)
        lines = [ln for ln in out.splitlines() if ln.startswith("|")]
        self.assertEqual(len(lines), 3)
        cells = re.split(r"(?<!\\)\|", lines[2])[1:-1]
        self.assertEqual(len(cells), len(HEADER_NAMES))
        self.assertEqual([cell.strip() for cell in cells][3:6],
                         [r"mit\|apache", "Unknown", "https://example.com/line1 line2"])

    def test_version_without_source_repo_leaves_project_columns_unknown(self):
        calls = []
        code, out, _ = self.run_main(["npm:norepo"], fixture_fetch(calls))
        self.assertEqual(code, 0)
        self.assertEqual(table_rows(out), [["npm:norepo"] + NOREPO_VALUES])
        self.assertEqual([url for url in calls if "/projects/" in url], [])

    def test_another_deps_dev_system_builds_its_own_urls(self):
        calls = []
        code, out, _ = self.run_main(["pypi:examplepkg"], fixture_fetch(calls))
        self.assertEqual(code, 0)
        self.assertEqual(table_rows(out), [["pypi:examplepkg"] + PYPI_VALUES])
        self.assertEqual(set(calls), {PYPI_PACKAGE_URL, PYPI_VERSION_URL, PYPI_PROJECT_URL})

    def test_a_control_character_in_a_cell_prints_as_a_question_mark(self):
        package = {"latest": {"version": "1.0.0", "pubspec": {"repository": "https://example.com/a\x1bb"}}}
        code, out, _ = self.run_main(["pub:crafted"], crafted_fetch(package))
        self.assertEqual(code, 0)
        self.assertEqual(table_rows(out)[0][5], "https://example.com/a?b")
        self.assertNotIn("\x1b", out)

    def test_a_lone_surrogate_prints_as_a_question_mark_in_the_table_and_in_json(self):
        fetch = crafted_fetch({"latest": {"version": "1.0\ud800"}})
        code, out, _ = self.run_main(["pub:crafted"], fetch)
        self.assertEqual((code, table_rows(out)[0][1]), (0, "1.0?"))
        code, out, _ = self.run_main(["--json", "pub:crafted"], fetch)
        self.assertEqual((code, json.loads(out)[0]["latest version"]), (0, "1.0?"))

    def test_json_prints_the_same_rows_as_a_list_of_objects(self):
        # AC-17: --json
        code, out, _ = self.run_main(["--json", "npm:zod", "pub:riverpod"])
        self.assertEqual(code, 0)
        rows = json.loads(out)
        self.assertIsInstance(rows, list)
        self.assertEqual(len(rows), 2)
        for row in rows:
            self.assertEqual(list(row.keys()), HEADER_NAMES)
        expected = [["npm:zod"] + ZOD_VALUES, ["pub:riverpod"] + RIVERPOD_VALUES]
        self.assertEqual([list(row.values()) for row in rows], expected)


class EcosystemFromManifestTests(CommandTestCase):
    def test_one_manifest_in_repo_gives_the_ecosystem(self):
        # AC-18
        folder = self.folder_with("package.json")
        code, out, _ = self.run_main(["zod", "--repo", str(folder)])
        self.assertEqual(code, 0)
        self.assertEqual(table_rows(out), [["zod"] + ZOD_VALUES])

    def test_pyproject_and_requirements_are_one_ecosystem(self):
        folder = self.folder_with("pyproject.toml", "requirements.txt")
        code, out, _ = self.run_main(["examplepkg", "--repo", str(folder)])
        self.assertEqual(code, 0)
        self.assertEqual(table_rows(out), [["examplepkg"] + PYPI_VALUES])

    def test_without_repo_the_working_folder_is_read(self):
        # AC-18: the default is the working folder
        self.chdir(self.folder_with("pubspec.yaml"))
        code, out, _ = self.run_main(["riverpod"])
        self.assertEqual(code, 0)
        self.assertEqual(table_rows(out), [["riverpod"] + RIVERPOD_VALUES])

    def test_repo_is_taken_as_given_a_subfolder_reads_its_own_manifests(self):
        # AC-18, D-26 Amended: never a jump to the git top; the top holds package.json (npm), the
        # subfolder pubspec.yaml (pub)
        with tempfile.TemporaryDirectory() as tmp:
            repo = GitFixture(Path(tmp) / "repo")
            repo.write("package.json", "")
            repo.write("app/pubspec.yaml", "")
            code, out, _ = self.run_main(["riverpod", "--repo", str(repo.root / "app")])
        self.assertEqual(code, 0)
        self.assertEqual(table_rows(out), [["riverpod"] + RIVERPOD_VALUES])

    def test_a_prefix_needs_no_manifest(self):
        folder = self.folder_with()
        code, out, _ = self.run_main(["pub:riverpod", "--repo", str(folder)])
        self.assertEqual(code, 0)
        self.assertEqual(table_rows(out), [["pub:riverpod"] + RIVERPOD_VALUES])


class BadInputTests(CommandTestCase):
    """AC-19: bad input is one `anomaly:` line and exit 2, before anything is fetched."""

    def test_no_manifest_names_the_missing_prefix(self):
        calls = []
        folder = self.folder_with()
        result = self.run_main(["zod", "--repo", str(folder)], fixture_fetch(calls))
        self.assert_one_anomaly_line(result)
        self.assertIn("zod", result[2])
        self.assertIn("prefix", result[2])
        self.assertEqual(calls, [])

    def test_manifests_of_two_ecosystems_are_refused(self):
        calls = []
        folder = self.folder_with("package.json", "pubspec.yaml")
        result = self.run_main(["zod", "--repo", str(folder)], fixture_fetch(calls))
        self.assert_one_anomaly_line(result)
        self.assertIn("zod", result[2])
        self.assertIn("prefix", result[2])
        self.assertEqual(calls, [])

    def test_dot_and_dot_dot_are_not_package_names(self):
        for given in ("npm:..", "pub:."):
            with self.subTest(given=given):
                calls = []
                result = self.run_main([given], fixture_fetch(calls))
                self.assert_one_anomaly_line(result)
                self.assertIn(given, result[2])
                self.assertEqual(calls, [])

    def test_every_bad_name_is_named_on_the_one_line(self):
        result = self.run_main(["npm:..", "pub:."])
        self.assert_one_anomaly_line(result)
        self.assertIn("npm:..", result[2])
        self.assertIn("pub:.", result[2])


class FakeResponse:
    """What urlopen returns: a context manager whose read(amount) gives at most `amount` bytes of `body`."""
    def __init__(self, body):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self, amount=-1):
        return self.body if amount is None or amount < 0 else self.body[:amount]


class FailureTests(CommandTestCase):
    """AC-19: a failed fetch or a missing adapter is exit 1, with the rows still printed."""

    def test_ecosystem_without_adapter_prints_no_adapter_and_exits_1(self):
        code, out, _ = self.run_main(["gem:rails"])
        self.assertEqual(code, 1)
        self.assertIn("no adapter: gem", out)

    def test_failed_fetch_prints_fetch_failed_with_unknown_columns_and_exits_1(self):
        fetch = fixture_fetch(fail={ZOD_PACKAGE_URL})
        code, out, _ = self.run_main(["npm:zod", "pub:riverpod"], fetch)
        self.assertEqual(code, 1)
        self.assertRegex(out, r"FETCH FAILED.*npm:zod|npm:zod.*FETCH FAILED")
        self.assertEqual(table_rows(out), [["npm:zod"] + ALL_UNKNOWN, ["pub:riverpod"] + RIVERPOD_VALUES])

    def test_malformed_response_is_treated_as_a_failed_fetch(self):
        code, out, _ = self.run_main(["pub:brokenpkg", "npm:zod"])
        self.assertEqual(code, 1)
        self.assertRegex(out, r"FETCH FAILED.*pub:brokenpkg|pub:brokenpkg.*FETCH FAILED")
        self.assertEqual(table_rows(out), [["pub:brokenpkg"] + ALL_UNKNOWN, ["npm:zod"] + ZOD_VALUES])

    def test_pub_discontinued_flag_of_the_wrong_type_is_a_failed_fetch(self):
        # isDiscontinued is the string "false", not a bool: a wrong type is a FETCH FAILED, not "yes"
        code, out, _ = self.run_main(["pub:badflag", "npm:zod"])
        self.assertEqual(code, 1)
        self.assertRegex(out, r"FETCH FAILED.*pub:badflag|pub:badflag.*FETCH FAILED")
        self.assertEqual(table_rows(out), [["pub:badflag"] + ALL_UNKNOWN, ["npm:zod"] + ZOD_VALUES])

    def test_response_at_the_five_megabyte_cap_is_a_failed_fetch(self):
        # The cap sits inside the real `fetch`, below the seam the other tests replace, so this test
        # keeps the real `fetch` and replaces urllib's urlopen. Every body is valid JSON.
        cap = 5 * 1024 * 1024
        head, tail = b'{"latest": {}, "pad": "', b'"}'

        def padded(size):
            return head + b"x" * (size - len(head) - len(tail)) + tail

        for body, expected_code in ((padded(cap + 1), 1), (padded(cap), 1), (padded(cap - 1), 0)):
            with self.subTest(size=len(body)):
                with mock.patch.object(urllib.request, "urlopen", lambda *a, **k: FakeResponse(body)):
                    code, out, _ = self.run_main(["pub:riverpod"], pkg_facts.fetch)
                self.assertEqual(code, expected_code)
                self.assertEqual("FETCH FAILED" in out, expected_code == 1)

    def test_default_version_without_version_key_is_a_failed_fetch(self):
        code, out, _ = self.run_main(["npm:nokey"])
        self.assertEqual(code, 1)
        self.assertRegex(out, r"FETCH FAILED.*npm:nokey|npm:nokey.*FETCH FAILED")
        self.assertEqual(table_rows(out), [["npm:nokey"] + ALL_UNKNOWN])

    def test_package_without_a_default_version_is_a_failed_fetch(self):
        code, out, _ = self.run_main(["npm:nodefault"])
        self.assertEqual(code, 1)
        self.assertIn("no default version", out)
        self.assertEqual(table_rows(out), [["npm:nodefault"] + ALL_UNKNOWN])

    def test_json_keeps_the_fetch_failed_note_on_stderr_only(self):
        fetch = fixture_fetch(fail={ZOD_PACKAGE_URL})
        code, out, err = self.run_main(["--json", "npm:zod"], fetch)
        self.assertEqual(code, 1)
        self.assertIn("FETCH FAILED", err)
        self.assertNotIn("FETCH FAILED", out)
        self.assertEqual(list(json.loads(out)[0].values()), ["npm:zod"] + ALL_UNKNOWN)


class StandardLibraryTests(unittest.TestCase):
    def test_both_modules_import_only_the_standard_library(self):
        # AC-21: a relative import (level > 0) names a sibling of the package, not a third-party one
        for module in (pkg_facts, terms_grep):
            with self.subTest(module=module.__name__):
                tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
                modules = set()
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        modules.update(alias.name.split(".")[0] for alias in node.names)
                    elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                        modules.add(node.module.split(".")[0])
                self.assertTrue(modules, "the module imports nothing: expected at least urllib")
                self.assertEqual(sorted(modules - set(sys.stdlib_module_names)), [])


@unittest.skipUnless(os.environ.get("LIVE") == "1", "set LIVE=1 to run the live network check")
class LiveTests(unittest.TestCase):
    def test_live_npm_zod_has_a_latest_version(self):
        code, out, err = run_cli("pkg-facts", "npm:zod")
        self.assertEqual(code, 0, err)
        rows = table_rows(out)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][0], "npm:zod")
        self.assertNotEqual(rows[0][1], "Unknown")
        self.assertRegex(rows[0][1], r"^\d+\.\d+")


if __name__ == "__main__":
    unittest.main()
