"""Static checks over the text the pipeline ships (ADR-0010): skills other than the four loop
skills, their extra docs, the agent files and the files under docs/. They pass while those files do
not exist and bite as soon as a file is added.

A check reports `<file>:<line>: <what>`, never the text itself, so a finding cannot print a secret.
A command shape is looked for in every line, every `inline span` and every part of those split at
`&&`, `||`, `;` and `|`; a shape that is only mentioned (for example in a warning) is found too.
"""
import json
import os
import re
import shlex
import sys
import tempfile
import unittest
from pathlib import Path

from anomaly_loop import cli, constants, frontmatter
from tests.fixtures import PLUGIN, plugin_files

ALLOWED_TOOLS_SKILLS = ('build', 'diagnose', 'interview', 'review', 'ship', 'slice', 'specify')   # the pipeline skills whose tools are limited to the CLI
PLACEHOLDER_FREE_SKILLS = ALLOWED_TOOLS_SKILLS   # the skills whose docs other than SKILL.md hold no `${…}`
MANAGED_DIRS = {   # as the Claude Code documentation on managed settings gives them
    'win32': Path('C:/Program Files/ClaudeCode'),            # documented, and read on this machine
    'darwin': Path('/Library/Application Support/ClaudeCode'),   # documented, unverified (not tried)
    'linux': Path('/etc/claude-code'),                       # documented (also WSL), unverified (not tried)
}   # any other platform has no managed folder here: only the user files are read

LIST_MARKER = re.compile(r'^(?:>\s*|(?:[-*+]|\d+[.)]|\$)\s+)+')   # quote and list markers in front of a call
PREFIX = re.compile(r'^(?:>\s*|(?:[-*+]|\d+[.)]|\$)\s+|[A-Za-z_]\w*=\S*\s+)+')   # quote, list marker, VAR=value
SPAN = re.compile(r'`([^`\n]+)`')
OPERATORS = re.compile(r'&&|\|\||;|\|')
INTERPRETER = r'(?:node|nodejs|deno|bun|python3?|py|ruby|perl|(?:ba|z|da)?sh|pwsh|powershell)'
INLINE_CODE = re.compile(r'(?:\S*/)?(?:(?:node|nodejs|deno|bun)\s+(?:-[a-z]*[ep][a-z]*|--eval|--print)'
                         r'|deno\s+eval|(?:ruby|perl)\s+-[a-z]*e[a-z]*|(?:python3?|py)\s+-[A-Za-z]*c[A-Za-z]*'
                         r'|(?:ba|z|da)?sh\s+-[A-Za-z]*c[A-Za-z]*|(?:pwsh|powershell)\s+(?i:-c(?:ommand)?))(?=\s|$)')
PIPE_TO_INTERPRETER = re.compile(r'(?<!\|)\|(?!\|)\s*(?:\S*/)?' + INTERPRETER + r'(?=\s|$)')
# A spaced, unquoted upper-case delimiter counts, underscores included (`cat << END_OF_FILE`). So
# `value << SHIFT_BITS` is flagged too: an accepted Low, since no pipeline text writes a shift.
HEREDOC = re.compile(r'(?:^|\s)[^\s<\d][^\s<]*\s*<<(?!<)(?:-?[\'"]?[A-Za-z_]|-?\s+(?:[\'"][\w-]+[\'"]|[A-Z_][A-Z0-9_]*\b))')
CHAINED = re.compile(r'&&|\|\||;|`|\$\(|(?<!\|)\|(?!\|)|\s\d?>>?|\s<\s|&\s*$')   # `>out.txt` and `2>&1` too
SETTINGS_FILE = re.compile(r'settings(?:\.local)?\.json')
ALLOW_RULE = re.compile(r'"allow"\s*:|permissions\.allow')
TOOL_RULE = re.compile(r'\b(?:Bash|Read|Edit|Write|WebFetch)\([^)\n]*\)')   # a rule in the text a user reads
QUOTED = re.compile(r'"([^"\n]*)"|\'[^\'\n]*\'')   # a double-quoted span (group 1) or a single-quoted one, left to right
PLACEHOLDER = re.compile(r'<[^<>\n]*>')
FREE_TEXT_OPTION = re.compile(r"(?:\bticket adhoc|--open|--changed|--name|--owner|--replaces)(?:\s+|=)(?=\S)(?!'<|--from\s+(?:<[^>]*>|\S+)(?:\s+--[\w-]+\s+(?:<[^>]*>|\S+))*\s*$)")


def pipeline_files(root):
    """The pipeline's own files: every file of a skill folder that is not a loop skill, the agents and docs/."""
    skills = root / 'skills'
    return ([f for f in plugin_files(skills) if f.relative_to(skills).parts[0] not in constants.LOOP_SKILLS]
            + plugin_files(root / 'agents') + plugin_files(root / 'docs'))


