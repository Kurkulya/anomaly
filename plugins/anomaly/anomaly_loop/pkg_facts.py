"""pkg-facts: the same registry facts for every package, one table row each, as evidence for a choice.

  pkg-facts <package>... [--json] [--repo DIR]    print one row per package; nothing is written

Columns: package, latest version, date, licence, deprecated, repository, stars, open issues,
scorecard, downloads. A package is `<ecosystem>:<name>` (npm, pypi, go, maven, cargo, nuget, pub);
a package with no prefix takes its ecosystem from the one manifest family in the `--repo` folder
(package.json, pubspec.yaml, go.mod, pyproject.toml or requirements.txt, Cargo.toml). `--repo` is
read as given, inside or outside git (default: the working folder), so a subfolder reads its own
manifests.

Two adapters: deps.dev (package, version and project endpoints, no token; downloads are not offered)
and pub.dev (package and score endpoints; licence from the score `license:<id>` tags, repository from
the pubspec `repository` only; deprecated from the package `isDiscontinued` key, Unknown when the
key is absent; no stars, issues or Scorecard). A column an adapter cannot fill prints Unknown.

A failed fetch or a malformed response (missing key, null or wrong type) prints FETCH FAILED for that
package with every column Unknown; an ecosystem with no adapter prints `no adapter: <system>`; both
make the exit code 1, a negative result. A package with no prefix and no single ecosystem in the
folder, or a name of . or .., is bad input: one `anomaly:` line and exit 2 before anything is
fetched. --json prints the rows as a JSON list; the notes then go to stderr.

Standard library only.
"""
import http.client
import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path

from .files import RecordError

COLUMNS = ['package', 'latest version', 'date', 'licence', 'deprecated', 'repository',
           'stars', 'open issues', 'scorecard', 'downloads']
UNKNOWN = 'Unknown'
DEPS_DEV = 'https://api.deps.dev/v3'
PUB_DEV = 'https://pub.dev/api/packages'
DEPS_DEV_SYSTEMS = {'npm': 'NPM', 'pypi': 'PYPI', 'go': 'GO', 'maven': 'MAVEN', 'cargo': 'CARGO', 'nuget': 'NUGET'}
MANIFESTS = {'package.json': 'npm', 'pubspec.yaml': 'pub', 'go.mod': 'go', 'pyproject.toml': 'pypi',
             'requirements.txt': 'pypi', 'Cargo.toml': 'cargo'}
MAX_RESPONSE_BYTES = 5 * 1024 * 1024   # a response this big or bigger is a FETCH FAILED
PUB_LICENCE_CLASSES = {'license:fsf-libre', 'license:osi-approved'}   # pub.dev tags that classify a licence, not name one
FETCH_ERRORS = (OSError, ValueError, http.client.HTTPException, KeyError, TypeError, AttributeError)


def fetch(url):
    """The response body of a GET, as bytes."""
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (research; pkg-facts)'})
    with urllib.request.urlopen(req, timeout=30) as r:
        body = r.read(MAX_RESPONSE_BYTES)
    if len(body) >= MAX_RESPONSE_BYTES:
        raise ValueError(f'response at or over {MAX_RESPONSE_BYTES} bytes')
    return body


def get_json(url):
    return json.loads(fetch(url))


def quote(part):
    return urllib.parse.quote(part, safe='')


def text(value):
    """A cell: the value as plain text, Unknown when the source has none."""
    return UNKNOWN if value is None or value == '' else str(value)


def first_ten(stamp):
    return stamp[:10] if stamp else None


def row_of(package, **cells):
    return {'package': package, **{name: text(cells.get(name)) for name in COLUMNS[1:]}}


def deps_dev_facts(system, name):
    """Cells from deps.dev: package, then version, then project endpoint."""
    package = get_json(f'{DEPS_DEV}/systems/{system}/packages/{quote(name)}')
    default = next((v for v in package.get('versions', []) if v.get('isDefault')), None)
    if default is None:
        raise KeyError('no default version')
    version = default['versionKey']['version']
    cells = {'latest version': version, 'date': first_ten(default.get('publishedAt')),
             'deprecated': 'yes' if default.get('isDeprecated') else 'no'}
    detail = get_json(f'{DEPS_DEV}/systems/{system}/packages/{quote(name)}/versions/{quote(version)}')
    cells['licence'] = ', '.join(detail.get('licenses', []))
    repo = next((p['projectKey']['id'] for p in detail.get('relatedProjects', [])
                 if p.get('relationType') == 'SOURCE_REPO'), None)
    if repo is None:
        return cells
    project = get_json(f'{DEPS_DEV}/projects/{quote(repo)}')
    cells.update({'repository': repo, 'stars': project.get('starsCount'),
                  'open issues': project.get('openIssuesCount'),
                  'scorecard': (project.get('scorecard') or {}).get('overallScore')})
    return cells


