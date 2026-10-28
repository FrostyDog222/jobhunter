# Performance audit - jobhunter

Audited 2026-10-27 and 2026-10-28 on the maintainer's PC (Windows 11, Python 3.14.6, 4 real job boards
over the internet, a live 250-row SQLite database). Every number below was measured here; where
something could not be measured it says so. Scope is this repository only.

## A. Executive summary

| | |
|---|---|
| Projects discovered / audited | 1 / 1 (a single FastAPI app + a scheduled worker; no monorepo, no submodules) |
| Findings | 9 - **P1: 1**, **P2: 5**, **P3: 2**, examined-and-closed: 1 group |
| Fixed | 4 (JH-01, JH-02, JH-04, JH-05); 1 partly (JH-07: diagnostics only, cause unknown) |
| Tried and reverted (no gain) | 1 (JH-03) |
| Open, needs a decision or more data | 3 (JH-06, JH-07, JH-09) |

**What moved, measured on real runs**

- A search kept reading ~200 ads it had already read and thrown away, every run. Same 2-term search
  twice in a row: **3m02s -> 52s** on the second run (reading 2m42s -> 28s). The first scheduled run
  with the fix was *learning* and took 23m40s; the dashboard's own 23-term search went
  **894s -> 234s** (reading 731s -> 98s) with the memory warm.