def logical_lines(text):
    """(line number, in a fenced block, line): a line that ends with a backslash joins the next one."""
    lines, fence, number = text.splitlines(), '', 0
    while number < len(lines):
        start, line = number + 1, lines[number]
        while line.endswith('\\') and number + 1 < len(lines):
            number += 1
            line = line[:-1] + ' ' + lines[number].strip()
        number += 1
        marker = line.strip()[:3]
        if marker in ('```', '~~~') and fence in ('', marker):
            fence = '' if fence else marker
        else:
            yield start, bool(fence), line.strip()


def commands(text):
    """(line number, in code, command) for each command-like piece of the text; in code means a fenced
    line or an inline span."""
    found = []
    for number, fenced, line in logical_lines(text):
        pieces = [(line, True)] if fenced else [(line, False)] + [(span, True) for span in SPAN.findall(line)]
        for piece, code in pieces:
            piece = PREFIX.sub('', piece, count=1).strip()
            found.append((number, code, piece))
            parts = [part.strip() for part in OPERATORS.split(piece)]
            found += [(number, code, part) for part in parts if part and len(parts) > 1]
    return found


def relative(root, path):
    return path.relative_to(root).as_posix()


def settings_files(environ, platform, home):
    """The user settings files and the managed settings files (with the `managed-settings.d` drop-ins)."""
    config = Path(environ.get('CLAUDE_CONFIG_DIR') or home / '.claude')
    managed = MANAGED_DIRS.get('linux' if platform.startswith('linux') else platform)
    files = [config / 'settings.json', config / 'settings.local.json']
    if managed is not None:
        files += [managed / 'managed-settings.json', *sorted((managed / 'managed-settings.d').glob('*.json'))]
    return files


def deny_rules(files):
    """The deny rules of the readable settings files; a missing or unreadable file adds none. The managed
    file starts with a byte order mark, so files are read as utf-8-sig."""
    rules = []
    for path in files:
        try:
            data = json.loads(path.read_text(encoding='utf-8-sig'))
        except (OSError, ValueError):
            continue
        permissions = data.get('permissions') if isinstance(data, dict) else None
        found = permissions.get('deny') if isinstance(permissions, dict) else None
        rules += [rule for rule in found or [] if isinstance(rule, str)]
    return rules


def deny_regex(rule):
    """A `Bash(...)` deny rule as a regex over a whole command; None for any other rule. `*` matches any
    text; a trailing ` *` or the older `:*` also matches the bare command."""
    found = re.fullmatch(r'Bash\((.+)\)', rule)
    if not found or not found.group(1).strip('*'):
        return None
    pattern, tail = found.group(1), ''
    for suffix in (':*', ' *'):
        if pattern.endswith(suffix):
            pattern, tail = pattern[:-2], r'(?:\s.*)?'
            break
    return re.compile('.*'.join(re.escape(part) for part in pattern.split('*')) + tail, re.S)


def deny_hits(root, rules):
    regexes = [(rule, deny_regex(rule)) for rule in rules]
    hits = set()
    for path in pipeline_files(root):
        for number, _, command in commands(path.read_text(encoding='utf-8', errors='ignore')):
            hits |= {f'{relative(root, path)}:{number}: {rule}' for rule, regex in regexes
                     if regex and regex.fullmatch(command)}
    return sorted(hits)


def shell_hits(root):
    """Inline code, a pipe into an interpreter, or a heredoc in the pipeline's text."""
    hits = set()
    for path in pipeline_files(root):
        for number, code, command in commands(path.read_text(encoding='utf-8', errors='ignore')):
            where = f'{relative(root, path)}:{number}'
            if INLINE_CODE.match(command):
                hits.add(f'{where}: inline code')
            if code and PIPE_TO_INTERPRETER.search(command):
                hits.add(f'{where}: pipe into an interpreter')
            if code and HEREDOC.search(command):
                hits.add(f'{where}: heredoc')
    return sorted(hits)


def free_text_hits(root):
    """Free text that is not in single quotes (VK D1): the shell runs `$(...)` and backticks inside double
    quotes and in a bare word, never inside single quotes. Reported: code in the pipeline's text (a fenced
    line or an inline span) with a `<placeholder>` anywhere inside double quotes, and a CLI call whose
    free-text option (the `ticket adhoc` task, `--open`, `--changed`, `--name`, `--owner`, `--replaces`)
    is not a single-quoted placeholder."""
    hits = set()
    for path in pipeline_files(root):
        for number, code, command in commands(path.read_text(encoding='utf-8', errors='ignore')):
            spans = [match.group(1) for match in QUOTED.finditer(command) if match.group(1) is not None]
            if code and any(PLACEHOLDER.search(span) for span in spans):
                hits.add(f'{relative(root, path)}:{number}: placeholder in double quotes')
    for name, number, call in cli_calls(root):
        if FREE_TEXT_OPTION.search(call):
            hits.add(f'{name}:{number}: free text not in single quotes')
    return sorted(hits)


