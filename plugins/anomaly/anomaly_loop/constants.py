"""Every fixed number, name and vocabulary of the loop, in one place.

Change a value here, never at the place that uses it.
"""
from pathlib import Path

# ---------- thresholds and windows ----------

NUDGE_MIN_SCORE = 4                  # nudge: open problems with at least this score
DIGEST_TOP = 3                       # digest backlog section: this many top anomalies
REPEAT_MIN_SIGHTINGS = 3             # repeated action: seen this many times ...
REPEAT_MIN_SESSIONS = 2              # ... in at least this many sessions ...
REPEAT_WINDOW_DAYS = 14              # ... within this many days
CHURN_MIN_COMMITS = 3                # needs-rework: this many commits ...
CHURN_WINDOW_DAYS = 28               # ... within this many days
REWORK_MIN_OPEN_PROBLEMS = 3         # needs-rework: or this many open or reopened problems about one target
CHURN_GRACE_DAYS = 14                # targets created or rewritten this recently are exempt
STALE_DAYS = 60                      # one-sighting anomalies older than this are offered as wontfix
UNUSED_DAYS = 56                     # a plugin skill unused this long is proposed for removal
TREND_WINDOW_DAYS = 14               # digest trends: last window against the one before
EXPERIMENT_CHECK_SESSIONS = 20       # default check: this many sessions of the relevant kind ...
EXPERIMENT_CHECK_DAYS = 21           # ... or this many days
BASELINE_DAYS = 28                   # experiment baseline before the fix
ACTIVE_GAP_SECONDS = 5 * 60          # a gap longer than this between entries is idle time
PROMPT_CACHE_DAYS = 30               # prompt excerpts older than this are pruned

# ---------- vocabularies ----------

DEFAULT_TICKET_KEY = r'[A-Z][A-Z0-9]+-\d+'
KINDS = ('problem', 'win')
ENVIRONMENT_CATEGORIES = ('navigation', 'automated-checks', 'coding-standards', 'steering-files',
                          'tool-economy', 'no-ops', 'information-access')   # capture pass 1: the agent's environment
WORKFLOW_CATEGORIES = ('rework', 'late-catch', 'handoff-loss', 'manual-step', 'blocked',
                       'pipeline-fit')                                      # capture pass 2: the way of working
CATEGORIES = ENVIRONMENT_CATEGORIES + WORKFLOW_CATEGORIES
ACTIVE_STATUSES = ('open', 'reopened')
STATUSES = ACTIVE_STATUSES + ('fixed', 'wontfix')
IMPACT_RANGE = (1, 3)
EFFORTS = ('S', 'M', 'L')
EXPERIMENT_RESULTS = ('keep', 'revert', 'inconclusive', 'unproven')
VERDICTS = ('adopt', 'trial', 'park', 'reject')
SESSION_KINDS = ('build', 'research', 'config', 'debug', 'unknown')
BUILD_SKILLS = ()   # no default: the profile key build_skills names the skills that make a session 'build'

# ---------- file names: home (durable) ----------

METRICS_FILE = 'metrics.jsonl'
INDEX_FILE = 'INDEX.md'
ANOMALIES_DIR = 'anomalies'
IDEAS_DIR = 'ideas'
LENSES_FILE = 'lenses.jsonl'
SESSION_KINDS_FILE = 'session-kinds.jsonl'
PROFILE_FILE = 'profile.md'
WORK_UNITS_FILE = 'work-units.jsonl'   # one line per pipeline stage run: {feature, stage, session, date, ended}
                                        # plus started, doc_bytes, ticket and mode when they apply
WORKLOG_BUILD_STAGE = 'build'   # the stage whose line, written after the merge, marks a ticket as merged
WORKLOG_REVIEW_STAGE = 'review'   # the one stage whose line may carry a review mode
WORKLOG_TICKET_STAGES = (WORKLOG_BUILD_STAGE, WORKLOG_REVIEW_STAGE)   # the stages whose line, and start, may name one ticket (--ticket)
REVIEW_MODES = ('ticket', 'delta', 'cumulative', 'combined', 'rules')   # the review modes of AC-45

