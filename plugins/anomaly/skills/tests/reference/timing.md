# Timings and CPU load

A timing on a busy machine is a different number. So every timing carries the load, and
any number a later ticket depends on is re-timed alone before planning.

`<evidence>` below is `.anomaly/test-audit-<date>/research/evidence/`.

## Before any run

1. **Install is fresh.** Compare the installed test runner with the lockfile (the check
   is in the stack profile, "Install freshness"). Stale → stop and ask. Do not install in
   the repo. Options: the user installs, or the runtime agent times a copy: `mkdir -p
   <scratchpad>/copy && git archive <sha> | tar -x -C <scratchpad>/copy`, then an offline
   install there (unverified; it may need the network). The copy has no `.git`, so hooks
   and git-based checks may fail there; say so next to those numbers.
2. **Compare `git status --porcelain`** with `evidence/status-0.txt` after each run.
   Test runs often leave `.snap` files, `test-results/`, `playwright-report/`,
   `coverage/` or `.dart_tool/` changes. Write any difference in `timings` and tell the
   user. Never revert or clean it.
3. **Sample the idle load** (below) 3 times, 2 s apart. Write the median.

## Sampling CPU load

Sample at the start, once in the middle and at the end of each timed run. Record the
median and the top CPU consumer that is not the test run.

```powershell
# Windows, PowerShell. Total CPU % now:
(Get-CimInstance Win32_Processor | Measure-Object -Property LoadPercentage -Average).Average
# Top consumers NOW. Get-Process CPU is cumulative seconds since start, so take two
# samples 2 s apart and sort by the difference:
$a = Get-Process | Select-Object Id,CPU; Start-Sleep 2
Get-Process | ForEach-Object { $p = $_; $o = $a | Where-Object Id -eq $p.Id; [pscustomobject]@{Name=$p.Name; Delta=[math]::Round(($p.CPU - $o.CPU),2)} } | Sort-Object Delta -Descending | Select-Object -First 5
```

```bash
# Windows, from Git Bash: wrap the same line.
powershell -NoProfile -Command "(Get-CimInstance Win32_Processor | Measure-Object -Property LoadPercentage -Average).Average"
# Linux (tried on Linux under WSL2): load = 100 - idle; also compare /proc/loadavg with nproc.
top -bn2 -d1 | grep "Cpu(s)" | tail -1
cat /proc/loadavg; nproc
top -bn2 -d1 -o %CPU | awk '/^top -/{n++} n==2 && /^ *[0-9]/' | head -5   # top consumers now
# WSL2: top and /proc/loadavg see only the Linux VM. They cannot see Windows processes,
# so a busy Windows program is invisible. Also sample the Windows side with powershell.exe;
# use the full Windows path if it is not on PATH:
powershell.exe -NoProfile -Command "(Get-CimInstance Win32_Processor | Measure-Object -Property LoadPercentage -Average).Average"
# macOS: not tried yet; check the output once. The first top sample is not valid, so
# read the second one.
top -l 2 -n 0 -s 1 | grep "CPU usage" | tail -1
top -l 2 -s 1 -o cpu -n 5 -stats pid,command,cpu | tail -5    # top consumers now
```

`ps %cpu` on Linux is an average over the whole process life, not current load, so it is
not used here.

`Win32_Processor.LoadPercentage` works on any Windows language. `Get-Counter` and
`typeperf` counter names are translated on non-English Windows; avoid them.

Load bands: idle < 20% · busy 20–50% · loaded > 50%. A loaded number is compared only
with numbers from the same band. Ratios and percent breakdowns hold up better than seconds.

## Commands

The run and timing commands per stack are in the stack profile ("Time one file"). Use the
repo's own script names (`package.json` scripts, `melos`, `Makefile`). Run a hook's
commands in the copy, never in the repo (hooks may fix or stage files).

Tags on every number (one legend for every file of the audit): **[M]** measured,
**[C]** counted (grep or reporter count), **[E]** estimated, **[NM]** not measured.

## The timings table (`timings`)

| What | Value | Tag | Command | Load at start / mid / end | Band | Top other consumer | Re-time isolated |
|---|---|---|---|---|---|---|---|
| full suite wall | … s | [M] | `…` | 8 / 31 / 12 % | busy | `<process>` | yes (ticket NN needs it) |

**Re-time isolated = yes** when a later ticket's acceptance criterion, estimate or
before/after claim will use the number. That ticket re-times it alone: idle band, the
one file or command only, median of 3 runs. Say this in the report next to the number.