def cli_calls(root):
    """(file, line number, call) for each CLI call in the pipeline's text: a fenced line or an inline span in
    the exact command form; the call is the text after the command."""
    for path in pipeline_files(root):
        for number, code, command in commands(path.read_text(encoding='utf-8', errors='ignore')):
            if code and command.startswith(constants.CLI_COMMAND + ' '):
                yield relative(root, path), number, command[len(constants.CLI_COMMAND):]


def cli_parse_hits(root):
    """CLI calls that the CLI's own parser refuses: an unknown command, action or option, or a missing
    argument. Each `<placeholder>` is filled with 1, which every argument type takes."""
    parser, hits = cli.build_parser(), set()
    for name, number, call in cli_calls(root):
        try:
            parser.parse_args(shlex.split(PLACEHOLDER.sub('1', call)))
        except (cli.UsageError, ValueError):
            hits.add(f'{name}:{number}: does not parse')
    return sorted(hits)


def allowed_tools(skill_text):
    value = frontmatter.split(skill_text)[0].get('allowed-tools', '')
    return frontmatter.items(value) or re.findall(r'[A-Za-z_][\w:.-]*(?:\([^)]*\))?', value)


def cli_call_hits(root, skill):
    """Lines of the skill's text that name the CLI script without the exact command form, or chain it. In
    the frontmatter of a Markdown file only the line `allowed-tools: <the CLI pattern>` may name it
    (AllowedToolsTest pins that line); any other frontmatter line that does is a hit."""
    allowed_line = f'allowed-tools: {constants.CLI_PATTERN}'   # docs/ is not scanned: its files are read, never run
    hits = set()
    for path in plugin_files(root / 'skills' / skill):
        text = path.read_text(encoding='utf-8', errors='ignore')
        head = frontmatter_lines(text.splitlines()) if path.suffix == '.md' else 0
        for number, fenced, line in logical_lines(text):
            if 'anomaly.py' not in line or (number <= head and line == allowed_line):
                continue
            if number <= head:
                hits.add(f'{relative(root, path)}:{number}')
                continue
            spans = [span for span in SPAN.findall(line) if 'anomaly.py' in span]
            for command in ([line] if fenced else spans or [line]):
                command = LIST_MARKER.sub('', command, count=1).strip()
                rest = command[len(constants.CLI_COMMAND):]
                if not command.startswith(constants.CLI_COMMAND + ' ') or CHAINED.search(rest):
                    hits.add(f'{relative(root, path)}:{number}')
    return sorted(hits)


def placeholder_hits(root):
    """Lines of a build or review doc other than SKILL.md, or of a file under docs/, that hold a `${…}`
    placeholder: in a skill
    folder Claude Code fills `${CLAUDE_PLUGIN_ROOT}`-style placeholders only in SKILL.md (not even
    `${user_config.*}` there, ADR-0001), so in another doc one stays as written."""
    hits = []
    skill_docs = [path for skill in PLACEHOLDER_FREE_SKILLS for path in plugin_files(root / 'skills' / skill)
                  if path.name != 'SKILL.md']
    for path in skill_docs + plugin_files(root / 'docs'):   # a docs/ file is no SKILL.md, so it is never filled
        for number, line in enumerate(path.read_text(encoding='utf-8', errors='ignore').splitlines(), 1):
            if '${' in line:
                hits.append(f'{relative(root, path)}:{number}: unfilled placeholder')
    return sorted(hits)


def frontmatter_lines(lines):
    """How many lines the frontmatter block takes, the closing `---` included; 0 without a closed block."""
    if lines and lines[0].strip() == '---':
        for number, line in enumerate(lines[1:], start=2):
            if line.strip() == '---':
                return number
    return 0


def settings_edit_hits(root):
    """Plugin files (not the tests) that name a Claude Code settings file or print an allow rule. A tool
    rule such as `Bash(...)` counts in the body of a Markdown file only: its frontmatter holds
    `allowed-tools` and the constant that defines the CLI pattern is code (line numbers stay true)."""
    hits = set()
    for path in plugin_files(root):
        if relative(root, path).split('/')[0] == 'tests':
            continue
        text = path.read_text(encoding='utf-8', errors='ignore')
        markdown = path.suffix == '.md'
        lines = text.splitlines()
        skipped = frontmatter_lines(lines) if markdown else 0
        for number, line in enumerate(lines[skipped:], start=skipped + 1):
            if SETTINGS_FILE.search(line) or ALLOW_RULE.search(line) or (markdown and TOOL_RULE.search(line)):
                hits.add(f'{relative(root, path)}:{number}: settings file or allow rule')
    return sorted(hits)