def pub_facts(name):
    """Cells from pub.dev: package endpoint, then score endpoint."""
    package = get_json(f'{PUB_DEV}/{quote(name)}')
    latest = package.get('latest', {})
    pubspec = latest.get('pubspec', {})
    score = get_json(f'{PUB_DEV}/{quote(name)}/score')
    licences = [tag[len('license:'):] for tag in score.get('tags', [])
                if tag.startswith('license:') and tag not in PUB_LICENCE_CLASSES]
    discontinued = package.get('isDiscontinued')
    if discontinued is not None and not isinstance(discontinued, bool):
        raise TypeError(f'isDiscontinued is {type(discontinued).__name__}, not a bool')
    return {'latest version': latest.get('version'), 'date': first_ten(latest.get('published')),
            'licence': ', '.join(licences),
            'deprecated': None if discontinued is None else 'yes' if discontinued else 'no',
            'repository': pubspec.get('repository'),
            'downloads': score.get('downloadCount30Days')}


def facts(ecosystem, name):
    """Cells for one package, or None when the ecosystem has no adapter."""
    if ecosystem in DEPS_DEV_SYSTEMS:
        return deps_dev_facts(DEPS_DEV_SYSTEMS[ecosystem], name)
    if ecosystem == 'pub':
        return pub_facts(name)
    return None


def detect_ecosystem(folder):
    """The one ecosystem the manifests in `folder` name, or None for none or several."""
    found = {eco for manifest, eco in MANIFESTS.items() if (Path(folder) / manifest).is_file()}
    return found.pop() if len(found) == 1 else None


def cell(value):
    """A Markdown table cell: `|` escaped, line breaks as spaces, so a value cannot split its row."""
    return value.replace('|', '\\|').replace('\r', ' ').replace('\n', ' ')


def render(rows):
    lines = ['| ' + ' | '.join(COLUMNS) + ' |', '|' + ' --- |' * len(COLUMNS)]
    lines += ['| ' + ' | '.join(cell(row[c]) for c in COLUMNS) + ' |' for row in rows]
    return '\n'.join(lines)


def wanted_packages(packages, folder):
    """[(given, ecosystem, name)] for the packages; bad input is a RecordError naming every bad one."""
    wanted, problems = [], []
    folder_ecosystem = None
    for given in packages:
        ecosystem, sep, name = given.partition(':')
        if not sep:
            folder_ecosystem = folder_ecosystem or detect_ecosystem(folder)
            ecosystem, name = folder_ecosystem, given
            if ecosystem is None:
                problems.append(f'{given}: no single ecosystem in {folder}; add a prefix such as npm:{given}')
        if name in ('.', '..'):
            problems.append(f'{given}: . and .. are not package names')
        wanted.append((given, ecosystem.lower() if ecosystem else None, name))
    if problems:
        raise RecordError('; '.join(problems))
    return wanted


def register(commands, common):
    command = commands.add_parser('pkg-facts', parents=[common],
                                  help='print the same registry facts for every package, one row each')
    command.add_argument('packages', nargs='+', metavar='package',
                         help='<ecosystem>:<name> (npm, pypi, go, maven, cargo, nuget, pub), or a bare name '
                              'when the --repo folder has one manifest family')
    command.add_argument('--json', action='store_true', help='print the rows as a JSON list')
    command.add_argument('--repo', help='the folder whose manifests give a bare name its ecosystem, read as '
                                        'given (default: the working folder)')
    command.set_defaults(handler=run_pkg_facts)


def run_pkg_facts(args, environ):
    folder = Path(args.repo) if args.repo else Path.cwd()
    rows, notes = [], []
    for given, ecosystem, name in wanted_packages(args.packages, folder):
        try:
            cells = facts(ecosystem, name)
        except FETCH_ERRORS as e:
            notes.append(f'FETCH FAILED: {given} ({type(e).__name__}: {e})')
            cells = {}
        else:
            if cells is None:
                notes.append(f'no adapter: {ecosystem} ({given})')
                cells = {}
        rows.append(row_of(given, **cells))
    if args.json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        for note in notes:
            print(note, file=sys.stderr)
    else:
        print(render(rows))
        for note in notes:
            print(note)
    return 1 if notes else 0
