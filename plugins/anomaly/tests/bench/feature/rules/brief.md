# Brief: the fixture skill `tidy`

The ledger of the rules the skill text must keep or leave out. A rule that is in the skill
text and in no row of the ledger is unbriefed.

Size budget (id `SIZE`): the skill text is at most 1536 bytes.

| id | rule | verdict |
|---|---|---|
| K01 | Read the ticket before anything else | keep |
| K02 | State the goal in one sentence at the top of the reply | keep |
| K03 | Ask no question the ticket already answers | keep |
| K04 | Name every changed file, with the line of the change | keep |
| K05 | Say what was not checked | keep |
| K06 | Keep each reply under 40 lines | keep |
| K07 | Quote the line a claim rests on | keep |
| K08 | Mark every guess as a guess | keep |
| K09 | List the open items last | keep |
| K10 | Stop at the first failing check and report it | keep |
| X1 | Run the whole suite again after every edit | drop |
| X2 | Ask for a review after every small edit | drop |
| X3 | Copy the ticket text into the reply | drop |