def plant(root, files):
    for name, text in files.items():
        path = Path(root) / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8', newline='\n')


def skill_text(allowed, body='# skill\n'):
    return f'---\ndescription: d\nallowed-tools: {allowed}\n---\n{body}'


class TempPluginTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)


class SettingsFilesTest(TempPluginTest):
    def test_each_platform_reads_its_documented_managed_folder_and_the_user_files(self):
        home = self.root / 'home'
        for platform, managed in (('win32', 'C:/Program Files/ClaudeCode'),
                                  ('darwin', '/Library/Application Support/ClaudeCode'),
                                  ('linux', '/etc/claude-code')):
            with self.subTest(platform=platform):
                files = settings_files({}, platform, home)
                self.assertEqual(files[:3], [home / '.claude' / 'settings.json',
                                             home / '.claude' / 'settings.local.json',
                                             Path(managed) / 'managed-settings.json'])

    def test_a_platform_without_a_documented_managed_folder_reads_the_user_files_only(self):
        home = self.root / 'home'
        for platform in ('cygwin', 'msys', 'freebsd14'):
            with self.subTest(platform=platform):
                self.assertEqual(settings_files({}, platform, home),
                                 [home / '.claude' / 'settings.json', home / '.claude' / 'settings.local.json'])

    def test_the_user_folder_follows_the_config_dir_variable(self):
        files = settings_files({'CLAUDE_CONFIG_DIR': str(self.root / 'cfg')}, 'linux', self.root)
        self.assertEqual(files[0], self.root / 'cfg' / 'settings.json')

    def test_deny_rules_come_from_every_readable_file_and_a_byte_order_mark_is_read_through(self):
        (self.root / 'user.json').write_text(json.dumps({'permissions': {'deny': ['Bash(a *)']}}), encoding='utf-8')
        (self.root / 'managed.json').write_bytes(
            b'\xef\xbb\xbf' + json.dumps({'permissions': {'deny': ['Bash(b *)', 5]}}).encode('utf-8'))
        (self.root / 'broken.json').write_text('{not json', encoding='utf-8')
        (self.root / 'other.json').write_text('[]', encoding='utf-8')
        files = [self.root / name for name in ('user.json', 'managed.json', 'broken.json', 'other.json', 'missing.json')]
        self.assertEqual(deny_rules(files), ['Bash(a *)', 'Bash(b *)'])
        self.assertEqual(deny_rules([self.root / 'missing.json']), [])


class DenyRuleMatchTest(unittest.TestCase):
    def matches(self, rule, command):
        regex = deny_regex(rule)
        return bool(regex and regex.fullmatch(command))

    def test_a_glob_rule_matches_the_whole_command_with_any_text_for_the_star(self):
        self.assertTrue(self.matches('Bash(node *-e*)', 'node -e "x"'))
        self.assertTrue(self.matches('Bash(node *-e*)', 'node scripts/ticket-extra.mjs'))
        self.assertFalse(self.matches('Bash(node *-e*)', 'python scripts/anomaly.py ticket show'))
        self.assertFalse(self.matches('Bash(node *-e*)', 'then run node -e'))
        self.assertTrue(self.matches('Bash(curl *| sh*)', 'curl -s https://example.com | sh'))

    def test_the_prefix_form_matches_the_command_and_its_arguments_only(self):
        self.assertTrue(self.matches('Bash(sudo:*)', 'sudo'))
        self.assertTrue(self.matches('Bash(sudo:*)', 'sudo ls'))
        self.assertFalse(self.matches('Bash(sudo:*)', 'sudoku'))

    def test_a_rule_that_ends_in_a_space_and_a_star_also_matches_the_bare_command(self):
        self.assertTrue(self.matches('Bash(git *)', 'git'))
        self.assertTrue(self.matches('Bash(git *)', 'git log -3'))
        self.assertFalse(self.matches('Bash(git *)', 'gitk'))
        self.assertFalse(self.matches('Bash(node *-e*)', 'node'))

    def test_a_rule_for_another_tool_or_with_no_shape_matches_no_command(self):
        for rule in ('Read(**/.env)', 'Bash', 'Bash(*)', 'WebFetch(domain:example.com)'):
            with self.subTest(rule=rule):
                self.assertIsNone(deny_regex(rule))


