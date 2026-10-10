# Pitfalls — the rule each past mistake teaches

1. **Read every cover.** A cover from a name or a grep hit is a guess. Open it at the tip
   and write `path:line — '<title>'`; a second read re-checks every cover (Phase 3).
2. **Time under a known load.** CPU load next to every number; re-time alone any number
   a ticket will use (`timing.md`).
3. **Break-probe each cut candidate.** A shortened cover can still pass with the code
   broken: run 1 to 3 breaks in a scratchpad copy (`outputs.md` § Break probes).
4. **Classify from the body, never from the title.** A title that names one function
   while the body calls another goes under "Problems found on the way".
5. **Check install freshness before any run.** Stale → stop and ask.
6. **Say "static" or "runtime" next to every count.** Never add the two.
7. **Per-file reporter time may hold only test bodies.** Use the summary line for the
   phase split. Whole heavy files and global setup give back more time than single tests.
8. **Ask "can this test fail?"** Watch for a silenced `console.error`, a suite that only
   prints a report, and screenshot baselines for one OS only.
9. **Name the cause of a cluster.** When one class clusters, name the rule or script that
   causes it, with `file:line`. The fix is the rule, not only the tests.
10. **Keep judgement calls apart.** They are `open` and go to the report's Open
    questions. Only `cut` rows with a checked cover count as cuts.

Out of scope: measuring the agent pipeline (how often a build step re-runs the same
checks). Offer it as a separate ask.