- `/api/jobs` (the dashboard's data call): **p50 210 ms -> 29.8 ms** (-86%), p95 247 -> 40 ms.

**What did not move.** Searching the four boards concurrently was built, measured (find 140s -> 141s)
and reverted: two of the four share one browser thread, which is the real critical path (JH-03).

**Remaining critical risks:** none critical. The next biggest cost is the two browser boards
(BestJobs + OLX = about 4.5 of the ~6 minutes finding takes) - JH-06.

## B. Project inventory

| | |
|---|---|
| Path | `C:\Users\vuici\Desktop\jobhunter` (git `main`, 1 commit ahead of `origin/main` before this audit) |
| Stack | Python 3.14, FastAPI 0.141 + uvicorn, Jinja2, stdlib `sqlite3` (WAL), httpx, Playwright 1.63 (Chromium) |
| Shape | `app.py` 4.1k lines (routes, DB, PDF), `scrape.py` (4 boards), `llm.py` (provider chain + prompts), `prefill.py` (browser automation), `auto.py`/`auto_apply.py` (scheduled run), `health.py`, `templates/` (dashboard 3.5k lines inline JS) |
| Entry points | `run.bat` -> `app.py` (port 8777); Windows Task Scheduler: `jobhunter scheduled search` (weekly trigger, daily in practice) and `jobhunter keep signed in` (every 2 h) |
| Data | `db.sqlite` 2.5 MB, 250 jobs (+ `passed_over`); JSON state files; no external DB |
| External | 4 job boards (httpx for eJobs/Hipo; Chromium for BestJobs/OLX), up to 4 LLM providers (groq, gemini, mistral, nvidia) |
| Tests | `python test_app.py` - one file, ~7k lines, **17.9 s**, prints `ok` or the first failure |
| Existing perf tooling | none before this audit; `auto.log` now has a per-phase `timing:` line and `/health` shows it |

Not present, so not audited (and not padded into the report): frontend bundles/build step, React or any
framework, ORM, Docker/CI/CDN, queues, vector search, GPU/local models, authentication (single local
user; the server refuses foreign `Origin`s and is unchanged).

## C. Findings register

| ID | Sev | Conf. | Finding | Status |
|---|---|---|---|---|
| JH-01 | **P1** | confirmed | A search read and then discarded the same ~200 non-remote ads on every run | **Fixed** |
| JH-02 | P2 | confirmed | `/api/jobs` re-ran the adult-work regex over every description on every request | **Fixed** |
| JH-03 | P2 | confirmed (negative) | Boards searched one after another - concurrency gives no gain | **Reverted** |
| JH-04 | P2 | confirmed | Two false alarms from the new monitor (mixed baselines; one-row sample) | **Fixed** |
| JH-05 | P2 | confirmed | After JH-01, 45 of 88 reads were still thrown away (unreadable / too old / same ad twice) | **Fixed in part** - see below |
| JH-09 | P3 | inferred | ~26 of 34 "nothing readable" drops are probably *stub* ads (< 200 chars), re-read every run | Open - counters added |
| JH-06 | P2 | high | BestJobs + OLX serialise on one browser thread: ~4.5 min of each run | Open - recommendation |
| JH-07 | P3 | medium | OLX intermittently returns a page with no result count (5 of 56 terms once; 0 of 12 the next pass) | Open - diagnostics added |
| JH-08 | - | - | Examined, nothing actionable (list in F) | Closed |

### JH-01 - re-reading ads the work-mode filter had already turned away (P1)
- **Where:** `app.py` `_search`: the "Remote" filter runs *after* each ad is read, and rejected ads were
  never stored, so `known` never saw them.
- **Evidence:** two identical searches back to back: 247 ads found, **197 and 190 read and dropped, 0
  kept**, 2m25s then 2m42s reading. One scheduled run logged "2 of 1924 ads could not be read" - it read
  ~2,000 ads to keep a handful. Reading was 69% of the first timed scheduled run (16m26s of 23m40s).
- **Fix:** a `passed_over(url, why, at)` table; rejected ads are remembered 14 days, keyed by the filter
  that rejected them (a "not remote" verdict is ignored when asking for on-site or any mode).
- **Risk / trade-off:** an employer who edits an ad into a remote one is invisible for up to 14 days.
- **Verified by:** end-to-end test on a throwaway DB (second search reads nothing; on-site and any-mode
  are not answered from the remote memory; 15-day-old verdicts are re-read); mutation-checked; real data (D1, D2).

### JH-02 - `/api/jobs` was 90% one regex (P2)
- **Evidence (cProfile, 20 calls):** `adult_job` = 4.67 s of 5.19 s; 0.9 ms per ad; 238 ms for 250 ads;
  linear, so ~2 s at 2,500 ads.
- **Fix:** `adult_job` memoised on its input text (`lru_cache(2048)`); keyed on the text, not the URL, so
  an edited ad is re-evaluated; bounded (a few MB).
- **Verified by:** identical answers on all 250 stored ads and on edge inputs (0 mismatches); a test that
  pins parity with the raw regex, cache hits, edited text, and the bound; mutation-checked.

### JH-03 - boards concurrently: no gain, reverted (P2, negative result)
- **Hypothesis:** finding was 6m16s as 1m41 + 2m57 + 1m13 + 25s one after another, so overlapping the
  boards should approach the slowest (~3 min).
- **Measurement (same 23-term query, same data):** find **140 s sequential -> 141 s concurrent**.
  Per board: BestJobs 44 -> 141 s, OLX 75 -> 139 s, eJobs/Hipo unchanged (10/11 s). BestJobs and OLX both
  go through the single browser worker thread (Playwright's sync API is bound to its creating thread), so
  they only interleave.
- **What this does and does not show.** Three later runs of the *same sequential code* took 135, 140 and
  170 s - the run-to-run spread (about 25%, mostly OLX: 75 s, 78 s, 111 s) is larger than the most
  concurrency could ever save. That ceiling is only what could overlap with the browser work, eJobs + Hipo,
  about 14-21 s. So the honest conclusion is **no detectable gain, and a structural ceiling of ~15%**, not
  "proved no effect".
- **My error:** I estimated ~3 minutes by adding board times without checking that two share one resource.
- **Action:** reverted completely, including its test: a change that cannot be shown to help is only added
  risk (one more ordering concern for duplicate resolution and warnings).

### JH-04 - the new monitor cried wolf twice (P2)
Both found in one real run's warnings, both caused by my earlier work, not by the sites:
1. `olx returned about 7 ads per search term where it usually returns 22`: a board's yield depends on
   *which terms* are searched (14-22/term for 2 everyday terms, 7/term for 23 incl. rare ones) and the baseline
   mixed them. **Fix:** baselines are keyed by a fingerprint of the *set* of terms.
2. `bestjobs: every company empty - parser broken`: `health()` runs on the rows a search *kept*, which after
   JH-01 is often 1-2 rows, and employers can hide their name. **Fix:** the company check needs >= 5 rows; a
   blank *title* still flags at any size (an ad always has one).
- **Verified:** the same real search that raised both now returns `warnings: []`; tests for each.

### JH-05 - what was still read for nothing after JH-01 (P2)
- **Evidence:** the next real run read **88 ads in 1m38s and kept none**: 43 not remote (newly
  remembered), **45 other**: 36 pages that loaded with nothing readable, 4 too old, 5 the same ad twice.
  Found by adding per-reason counters to `hydrate` (also shown in the `timing:` line).
- **Fix:** ads past their date or closed are remembered 14 days (a date does not un-pass); a page that
  answered with nothing readable is remembered **3 days** only, since it can be a glitch or a layout the next
  update reads. A page that never answered is weather and is not remembered.
- **Trade-off:** after a site layout change is fixed by an update, affected ads can stay skipped for <= 3 days.
- **Verified so far:** unit/e2e tests incl. both expiries (mutation-checked); and on real data the memory is
  being written (`passed_over`: 2,182 `mode:remote`, 8 `unreadable`, 4 `gone`). **Not yet verified on real
  data:** the *reduction* - the final run was the first to write these two kinds, so it still read them; only
  the next run shows the skip. The 16:00 scheduled run will.
- **A correction to my own reading:** only 8 of the 34 "nothing readable" drops were pages that answered with
  nothing. The label lumped three different things; it is now split into `no answer`, `nothing readable` and
  `too short`, so the next `timing:` line says which is which (JH-09).

### JH-06 - the browser is the critical path (P2, open)
BestJobs (1.7 s/query) and OLX (2.9-4.4 s/query) share one Chromium thread: about 4.5 of the ~6 minutes
finding takes on a 56-term run. A second browser (own Playwright instance + thread) would let them overlap:
estimated saving ~1.6 min/run (~18% once reading has shrunk), at the cost of a second Chromium process
(memory ~150-300 MB, not measured). **Not done:** the gain is moderate and the cost is a second heavy process;
worth doing only if find time matters after the next scheduled run's timing is in.

### JH-07 - OLX sometimes returns a page with no result count (P3, open)
Scheduled run 2026-10-27: one `olx: ... neither a result count nor any ads` warning. Replaying the 56 terms:
5 terms flagged (#26-29 consecutive, #56), each costing the 8 s wait and returning 0 ads; replaying terms
20-31 immediately after: 0 of 12. Not term-specific, not reproducible on demand. A throttle, a check and a slow
render are different problems and I never caught the page. **Added:** the page's title and first lines are now
recorded in the warning, so the next occurrence explains itself (visible in the Health tab). No retry/back-off
was added for a cause not yet seen.

## D. Before / after (real measurements)

Conditions: live boards, warm DB, same machine; one run per cell unless stated (single runs - treat
differences under ~10% as noise). Searches were real and wrote to the real database.

**D1. Same 2-term search, run twice back to back** (`customer support, operator call center`, remote)

| run | read | total | skipped unread |
|---|---|---|---|
| old code, #1 | 2m25s | 2m44s | - |
| old code, #2 | 2m42s | 3m02s | - |
| new code, #1 (learns) | 2m55s | 3m22s | 0 |
| new code, #2 | **28s** | **52s** | 194 |

**D2. The dashboard's own 23-term search**

| run | find | read | score | total | skipped | note |
|---|---|---|---|---|---|---|
| 15:29, old code | 140 s | 731 s | 22 s | **894 s** | 191 | boards sequential |
| concurrent-boards experiment (reverted) | 141 s | 180 s | 3 s | 325 s | 963 | find unchanged |
| JH-01 memory warm | 135 s | 98 s | 0 s | **234 s** | 1103 | 45 + 43 read for nothing |
| + JH-05 code, first run with it (learning run for the new reasons) | 170 s | 78 s | 0 s | 249 s | 1137 | 34 + 4 + 4 + 18 read for nothing |

Find time on the sequential code: **135, 140, 170 s** across three runs of the identical query - about 25% spread
(OLX alone 75-111 s). Single-run differences below that are noise; the reading figures (731 -> 180 -> 98 -> 78 s)
move far more than the noise.

**D3. Scheduled run (56 terms)**

| run | total | find | read | score | skipped |
|---|---|---|---|---|---|
| 2026-10-26 17:00 | 28m45s (no per-phase timing existed) | | | | |
| 2026-10-27 17:00 (first timed, mostly learning) | 23m40s | 6m16s | 16m26s | 57 s | 850 |
| 2026-10-28 16:00 | *not run yet - the first steady-state figure; read it from `auto.log` / the Health tab* | | | | |

**D4. Final identical 23-term run, JH-05 in place:** `total 4m09s · find 2m50s (bestjobs 44s, olx 1m51s, ejobs 9s, hipo 5s) · read 1m18s (skipped 1137 already judged) (dropped after reading: 34 nothing readable, 4 too old, 4 same ad twice) · score 0s`,
`warnings: []`. Reading fell 98 -> 78 s from the 43 -> 18 newly-rejected not-remote ads; the extension's own effect needs the *next* run (see JH-05).

**D5. Web layer** (local server, 30 requests after 2 warm-ups, `/api/jobs` re-measured after JH-02)

| endpoint | before p50 / p95 | after p50 / p95 | payload |
|---|---|---|---|
| `/api/jobs` | 210.3 / 246.7 ms | **29.8 / 40.4 ms** | 215 KB (unchanged) |
| `/` | 3.7 / 4.9 ms | 2.5 / 3.2 ms (noise) | 222 KB |
| every other read-only endpoint | 0.9-10.3 ms | not re-run - unchanged code | <= 15 KB |

In-process handler: 238.4 ms -> 25.7 ms (-89%). The first request after a server start pays ~190 ms once
to fill the cache.

## E. Change log

| File | Change |
|---|---|
| `app.py` | `passed_over` table; `_passed_over`/`_pass_over`; skip before reading (work mode / gone / unreadable); `_timing_report` (+ `skipped_unread`, `read_dropped`); per-term-set baselines in `_check_board_counts`; `SEARCH_LOG`; `/health`, `/api/health` |
| `scrape.py` | memoised `adult_job`; `hydrate` reports per-reason drops and what to remember; `health()` company check needs >= 5 rows; OLX card/grid extraction, anchor choice, wait-on-count, drift notes incl. page text; images/fonts not fetched |
| `health.py` (new) | the search record, issue classification, per-board rows, `fingerprint()` |
| `auto.py` | `timing:` log line incl. skipped / dropped-after-reading; run tags itself `scheduled` |
| `llm.py` | `WAIT_EVENTS`: what each provider that did not answer cost |
| `templates/health.html`, `base.html`, `lang.py`, `README.md`, `share.py`, `.gitignore` | the Health tab, its Romanian, docs, and keeping the new state files out of the zip/repo |
| `test_app.py` | suite redirects the search log, board baselines **and the database** to throwaway files (it was writing fake searches into the real log); new tests for every item above |

**Database migration:** one additive table, `CREATE TABLE IF NOT EXISTS passed_over(url, why, at, PRIMARY KEY(url, why))`,
created lazily with the rest of the schema. No existing table or column changed. **Rollback:** `DROP TABLE passed_over;`
(the app recreates it empty and simply re-reads once) - or revert the commit; older code ignores the table.

**Dependencies / config:** none changed. No new packages (a scraping library, Scrapling, was evaluated and
rejected earlier: parsing is 1.7% of a read).

**Compatibility:** no API shape changed except additions (`timing`, `read_dropped` in the search result;
`/api/health`). The adult filter returns identical answers (checked on all stored ads).

## F. Verification results

| Command / check | Result |
|---|---|
| `python test_app.py` (after every change) | **passed** each time (17.9 s) |
| Mutation checks (change reverted on purpose, suite must fail) | JH-01 skip, JH-02 memo, JH-05 TTL and remembering, OLX anchor fix: **each caught** by a named assertion |
| Real database untouched by the suite (sha256 before/after) | **identical** |
| Real searches (2- and 23-term, one 56-term OLX pass, one 31-term OLX replay) | ran; results in D1-D2, JH-07 |
| `/api/jobs` parity vs raw regex on 250 stored ads | 0 mismatches |
| Frontend build / lint / typecheck / Docker / load test | **not applicable / not run** - none exist; no load test was run (the live boards are third parties) |
| Final identical 23-term run with JH-05 | ran: D4; `warnings: []`. Skip *reduction* from JH-05 **not yet verifiable** (learning run) |

## G. Outstanding work

1. **Read tomorrow's `timing:` line** (Health tab -> "Where the time went"): it is the first steady-state
   measurement of the scheduled run. Expect reading to be small; if find (6 min) is now the largest block, JH-06 is the next lever.
2. **JH-07 / JH-09:** wait for the next "neither a result count nor any ads" warning (it now carries the page's own words), and
   read the next `timing:` line's `dropped after reading` split (`no answer` / `nothing readable` / `too short`). If `too short`
   dominates, remember stubs like unreadable pages (3 days) - not before.
3. **Not verified:** production-like load (single-user app, none needed); memory use of the server over days
   (not measured); JH-05's 3-day expiry has not been exercised against a real site-layout change.
4. Changes are **uncommitted** (the maintainer commits); one earlier commit is not pushed.

## H. Recommendations (next most valuable first)

1. Re-measure after one or two scheduled runs; decide JH-06 on the real `find` share. *Impact:* ~1.6 min/run;
   *cost:* second Chromium; *risk:* moderate (thread ownership - the app already hit a greenlet bug here once).
2. If `nothing readable` stays large on BestJobs/OLX, read it as *closed ads* and skip them at discovery, not after a
   2 s browser read. *Confidence:* medium - needs the per-board split (`hydrate` counts `unparsed` per board but does not log it yet).
3. Nothing else on the web layer, DB or model calls is worth touching at this data size (see below).

### Examined, nothing actionable (JH-08)
- Startup: `import app` 2.4 s (0.6 s is FastAPI itself); no startup work in the app.
- Endpoints: all but `/api/jobs` are 1-10 ms.
- Romanian pages: 15 ms render and ~105 KB of embedded translations per page - negligible on loopback.
- LLM calls: scoring asks for 1,500 tokens -> 60 s timeout; the slowest measured provider took 35-48 s under load, so
  tightening it would risk cutting off real answers; the circuit breaker already rests a provider after one timeout.
- SQLite: 2.5 MB, 250 rows, primary-key lookups; an extra index would add write cost for no measurable read gain.
- Keep-alive task: ~25 s every 2 h of Chromium by design (sessions lapse otherwise).
- Scoring concurrency already adapts to provider refusals.
