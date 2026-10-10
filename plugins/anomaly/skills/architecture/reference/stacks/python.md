# Stack profile: Python

Picked when the repo has `pyproject.toml`, `setup.py` or tracked `*.py` files. Run on one flat
package: greps 1, 2, 4, 5 hit; 3 and 6 found none. Replace `<name>` (package), `<pkg>` (its
folder), `<high>` (`a|b`), `<low>` (paths).

- **Layers.** `constants/models → platform adapters (files, HTTP, DB) → services → cli/api`. A flat
  package: rank modules by who imports whom.
- **Imports.** Absolute `from <name> import x`, `import <name>.x`; relative `from . import
  x`, `from ..x import y`. Run both, then union.
- **State.** Module-level lists and dicts, `global`, `lru_cache`; no second copy of a
  platform adapter result.
- **Side effects.** `print`, `input`, `sys.exit` below the cli: return a value or raise.
- **Platform adapters.** One module each for `os.environ`, the clock, `subprocess`, files, HTTP.

```bash
git ls-files '*.py' | cut -d/ -f1-3 | sort | uniq -c | sort -rn   # base: files per dir
git ls-files pyproject.toml setup.py tox.ini Makefile '.github/workflows/*' '.gitlab-ci.yml'
# 1 lower module importing a higher one: absolute, then relative
git grep -nE '^\s*(from\s+<name>\s+import\s+.*\b(<high>)\b|(from|import)\s+<name>\.(<high>)\b)' -- <low>
git grep -nE '^\s*from\s+\.+\s+import\s+.*\b(<high>)\b|^\s*from\s+\.+(\w+\.)*(<high>)\s+import' -- <low>
# 2 raw wire data
git grep -nE "json\.loads\(|\.json\(\)\[|->\s*(dict|Dict)\[str,\s*(Any|object)\]" -- ':(glob)<pkg>/**/*.py'
# 3 module-level mutable state
git grep -nE "^[a-z_][a-z_0-9]*\s*(:[^=]+)?=\s*(\[\]|\{\}|dict\(\)|set\(\))|^\s+global\s" -- ':(glob)<pkg>/**/*.py'
# 4 acting sites; raw platform calls per file
git grep -nE "\bprint\(|\binput\(|sys\.exit\(" -- ':(glob)<pkg>/**/*.py' | wc -l
git grep -cE "os\.environ|os\.getenv|datetime\.now\(|time\.time\(|subprocess\." -- ':(glob)<pkg>/**/*.py'
# 5 biggest modules
git ls-files '*.py' | xargs wc -l | sort -rn | sed -n 2,11p
# 6 lint level
git grep -nE "importlinter|import-linter|fail_under|\[tool\.(ruff|mypy|pylint)" -- pyproject.toml tox.ini
```