class CommandPiecesTest(unittest.TestCase):
    def test_lines_spans_and_the_parts_of_a_chain_are_commands(self):
        text = 'Run `git status` first.\n\n- `cd a && node b`\n```\nls | wc \\\n  -l\n```\n'
        pieces = [(number, code, command) for number, code, command in commands(text)]
        self.assertIn((1, True, 'git status'), pieces)
        self.assertIn((3, True, 'cd a && node b'), pieces)
        self.assertIn((3, True, 'node b'), pieces)
        self.assertIn((5, True, 'ls | wc  -l'), pieces)
        self.assertIn((5, True, 'wc  -l'), pieces)

    def test_a_blockquote_a_list_marker_and_variable_assignments_in_front_are_left_out(self):
        text = '> - FOO=1 BAR=2 node b\n'
        self.assertIn((1, False, 'node b'), commands(text))

    def test_a_tilde_fence_holds_code_and_a_fence_of_the_other_kind_inside_it_does_not_close_it(self):
        text = '~~~\n```\nin code\n~~~\nplain\n'
        self.assertEqual([(number, code) for number, code, _ in commands(text)],
                         [(2, True), (3, True), (5, False)])


class DenyShapeTest(TempPluginTest):
    RULES = ['Bash(node *-e*)', 'Bash(sudo:*)', 'Read(**/.env)']

    def test_a_denied_shape_is_reported_with_its_rule_and_place_in_every_kind_of_pipeline_file(self):
        plant(self.root, {
            'skills/build/SKILL.md': '# build\n\n```\nnode -e "x"\n```\n',
            'skills/build/UI.md': 'Run `sudo make`.\n',
            'agents/code.md': 'text\nnode scripts/a-e.js\n',
        })
        self.assertEqual(deny_hits(self.root, self.RULES), [
            'agents/code.md:2: Bash(node *-e*)',
            'skills/build/SKILL.md:4: Bash(node *-e*)',
            'skills/build/UI.md:1: Bash(sudo:*)'])

    def test_a_variable_assignment_or_a_blockquote_in_front_does_not_hide_a_denied_shape(self):
        plant(self.root, {'agents/code.md': 'FOO=1 node -e x\n> sudo ls\n'})
        self.assertEqual(deny_hits(self.root, self.RULES),
                         ['agents/code.md:1: Bash(node *-e*)', 'agents/code.md:2: Bash(sudo:*)'])

    def test_the_report_never_holds_the_matched_text(self):
        plant(self.root, {'skills/build/SKILL.md': 'node -e "secret-value"\n'})
        self.assertNotIn('secret-value', ' '.join(deny_hits(self.root, self.RULES)))

    def test_loop_skills_and_clean_text_are_not_checked(self):
        plant(self.root, {'skills/measure/SKILL.md': 'node -e "x"\n',
                          'skills/build/SKILL.md': 'python "${CLAUDE_PLUGIN_ROOT}/scripts/anomaly.py" ticket show 01\n'})
        self.assertEqual(deny_hits(self.root, self.RULES), [])

    def test_the_pipeline_files_of_this_plugin_hold_no_shape_the_readable_deny_rules_match(self):
        files = [f for f in settings_files(os.environ, sys.platform, Path.home()) if f.is_file()]
        rules = deny_rules(files)
        if not rules:
            self.skipTest('no readable settings file holds a deny rule')
        self.assertEqual(deny_hits(PLUGIN, rules), [])