# ---------- file names: data folder (throwaway) ----------

STATE_FILE = 'measure-state.json'
NUDGE_MARKER_FILE = 'nudge-week'
PROMPT_CACHE_FILE = Path('cache') / 'prompts.jsonl'
LENS_TALLY_FILE = 'lens-tally.jsonl'   # one {session, lens, accepted, rejected[, revised]} line per reviewer, its counts over its rounds
LENS_BATCH_FILE = 'lens-batch-{session}.json'   # the observe batch `lens tally sum` writes for a session
WORKLOG_START_FILE = 'worklog-starts.jsonl'   # append-only: a {feature, stage, [ticket,] started} line per `worklog start`,
                                              # a {feature, stage, [ticket,] consumed} line when `worklog add` has read it

# ---------- observe: record limits ----------

SIGHTING_MAX_CHARS = 300             # one sighting: a short line in the writer's own words
PARAGRAPH_MAX_CHARS = 600            # an anomaly's problem or win paragraph, and its proposed fix
SIGHTING_SEPARATOR = ' · '           # sighting line: date, repository, session, what happened
IDENTIFIER_MAX_CHARS = 80            # a repository, session or lens name stored on a line of its own
SUMMARY_CHARS = 120                  # `observe list`: first words of an anomaly's text
COMMIT_SCOPE = 'anomaly'             # scope of the commit that records observe writes
UNKNOWN_REPO = 'unknown'             # repository name when the skill gives none

# ---------- digest trends ----------

DIGEST_TOP_SKILLS = 3                # digest trends: this many skills by weighted tokens
REVERTED_FIX_CHARS = 100             # digest trends: a reverted fix is cut to this many characters

# ---------- assess ----------

IDEA_QUOTE_MIN_WORDS = 4             # a quoted span of fewer words is a term, not a quote
IDEA_QUOTE_MAX_WORDS = 15            # an idea's body holds at most one quote, this many words at most
TEXT_KEY_PREFIX = 'text:'            # idea source for an assessed text or opinion: prefix + digest of its words
TEXT_KEY_LENGTH = 12                 # hex characters of that digest
ASSESS_DEFAULT_SCOPE = 'global'      # scope of an anomaly that `assess record` creates for an adopted idea
ASSESS_DEFAULT_IMPACT = 1            # impact of that anomaly unless given
LINK_DIGEST_LENGTH = 8               # hex characters of the digest that stands for a link's query or routing fragment
LINK_TRACKING_PARAMS = ('fbclid', 'gclid', 'ref')   # query parameters that do not make a different page ...
LINK_TRACKING_PREFIXES = ('utm_',)                  # ... and the prefixes of such parameters

# ---------- digest flags and the nudge ----------

NEAR_DUPLICATE_MIN_OVERLAP = 0.6     # near-duplicates: signatures whose words overlap by at least this share
NEAR_DUPLICATE_MIN_TEXT_OVERLAP = 0.3  # near-duplicates: same target and category also needs this share of summary or fix words
REPEAT_MIN_PROMPT_WORDS = 3          # repeated prompts: shorter ones ("yes", "continue") are not counted
REPEAT_POINTER_MAX_WORDS = 8         # a repeated prompt this short fits a pointer, a longer one a skill
FLAGS_SHOW = 5                       # digest flag lists: this many lines per list, then "+n more"
CHURN_RUN_GAP_DAYS = 28              # needs-rework grace: a quiet spell longer than this ends a run of activity
PROMPT_SHOW_CHARS = 80               # repeated prompts are printed cut to this many characters
READ_ONLY_SHAPES = ('sed -n', 'grep', 'cat', 'head', 'tail', 'ls', 'git log', 'git show', 'git diff',
                    'git status')    # command shapes that only read: never offered for automation

