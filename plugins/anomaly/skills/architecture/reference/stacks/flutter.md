# Stack profile: Flutter

Picked when the repo has `pubspec.yaml` with a `flutter:` section. No Flutter repo was at
hand: the greps below are unverified (only their git syntax was run). Replace `<app>` (the
package name in `pubspec.yaml`).

- **Layers.** `domain → data → application → presentation` (under `lib/`).
- **Imports.** Package spelling `import 'package:<app>/...'`; relative spelling
  `import '../...'`. Run both, then union.
- **State.** Providers, notifiers, cubits and blocs: one owner per fact; none holds a copy of
  a repository result. `setState` is for ephemeral view state.
- **Side effects.** `ScaffoldMessenger`, `Navigator`, `showDialog` below `presentation`:
  return a decision, a widget performs it.
- **Platform adapters.** One class each around `SharedPreferences`, `Dio` and platform channels.

```bash
git ls-files 'lib/*' | cut -d/ -f2 | sort | uniq -c | sort -rn      # base: files per layer
git ls-files pubspec.yaml analysis_options.yaml Makefile '.github/workflows/*'
# 1 domain importing a higher layer or Flutter: package, then relative
git grep -nE 'import .package:(<app>/(data|application|presentation)|flutter/)' -- lib/domain   # `.` matches the quote
git grep -nE "import '(\.\./)+(data|application|presentation)/" -- lib/domain
# 2 wire types past the data layer
git grep -nE 'Response<dynamic>|Map<String,\s*dynamic>' -- lib/application lib/presentation
# 3 state holders; read each for a copy of a repository result
git grep -nE "StateNotifier|Notifier<|Cubit<|ChangeNotifier" -- 'lib/*.dart' | wc -l
# 4 raw prefs outside the platform adapter; acting below presentation
git grep -nE "SharedPreferences\.getInstance" -- 'lib/*.dart' | grep -v '<platform adapter file>'
git grep -nE "ScaffoldMessenger|Navigator\.|showDialog" -- lib/domain lib/data lib/application
# 5 biggest files
git ls-files 'lib/*.dart' ':(exclude)*.g.dart' | xargs wc -l | sort -rn | sed -n 2,11p
# 6 lint level
git grep -nE "severity|errors:|import_lint|custom_lint" -- analysis_options.yaml
```
