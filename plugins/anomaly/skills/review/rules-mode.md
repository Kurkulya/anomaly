# Rules mode

For `anomaly:feature` in rules mode only. Inputs: the brief (a ledger with one verdict per rule id) and the new SKILL.md with its extra docs.

1. Find each ledger rule in the new text by its meaning, in any words; the id need not appear. A keep, new, eval or merge rule must be present (a merge rule inside the rule it joins). A merge whose target is another skill or agent may be absent or a one-line pointer to it. A drop rule must be absent. A pending rule must be present and marked "pending verdict". [F5]
2. A rule in the new text that no ledger row lists is unbriefed. [F6]
3. Org facts in core text (an org tool, agent, path or host name) are a finding.
4. Measure each file's size in bytes against the budget the brief sets.

Print the table, one row per ledger rule and per unbriefed rule:

| rule id | present / absent / unbriefed | file:line |

and one line `SIZE | <bytes> of <budget> bytes` per file.

Then one finding line per problem, in the shape of the agent file, quoting the rule id as a whole token (`K02`, `X2`, `SIZE` in capitals):

- a missing keep, new, eval or merge rule (not a merge into another skill or agent): High, at line 1 of the reviewed file;
- a present drop rule: High, at its line;
- over budget: High, quoting `SIZE`, at line 1 of the file;
- an unbriefed rule: Medium, at its line, named in a few words;
- a pending rule without its mark, or an org fact in core text: Medium, at its line.

An absent drop rule and a present keep rule are table rows only, never findings.