# ---------- calibrate: experiments and verdicts ----------

FIXED_BY_SEPARATOR = SIGHTING_SEPARATOR   # fixed_by: the day the fix landed, then its commit or file
VERDICT_LEVEL = 0.10                 # verdict: a real change needs chance alone (two-way) at or below this share ...
VERDICT_MIN_CHANGE = 0.15            # ... a change by this share or more ...
VERDICT_MIN_SAMPLES = 5              # ... and this many sessions before the fix and since (and per digest trend window)
GUARD_LEVEL = 0.10                   # a guard is worse only when chance alone for a rise is at or below this share
PERMUTATION_SPLITS = 10_000          # chance alone: every split up to this many, else this many random ones ...
PERMUTATION_SEED = 9                 # ... drawn with this seed, so the same data always gives the same answer
VERDICT_RULE = 'permutation test, ADR-0009'   # the rule a verdict names in its reason
RARE_EVENT_RULE = 'rare-event rule, ADR-0009'   # ... and the rule of a rare-event primary (no count test)
WORKFLOW_MIN_SCORE = 4               # a workflow-category fix needs this score, unless impact is the highest
GUARD_MIN_SIGHTINGS = 2              # a sighting guard counts as worse only with this many sightings since the fix
QUALITY_GUARDS = ('rework sightings', 'late-catch sightings', 'interrupts')   # the only metrics a guard may be
GUARD_HELP = f'exactly one quality guard that must not get worse: {", ".join(QUALITY_GUARDS)}'

# ---------- ticket files ----------

TICKET_ADHOC_DIR = Path('.anomaly') / 'adhoc'   # a light-path ticket is one file here, under the main checkout
TICKET_SLUG_MAX_CHARS = 40           # adhoc ticket: the file name's slug made from the task text
TICKET_TITLE_MAX_CHARS = 80          # adhoc ticket: the heading is the task cut to this length
TICKET_FIELD_SEPARATOR = ' · '       # between the parts of a Result: or Red: line
TICKET_TIME_FORMAT = '%Y-%m-%d %H:%M'   # the times on a Metrics: line
TICKET_START_UNKNOWN = 'unknown'     # `started unknown` on a Metrics: line closed without a start time
TICKET_NUMBER_DIGITS = 2             # a ticket is named by a number of two ASCII digits (NN): ledger lines, work-unit lines
NO_START_WARNING = 'warning: no start time'   # printed (on stdout, like the other ticket warnings) by `worklog add` and `ticket result`
TICKET_STATUS_DONE = 'done'          # ticket Status: words the commands write or test for
TICKET_STATUS_IN_PROGRESS = 'in-progress'
TICKET_STATUS_READY = 'ready-for-agent'
TICKET_STATUS_UNKNOWN = 'unknown'    # what a ticket without a readable Status: line reports

# ---------- pipeline skills ----------

LOOP_SKILLS = ('measure', 'observe', 'calibrate', 'assess')   # every other skill is a pipeline skill
CLI_COMMAND = 'python "${CLAUDE_PLUGIN_ROOT}/scripts/anomaly.py"'   # the one way a skill runs the CLI
CLI_PATTERN = f'Bash({CLI_COMMAND} *)'   # the one entry of a pipeline skill's allowed-tools

# ---------- ports and the repo layer (ADR-0007) ----------

