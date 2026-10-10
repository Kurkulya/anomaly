# Stack profile: Flutter (flutter test, Patrol)

Picked when `pubspec.yaml` lists flutter_test or patrol. Use the repo's own script names
(`melos`, `Makefile`). Greps are candidates only (`grep-recipes.md`).

- **Find tests.** Unit and widget: `git ls-files 'test/*_test.dart'`. Patrol:
  `integration_test/`. Widget flows may live in a folder such as `test/flows/`.
- **Run one file.** `flutter test <file>`; Patrol: `patrol test --target <file>` (unverified:
  check `patrol test --help` for the repo's version).
- **Time one file.** `flutter test --file-reporter json:<evidence>/flutter.json` gives
  per-test times. Patrol needs a device or emulator; with none, write `[NM] not measured`
  and say why.
- **Empty assertion.** `isNotNull`, `isA<Function>()`, `returnsNormally`, or no `expect(`.
  A check of what the user sees (`findsOneWidget`) is real.
- **E2e test.** A `patrolTest(` or `patrolWidgetTest(`; its reason is a tag
  (`tags: ['reason-<slug>']`) that `dart_test.yaml` must declare.
- **Break code.** In the copy, edit the code under test by hand. Run the cover with
  `flutter test <cover file>`.
- **Install freshness.** `flutter --version` against the repo's pinned SDK; `pubspec.lock`
  against the age of `.dart_tool/package_config.json`.
- **Scope example** (an example only): `features/` A–M · `features/` N–Z + `core/` +
  `shared/` · widget flows + `integration_test/` (Patrol) · runtime.

## Recipes

```bash
git ls-files 'test/*_test.dart' | cut -d/ -f1-3 | sort | uniq -c | sort -rn
git grep -cE "^[[:space:]]*(test|testWidgets)\(" -- 'test/*_test.dart' | awk -F: '{s+=$2} END {print s}'

# EMPTY-ASSERTION
git grep -nE 'isNotNull|isA<Function>\(\)|returnsNormally' -- '*_test.dart' | head -50
git grep -L -E "expect\(|expectLater\(|verify\(" -- '*_test.dart' | head

# INTERNALS
git grep -nE "toStringDeep\(|debugDumpApp|Color\(0x|\.padding, ?equals|TextStyle\(" -- '*_test.dart' | head
git grep -n "matchesGoldenFile" -- '*_test.dart' | grep -v '<design-system folder>' | head
git grep -cE "extends Mock implements|overrideWith(Value)?\(" -- '*_test.dart' | sort -t: -k2 -rn | head -20

# Patrol
git grep -nE "patrol(Widget)?Test\(" -- integration_test | head -80
git grep -nE "tags:[[:space:]]*\[[^]]*reason-[a-z-]+" -- integration_test | head -80
git show <sha>:dart_test.yaml 2>/dev/null | grep -A20 "^tags"
```

A mock of the HTTP client (for example Dio) or a repository provider is the boundary, and
fine. A mock of a sibling notifier, service or widget is the smell.

A Patrol test without a device-only reason may already have a widget flow test that
proves it. Look there first for the cover.