class ShellShapeTest(TempPluginTest):
    def test_inline_code_a_pipe_into_an_interpreter_and_a_heredoc_are_reported(self):
        plant(self.root, {
            'skills/build/SKILL.md': ('`node -e "x"`\n\n```\nbash -c "x"\nglab ci status | node parse.js\n'
                                       "cat > f <<'EOF'\n```\n\npython -c now.\n"),
            'agents/code.md': '```\ngh pr view | python3 -\nsh -c x\n```\n',
        })
        self.assertEqual(shell_hits(self.root), [
            'agents/code.md:2: pipe into an interpreter',
            'agents/code.md:3: inline code',
            'skills/build/SKILL.md:1: inline code',
            'skills/build/SKILL.md:4: inline code',
            'skills/build/SKILL.md:5: pipe into an interpreter',
            'skills/build/SKILL.md:6: heredoc',
            'skills/build/SKILL.md:9: inline code'])

    def test_every_inline_code_spelling_is_reported(self):
        spellings = ['node -p "1"', 'node --print x', 'node -pe x', 'deno eval x', 'perl -ne x', 'ruby -ne x',
                     'bash -ce x', 'zsh -lc x', 'python -Ic x', 'pwsh -c x', 'powershell -Command x',
                     'FOO=1 node -e x', '> node -e x', '- BAR=2 FOO=1 sh -c x']
        plant(self.root, {'agents/code.md': '\n'.join(spellings) + '\n'})
        self.assertEqual(shell_hits(self.root),
                         sorted(f'agents/code.md:{number}: inline code' for number in range(1, len(spellings) + 1)))

    def test_commands_that_only_look_like_inline_code_are_not_reported(self):
        plain = ['node script.js', 'python scripts/x.py -c cfg', 'perl script.pl', 'bash scripts/run.sh',
                 'powershell -File x.ps1', 'sh run.sh', 'FOO=1 make', 'python -m pytest', 'node -r pkg main.js']
        plant(self.root, {'agents/code.md': '\n'.join(plain) + '\n'})
        self.assertEqual(shell_hits(self.root), [])

    def test_a_heredoc_needs_a_command_in_front_and_a_delimiter_after_it(self):
        text = ('```\ncat <<EOF\ncat << EOF\ncat > f <<\'EOF\'\npython - <<END\nx = 1 << 3\nx << 3\n'
                'std::cout << x\ncat << END_OF_FILE\n```\n')
        plant(self.root, {'agents/code.md': text})
        self.assertEqual(shell_hits(self.root), [f'agents/code.md:{n}: heredoc' for n in (2, 3, 4, 5, 9)])

    def test_a_tilde_fence_makes_its_lines_code(self):
        plant(self.root, {'agents/code.md': '~~~\n```\ncat <<EOF\n~~~\ncat <<EOF\n'})
        self.assertEqual(shell_hits(self.root), ['agents/code.md:3: heredoc'])

    def test_tables_here_strings_and_plain_commands_are_not_reported(self):
        plant(self.root, {'skills/build/SKILL.md': (
            '| a | node |\n| --- | --- |\n\n```\ngit log | head -3\ngrep x <<< y\n'
            'python "${CLAUDE_PLUGIN_ROOT}/scripts/anomaly.py" ticket show 01\n```\n')})
        self.assertEqual(shell_hits(self.root), [])

    def test_the_pipeline_files_of_this_plugin_run_no_inline_code_and_write_no_heredoc(self):
        self.assertEqual(shell_hits(PLUGIN), [])


class FreeTextTest(TempPluginTest):
    def test_a_placeholder_in_double_quotes_or_an_unquoted_free_text_option_is_reported(self):
        call = constants.CLI_COMMAND + ' seams add <seams.md>'
        plant(self.root, {
            'skills/build/SKILL.md': (
                f'```\n{call} --name "<seam>"\n{call} --name \'<seam>\'\n'
                f'{call} --name \'<seam>\' --open "Open: <items>"\n{call} --name \'<seam>\' --open <items>\n'
                f'{constants.CLI_COMMAND} ticket adhoc <task> --repo <checkout>\n```\n'
                'Run `ticket red --changed "<why>"` then.\n'
                'Plain words "<like this>" are prose.\n'),
            'agents/code.md': f'```\n{call} --data "${{CLAUDE_PLUGIN_DATA}}" --owner \'<owner>\'\n```\n',
            'skills/observe/SKILL.md': '```\n{"session": "<session id>"}\n```\n',
            'skills/diagnose/SKILL.md': (
                f'```\n{constants.CLI_COMMAND} ticket adhoc --from <draft file> --slug <slug> --repo <checkout>\n'
                f'{constants.CLI_COMMAND} ticket adhoc --from <draft file> <task>\n```\n')})
        self.assertEqual(free_text_hits(self.root), [
            'skills/build/SKILL.md:2: free text not in single quotes',
            'skills/build/SKILL.md:2: placeholder in double quotes',
            'skills/build/SKILL.md:4: free text not in single quotes',
            'skills/build/SKILL.md:4: placeholder in double quotes',
            'skills/build/SKILL.md:5: free text not in single quotes',
            'skills/build/SKILL.md:6: free text not in single quotes',
            'skills/build/SKILL.md:8: placeholder in double quotes',
            'skills/diagnose/SKILL.md:3: free text not in single quotes'])

    def test_the_pipeline_files_of_this_plugin_put_free_text_in_single_quotes(self):
        self.assertEqual(free_text_hits(PLUGIN), [])


class AllowedToolsTest(TempPluginTest):
    def test_the_entries_of_a_list_a_string_and_a_cli_pattern_with_spaces_are_read(self):
        self.assertEqual(allowed_tools('---\nallowed-tools:\n  - Read\n  - Bash(git log *)\n---\n'),
                         ['Read', 'Bash(git log *)'])
        self.assertEqual(allowed_tools('---\nallowed-tools: Read, Bash(git log *)\n---\n'),
                         ['Read', 'Bash(git log *)'])
        self.assertEqual(allowed_tools(skill_text(constants.CLI_PATTERN)), [constants.CLI_PATTERN])
        self.assertEqual(allowed_tools('# no frontmatter\n'), [])

    def test_the_cli_pattern_is_the_quoted_form_of_the_one_command(self):
        self.assertEqual(constants.CLI_PATTERN,
                         'Bash(python "${CLAUDE_PLUGIN_ROOT}/scripts/anomaly.py" *)')
        self.assertEqual(constants.CLI_COMMAND, 'python "${CLAUDE_PLUGIN_ROOT}/scripts/anomaly.py"')

    def test_build_and_review_allow_only_the_cli_pattern_and_exactly_one_entry(self):
        for skill in ALLOWED_TOOLS_SKILLS:
            path = PLUGIN / 'skills' / skill / 'SKILL.md'
            if not path.is_file():
                continue
            entries = allowed_tools(path.read_text(encoding='utf-8'))
            with self.subTest(skill=skill):
                self.assertEqual([e for e in entries if e != constants.CLI_PATTERN], [])   # AC-26
                self.assertEqual(entries, [constants.CLI_PATTERN])                          # AC-63