REPOS_DIR = 'repos'                  # <home>/repos/<repo>.md: the personal repo override file
REPLACE, ADD, EXTEND = 'replace', 'add', 'extend'   # the port modes
SECURITY_REVIEWER = 'anomaly:security'   # the core security reviewer, as its tokens are keyed in tokens_by_agent
# (port, mode, profile key, core default items), in the order `ports` prints them. A port in
# PER_STACK_PORTS reads one `stack: adapter` line per stack from its key.
PORTS = (
    ('implementer', REPLACE, 'implementers', ('general-purpose agent with the build brief',)),
    ('test_writer', REPLACE, 'test_writers',
     ('a separate general-purpose dispatch with the test-writer brief, never the implementer',)),
    ('conventions', EXTEND, 'conventions', ("the repo's own docs, only the sections the diff touches",)),
    ('reviewers', ADD, 'reviewers', ('anomaly:code', 'anomaly:feature', SECURITY_REVIEWER)),
    ('gather', ADD, 'gather', ("read the repo's code and docs",)),
    ('tracker', REPLACE, 'tracker', ('local .anomaly markdown, read-only',)),
    ('issue_source', REPLACE, 'issue_source', ('local .anomaly markdown, read-only',)),
    ('ci', REPLACE, 'ci', ('no CI gate',)),
    ('mr', REPLACE, 'mr_tool', ('print the MR body to paste',)),
    ('commit', REPLACE, 'commit_style', ('type(scope): summary',)),
    ('branch', REPLACE, 'branch_pattern', ('feat/<slug>',)),
    ('ui_check', REPLACE, 'verify_ui', ("built-in browser walkthrough of the ticket's UI ACs",)),
)
PER_STACK_PORTS = ('implementer', 'test_writer', 'conventions')
MODELS_KEY = 'models'                # profile key: one `role: model` line per role
MODEL_ROLES = (                      # (role, core default), in the order `ports` prints them
    ('explore', 'sonnet'),
    ('implement', 'sonnet for contained tickets, opus for cross-cutting ones'),
    ('review', 'opus'),
    ('deep_analysis', 'opus'),
    ('browse', 'sonnet'),
)
REPO_COMMANDS = ('verify', 'e2e', 'install', 'codegen', 'hook_path')   # hook_path: a folder, not a command
INSTRUCTION_FILES = ('CLAUDE.md', 'AGENTS.md')   # a line `<label>: `<text>`` names a command explicitly
EXPLICIT_SCRIPTS = ('verify', 'e2e', 'codegen')  # package.json scripts and Makefile targets named like the command
GUESSED_SCRIPTS = (('verify', 'test'), ('e2e', 'test:e2e'), ('codegen', 'generate'))   # guessed, below the override
MAKE_INSTALL_TARGETS = ('deps',)     # guessed; `make install` usually installs the program itself, so it is not read
LOCKFILES = (('yarn.lock', 'yarn'), ('pnpm-lock.yaml', 'pnpm'), ('bun.lock', 'bun'), ('bun.lockb', 'bun'),
             ('package-lock.json', 'npm'))
DEFAULT_PACKAGE_MANAGER = 'npm'      # package.json with none of the lockfiles above
NO_LOCKFILE_INSTALL = 'npm install --ignore-scripts'   # no lockfile: nothing to freeze (npm ci would fail), no scripts
FROZEN_INSTALLS = {                  # the guessed install per manager: the lockfile as it is, no package scripts (VK D3);
    'npm': 'npm ci --ignore-scripts',
    'yarn': 'yarn install --frozen-lockfile --ignore-scripts',   # Yarn 1 flags
    'pnpm': 'pnpm install --frozen-lockfile --ignore-scripts',
    'bun': 'bun install --frozen-lockfile --ignore-scripts',
}
BUILD_RUNNER_CODEGEN = 'dart run build_runner build --delete-conflicting-outputs'   # pubspec with build_runner
APP_FACTS = ('port', 'width', 'theme_key', 'console_error', 'login_redirect')   # override `ui_check:` block
RISK_PATTERNS_KEY = 'risk_patterns'  # override key: one `- <pattern>` line per extra risk pattern
BASE_KEY = 'base'                    # override key: the base branch the integration branch is cut from
DEFAULT_BASE_BRANCH = 'main'         # the base branch when neither the override file nor origin's HEAD names one

# ---------- seeded-defect benchmark (`bench score`) ----------

