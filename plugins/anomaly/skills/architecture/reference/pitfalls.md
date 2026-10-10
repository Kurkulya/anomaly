# Pitfalls — the rule each one teaches

## 1. Alias-only grep

Every import grep runs twice, alias and relative spelling, then union. A first run that
checked only the alias found 3 of 11 violations. Write the count as "N violations (a alias,
b relative)". The lint lock that holds the layer order must match both spellings, or it
locks nothing.

## 2. Filesystem vs git

Facts come from `git ls-files`, grep over tracked files, `git log`, and the repo's own
scripts. An untracked file is neither repo debt nor a repo asset. Say "tracked" in every
count that could be confused ("8 tracked ADRs").

## 3. Wrong counts

Count before you write a number into a report or a summary, and put the command next to
it. Every countable claim will be re-counted. When you correct an earlier claim, say so:
"Correction: pass one said 3, the right number is 11; reason: alias-only grep."

## 4. Words with two meanings

List the domain words the area findings use and check each against `CONTEXT.md`. A word that
means two things (for example "draft" for both an unsaved copy and a status value) goes
into the summary's word list. The interview settles the term; this skill does not edit
`CONTEXT.md`.

## 5. Measuring intent instead of the artifact

Read the CI file, the lint level, the flag's value and its age with `git log -S`. If the
artifact is outside the repo (a shared CI template), say "unknown from inside this repo",
and the proposed work moves the check inside.