class CliCallTest(TempPluginTest):
    def test_the_exact_form_in_a_line_a_span_and_a_fence_passes(self):
        call = constants.CLI_COMMAND + ' ticket show <ticket> --home "${HOME_DIR}"'
        plant(self.root, {'skills/build/SKILL.md': f'Run `{call}` first.\n\n```\n{call}\n```\n\n- {call}\n> {call}\n'})
        self.assertEqual(cli_call_hits(self.root, 'build'), [])

    def test_a_call_that_is_unquoted_unprefixed_or_chained_is_reported_with_its_line(self):
        call = constants.CLI_COMMAND + ' ticket gate 01'
        plant(self.root, {'skills/review/SKILL.md': (
            'python ${CLAUDE_PLUGIN_ROOT}/scripts/anomaly.py ticket gate 01\n'
            f'`{call} && git status`\n'
            f'`{call} | head`\n'
            f'`{call} > out.txt`\n'
            f'```\n{call} ; ls\n```\n'
            'python scripts/anomaly.py ticket gate 01\n'
            f'`{call}`\n'
            f'`{call} 2>&1`\n'
            f'`{call} >out.txt`\n')})
        self.assertEqual(cli_call_hits(self.root, 'review'), [
            'skills/review/SKILL.md:1', 'skills/review/SKILL.md:10', 'skills/review/SKILL.md:11',
            'skills/review/SKILL.md:2', 'skills/review/SKILL.md:3',
            'skills/review/SKILL.md:4', 'skills/review/SKILL.md:6', 'skills/review/SKILL.md:8'])

    def test_only_the_allowed_tools_line_of_the_frontmatter_may_name_the_script(self):
        body = 'run anomaly.py now\n'
        plant(self.root, {
            'skills/review/SKILL.md': skill_text(constants.CLI_PATTERN, body).replace(
                'description: d', 'description: runs scripts/anomaly.py'),
            'skills/build/SKILL.md': skill_text('Bash(python scripts/anomaly.py *)')})
        self.assertEqual(cli_call_hits(self.root, 'review'), ['skills/review/SKILL.md:2', 'skills/review/SKILL.md:5'])
        self.assertEqual(cli_call_hits(self.root, 'build'), ['skills/build/SKILL.md:3'])

    def test_extra_docs_of_the_skill_are_checked_too(self):
        plant(self.root, {'skills/build/SKILL.md': 'x\n', 'skills/build/BRIEF.md': 'run anomaly.py now\n'})
        self.assertEqual(cli_call_hits(self.root, 'build'), ['skills/build/BRIEF.md:1'])

    def test_build_and_review_call_the_cli_in_the_exact_form_only(self):
        for skill in ALLOWED_TOOLS_SKILLS:
            with self.subTest(skill=skill):
                self.assertEqual(cli_call_hits(PLUGIN, skill), [])

    def test_a_call_the_cli_parser_refuses_is_reported_and_a_filled_template_passes(self):
        call = constants.CLI_COMMAND
        plant(self.root, {'skills/build/SKILL.md': (
            f"```\n{call} ticket result <ticket> --branch <b> --open '<items>' --suites <n>\n"
            f'{call} ticket reviewed <ticket> <sha> --nope\n{call} no-such-command\n```\n'
            f'Run `{call} ticket gate` once.\n'),
            'agents/code.md': f'```\n{call} lens tally sum --session ${{CLAUDE_SESSION_ID}}\n```\n'})
        self.assertEqual(cli_parse_hits(self.root), [
            'skills/build/SKILL.md:3: does not parse', 'skills/build/SKILL.md:4: does not parse',
            'skills/build/SKILL.md:6: does not parse'])

    def test_every_cli_call_in_the_pipeline_text_parses(self):
        self.assertLessEqual({f'skills/{skill}/SKILL.md' for skill in ALLOWED_TOOLS_SKILLS},
                             {name for name, _, _ in cli_calls(PLUGIN)})
        self.assertEqual(cli_parse_hits(PLUGIN), [])