FINDING_SEVERITIES = ('Blocker', 'High', 'Medium', 'Low', 'Nit')   # the reviewers' scale, most severe first
FINDING_STATES = ('observed', 'unverified')   # the last field of a finding line
BENCH_FOUND_FLOOR = 'Medium'         # a finding on a planted defect counts as found at this severity or above
BENCH_FALSE_HIGH = ('Blocker', 'High')   # a finding this severe that matches no planted defect is a false High
BENCH_WINDOW = 3                     # a finding matches a planted range this many lines to either side
BENCH_MAX_RUNS = 3                   # the median is of at most this many runs
OWASP_2021 = (                       # the public OWASP Top 10 2021 labels and category names
    ('A01', 'Broken Access Control'),
    ('A02', 'Cryptographic Failures'),
    ('A03', 'Injection'),
    ('A04', 'Insecure Design'),
    ('A05', 'Security Misconfiguration'),
    ('A06', 'Vulnerable and Outdated Components'),
    ('A07', 'Identification and Authentication Failures'),
    ('A08', 'Software and Data Integrity Failures'),
    ('A09', 'Security Logging and Monitoring Failures'),
    ('A10', 'Server-Side Request Forgery'),
)

# ---------- pre-merge check and seam ledger ----------

SHORT_SHA_CHARS = 12                 # a commit id as shown in a message
SEAM_BULLET = '- '                   # a seam ledger line: `- <name> · <owner file> · replaces <old way> (ticket NN)`
SEAM_REPLACES = 'replaces'           # the word before the old way; the parts are joined by TICKET_FIELD_SEPARATOR

# ---------- ci watch and ci log ----------

CI_ADAPTERS = ('glab',)              # the `ci` profile values that name a CI tool wrapper
CI_PASSED, CI_FAILED, CI_RUNNING, CI_DEAD, CI_NO_PIPELINE = 0, 1, 3, 4, 5   # exit codes; 2 is the error contract
CI_DEFAULT_MAX_MIN = 8               # `ci watch` waits about this long: polls are counted, the tool calls come on top
CI_POLL_SECONDS = 30                 # between two looks at a running pipeline
CI_ATTEMPTS = 3                      # tries of one CI tool call before a network error is final
CI_RETRY_SECONDS = 5                 # pause before retry n is n times this
CI_TRACE_LINES = 40                  # failure lines shown per failed job

# ---------- risk ----------

# (area, fnmatch globs) in the order `risk` prints them. A glob is matched in lower case against the
# whole repository-relative path and against its file name, so `*auth*` finds src/auth/x.py and
# `.env*` finds app/.env.local. The repo layer adds its own globs as one more area, RISK_REPO_AREA.
RISK_AREAS = (
    ('auth', ('*auth*', '*login*', '*logout*', '*session*', '*token*', '*password*', '*permission*', '*role*',
              '*oauth*', '*jwt*', '*cookie*', '*csrf*')),
    ('input parsing and execution', ('*parse*', '*deserializ*', '*pickle*', '*upload*', '*multipart*',
                                     '*subprocess*', '*shell*', '*exec*', '*.sql', '*migrat*')),
    ('secrets or config', ('.env*', '*config*', '*settings*', '*secret*', '*credential*', '.gitlab-ci.yml',
                           '.github/workflows/*', '.circleci/*', 'jenkinsfile', 'dockerfile*', '*.pem', '*.key',
                           '*.crt', '*.p12', '*.pfx')),
    ('dependencies', ('package.json', *(lockfile for lockfile, _ in LOCKFILES), '*.lock',
                      'pubspec.*', 'go.mod', 'go.sum', 'pyproject.toml', 'requirements*.txt')),
    ('network calls', ('*fetch*', '*axios*', '*http*', '*urllib*', '*requests*', '*socket*', '*grpc*')),
)
RISK_REPO_AREA = 'repo layer'        # the area of the globs `risk_patterns` adds; matched in the case written