class PlaceholderTest(TempPluginTest):
    def test_a_placeholder_in_a_doc_other_than_skill_md_is_reported_with_its_line(self):
        plant(self.root, {'skills/build/SKILL.md': 'run "${CLAUDE_PLUGIN_ROOT}/x"\n',
                          'skills/review/BRIEFS.md': 'one\nread ${CLAUDE_PLUGIN_ROOT}/agents/feature.md\n',
                          'skills/digest/NOTES.md': '${x}\n', 'agents/code.md': '${x}\n'})
        self.assertEqual(placeholder_hits(self.root), ['skills/review/BRIEFS.md:2: unfilled placeholder'])

    def test_the_build_and_review_docs_of_this_plugin_hold_no_placeholder(self):
        self.assertEqual(placeholder_hits(PLUGIN), [])


class NoSettingsEditTest(TempPluginTest):
    def test_a_settings_file_name_or_an_allow_rule_in_plugin_files_is_reported(self):
        plant(self.root, {
            'anomaly_loop/x.py': "open('settings.json', 'w')\n",
            'skills/build/SKILL.md': skill_text(constants.CLI_PATTERN, 'Add "allow": ["x"] to it.\n'),
            'skills/review/SKILL.md': skill_text(constants.CLI_PATTERN, 'Allow `Bash(git *)` once.\n'),
            'agents/code.md': 'edit managed-settings.json\n',
            'tests/test_x.py': "SETTINGS = 'settings.json'\n"})
        self.assertEqual(settings_edit_hits(self.root), [
            'agents/code.md:1: settings file or allow rule',
            'anomaly_loop/x.py:1: settings file or allow rule',
            'skills/build/SKILL.md:5: settings file or allow rule',
            'skills/review/SKILL.md:5: settings file or allow rule'])

    def test_the_line_number_stays_true_when_the_body_ends_in_blank_lines(self):
        plant(self.root, {'skills/build/SKILL.md': skill_text(constants.CLI_PATTERN, 'settings.json here\n\n\n\n')})
        self.assertEqual(settings_edit_hits(self.root), ['skills/build/SKILL.md:5: settings file or allow rule'])

    def test_the_allowed_tools_frontmatter_is_not_an_allow_rule(self):
        plant(self.root, {'skills/build/SKILL.md': skill_text(constants.CLI_PATTERN)})
        self.assertEqual(settings_edit_hits(self.root), [])

    def test_the_plugin_edits_no_settings_file_and_prints_no_allow_rule(self):
        self.assertEqual(settings_edit_hits(PLUGIN), [])


class DocsFolderTest(TempPluginTest):
    """AC-5 (workflow-plan ticket 02): the guard-rail scans cover `docs/`, like the skill files."""

    def test_the_pipeline_files_list_the_docs_folder(self):
        plant(self.root, {'docs/formats.md': 'x\n', 'docs/sub/more.md': 'y\n', 'skills/build/SKILL.md': 'z\n',
                          'skills/measure/SKILL.md': 'loop\n', 'agents/code.md': 'a\n'})
        self.assertEqual([relative(self.root, f) for f in pipeline_files(self.root)],
                         ['skills/build/SKILL.md', 'agents/code.md', 'docs/formats.md', 'docs/sub/more.md'])

    def test_a_denied_shape_in_a_docs_file_is_reported(self):
        plant(self.root, {'docs/formats.md': 'one\n```\nsudo ls\n```\n'})
        self.assertEqual(deny_hits(self.root, ['Bash(sudo:*)']), ['docs/formats.md:3: Bash(sudo:*)'])

    def test_inline_code_in_a_docs_file_is_reported(self):
        plant(self.root, {'docs/boundaries.md': 'Run `node -e "x"` now.\n'})
        self.assertEqual(shell_hits(self.root), ['docs/boundaries.md:1: inline code'])

    def test_a_placeholder_in_double_quotes_in_a_docs_file_is_reported(self):
        plant(self.root, {'docs/formats.md': 'Run `echo "<text>"`.\n'})
        self.assertEqual(free_text_hits(self.root), ['docs/formats.md:1: placeholder in double quotes'])

    def test_an_unfilled_placeholder_in_a_docs_file_is_reported(self):
        plant(self.root, {'docs/x.md': 'a\nPath ${CLAUDE_PLUGIN_ROOT}/x\n'})
        self.assertEqual(placeholder_hits(self.root), ['docs/x.md:2: unfilled placeholder'])

    def test_the_pipeline_files_of_this_plugin_include_the_planning_docs(self):
        """The single check against the real plugin; the cases above plant files in a temporary one."""
        listed = {relative(PLUGIN, f) for f in pipeline_files(PLUGIN)}
        self.assertLessEqual({'docs/formats.md', 'docs/boundaries.md'}, listed)
