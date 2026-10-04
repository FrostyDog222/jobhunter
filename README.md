<!-- GitHub strips CSS out of a README, so the background cannot be set around the image -
     it has to be part of it. static/banner.png is the artwork on its own navy, edge to edge. -->
<img src="static/banner.png" alt="jobhunter - Find Jobs. Tailor Your CV. Get Hired." width="100%">

# jobhunter

Finds jobs on the Romanian boards, scores each one against your CV, writes a CV tailored to the ad,
and applies for you where the board allows it.

Everything stays on your PC. The only thing that leaves is the job ad and your profile, sent to
whichever AI model you choose to score them — and if you run Ollama, not even that.

**Windows only.**

## Getting it

Two ways — pick either. No GitHub account needed for either one.

**1. Download it yourself.** Open
[github.com/FrostyDog222/jobhunter](https://github.com/FrostyDog222/jobhunter), press **Code →
Download ZIP**, and unzip it somewhere short like `C:\jobhunter`.

**2. Or let PowerShell do it.** Paste this in and it downloads and unpacks itself onto your Desktop,
into a folder called `jobhunter-main`:

```powershell
$d = [Environment]::GetFolderPath('Desktop'); $z = "$d\jobhunter.zip"
Invoke-WebRequest https://github.com/FrostyDog222/jobhunter/archive/refs/heads/main.zip -OutFile $z
Expand-Archive $z -DestinationPath $d -Force; Remove-Item $z
```

Either way, you end up with a folder of files. The name does not matter — the app runs from whatever
folder it is in. Then carry on to **Start**, below. (If you have git, `git clone
https://github.com/FrostyDog222/jobhunter.git` gets you the same thing.)

**Keep it out of OneDrive.** Windows often puts the Desktop inside OneDrive, and OneDrive syncs the
database while the app is writing to it, which is how a job list gets corrupted. If yours is
synced, move the folder somewhere local like `C:\jobhunter` before you start.

## Start

### 1. FirstTimeSetup.bat — this one first, before anything else

Double-click it. On a PC with nothing installed it takes about five minutes, once, and needs an
internet connection. It installs:

| | |
|---|---|
| **Python** | if the PC does not already have 3.10 or newer — through the Windows package manager, or straight from python.org if that is not available |
| **The app's packages** | the web server, the PDF reader, the browser driver, into a `.venv` folder of its own so nothing else on the PC is touched |
| **Chromium** | the browser the app uses to read job pages, fill forms and make PDFs |

Then it runs the app's self-check and tells you whether everything actually works, rather than
leaving you to find out later. At the end it offers to start the app.

Nothing of yours is sent anywhere, and nothing is installed system-wide except Python itself.

### 2. run.bat — every time after that

It opens the dashboard at http://127.0.0.1:8777 by itself. Keep the black window open while you
use the app; closing it stops the app.

run.bat installs nothing. If the setup is missing — a fresh copy, or a folder carried over from
another PC whose `.venv` cannot run here — it says so and offers to run FirstTimeSetup for you,
then starts the app in the same window. It also mentions it if the PC's Python has moved on from
the one the app was built against.

## First time: three steps

The dashboard shows a checklist until all three are done.

1. **Choose an AI model and paste its key.** Open *Settings*, pick a provider, and use the
   *Get a key* link beside it — it goes straight to the page where that provider hands out keys.
   Paste the key and press *Save & test*; it makes a real call and tells you whether it worked.

   | provider | cost | where the key comes from |
   |---|---|---|
   | groq | free tier | https://console.groq.com/keys |
   | gemini | free tier | https://aistudio.google.com/apikey |
   | mistral | free tier (smaller models) | https://console.mistral.ai/api-keys |
   | nvidia | free after sign-up | https://build.nvidia.com/settings/api-keys |
   | openrouter | some free models | https://openrouter.ai/settings/keys |
   | ollama | free, runs on your PC, no key | https://ollama.com/download |
   | anthropic | paid | https://platform.claude.com/settings/keys |
   | openai | paid | https://platform.openai.com/api-keys |

   **Add more than one.** Keys sit side by side, and when one runs out of free quota the next
   takes over in the middle of a search. Two or three free keys are enough for daily use.

2. **Fill in your profile.** On the *Profile* tab, upload your current CV (PDF, DOCX or TXT) and
   the app reads it into the fields. Check them: it copies, it does not invent, so anything it
   could not find stays blank. *Suggest improvements* proposes rewrites one at a time; take the
   ones you like. It may only sharpen what you wrote — a suggestion that adds a number your profile
   does not contain, or a skill you never listed, is dropped before you see it. Where a number is
   genuinely missing it leaves `[X]` for you to fill in rather than inventing one.

   Declare every language you work in. A job that demands a language you have not listed is
   skipped before it is scored.

   The *Application answers* card holds your salary expectation, notice period and earliest
   start. Boards ask for these, and the app answers with exactly what you wrote there.

3. **Search.** Pick a role family from *Preset* — your own job titles are at the top of the
   list — or type your own terms, separated by commas. Then *Search & score*.

   Romanian boards index Romanian wording, so search both: `suport clienti, relatii clienti,
   customer support`.

## Finding jobs

Type what you are looking for and press *Search*. Four job boards are searched at once: **eJobs**,
**BestJobs**, **Hipo** and **freehire** (international and remote).

Every job gets a score out of 100, a one-line reason, what you **bring** to it and what the
**gaps** are. *Best for you* is everything at or above your score floor, which you set under
*Settings*.

**The search box suggests as you type** but never restricts — type anything and it is searched
exactly as typed. It starts from your own job titles rather than anybody else's, and the *Pick a role
family* list offers them one at a time or **All of these** at once. Whatever you type is remembered
as you leave the box, so an edit is not lost if you never press Search. *Settings → Suggest terms from my CV* reads your profile and proposes job titles
you might not think of, each showing the line in your CV it came from. Nothing is filled in until
you click it.

Lists show 20 jobs to a page. The filter box narrows what is already found, and ignores diacritics —
`iasi` finds `Iași`.

### What is on a card

| | |
|---|---|
| **score and reason** | out of 100, with what you bring and what is missing |
| **#N today** | where this sits in the ranking, when the scores tie |
| **applicants** | how many have already applied. Green under 25, red over 150. BestJobs only |
| **replies** | a green badge where the employer is known to answer applications. BestJobs only |
| **new / old** | green for the first week after posting, amber after |
| **closes in N days** | the employer's own closing date, where they published one |
| **salary** | marked `(est.)` and dimmed when it is the board's guess rather than the employer's figure. **Do not quote an estimate back to an employer** |

**Just pulled in** shows what the last search brought in, so you can see today's arrivals without
reading the whole list. The **Few applicants** tile shows just the quiet ones. *What should I do today?* picks three jobs
worth sending now and says why, and puts a **#1, #2, #3** on every card above your floor so you can
see the order while you work down the list. It exists because the score cannot separate the top:
scoring rates each ad on its own, so the best are routinely all the same number. Advice only — the
list is not re-sorted, nothing is hidden and no score is rewritten.

### Narrowing it down

**What the filters left out.** A panel under the tiles names what never reached your list: the
languages that keep being asked for, and which of your own skip rules dropped the most. A count tells
you the app is working — this tells you something you can act on. On one run, 68 ads were dropped
purely on language: Italian 16, German 15, French 11. Sixteen more jobs would have been open with
one of them.

**Skip job families you do not work in.** Under *Settings*, list families like `engineer`, `sudor`,
`contabil` or `sofer`. Ads whose title names one are never opened or scored. It starts empty.

Two things it will not do: it never skips an ad that names the job you actually searched for
(including the Romanian or English wording of it), and it only takes job families — never a city, a
language or a seniority word. Every search tells you how many it skipped.

**Say when you can work.** *Can work weekends* and *Can work shifts or nights* on your profile, each
set to yes, no, or left blank. These never go on your CV. They are used only where an ad asks for
weekend or shift work, and they let the app answer that question on an employer's form. Left blank,
nothing is claimed either way.

### When jobs disappear from your list

Ads are cleared out as they close. Where the employer published a closing date, that date decides.
Where they did not, the ad is dropped **thirty days** after it was posted.

**Where a job is.** Pick a city, a county, or neither — and a genuinely remote job shows up whatever
you picked, even when the ad names an office in another country. It reads the wording, not the word:
*fully remote*, *remote-first*, *work from home*, *telemunca* count; *"the possibility to work
remotely"*, *"remote support tools"* and *"nu poate fi desfășurată remote"* do not. Whatever you choose is enforced twice: ads
from somewhere else are dropped as they are found, **and the scheduled run will not apply to them**.
That second half used to be missing: it applied to anything above your score floor wherever it was,
because the search only filters what it *discovers* and your list is full of ads found before you set
a filter. A job whose location cannot be read is not applied to while a filter is set, and the run
says how many it held back.

**Anything at or above your score floor is never dropped for being old**, and neither is anything
you applied to, tailored, opened or skipped. A search tells you if it dropped something you would
have wanted.

**Check what is still open.** *Settings* has a monthly check that asks each board which of your
saved jobs it still has, and removes the ones it says are gone. It is **off by default** because it
deletes; there is a **Check now** button to run it by hand. It only removes a job when a board
clearly says so — anything it cannot read is kept.

## Tailored CVs

*Tailor CV* rewrites and reorders **your own** facts for that one ad and saves a PDF. Nothing is
invented: no employer, date, degree, tool or achievement that is not in your profile.

- **Language** follows the ad by default — a Romanian ad gets a Romanian CV — or you can fix it
  to one language under *Settings*.
- **Template**: pick a default under *Settings*, or leave *Ask me every time* on and choose per
  CV. Every template is plain text underneath, with no tables or columns, so applicant tracking
  systems read it correctly.

## Applying

| where the job is | what happens |
|---|---|
| eJobs, BestJobs, Hipo | The app applies for you, after you confirm. Tick several and send up to 50 at once |
| Employer forms (Greenhouse, Lever, Ashby, Workable, SmartRecruiters and others) | Opens the form with your details filled in and your CV attached, then stops. You check it and press submit |
| Ads that send you to the employer's own site | Marked *apply on the employer site* and opened, never submitted. Most Hipo ads and many BestJobs ones are this kind |
| Anything else | Opens the ad and your tailored CV side by side |

The **You apply yourself** tile gathers everything you have to send by hand. None of it is ever
picked up by batch apply or the scheduled run.

**Sign in first**, under *Settings → Job board accounts*. A browser window opens and you type your
password into the board's own page, not into this app. All three boards need it before they can
apply.

**What a board application sends is the CV on your board profile, not your tailored PDF.** Keep
those profiles up to date — the links are under *Settings*.

**Screening questions.** Some eJobs ads ask their own. Salary, notice period and start date come
from your *Application answers*; if anything is left blank the app stops and opens the form for you.
The salary figure you save goes to every employer that asks, so set one you would stand behind.

**Hipo confirms nothing.** When an application goes through, Hipo just removes the apply button —
no message, no badge. The same thing happens when a posting closes, and the two cannot be told
apart, so the app reports "either it closed or you already applied" rather than guessing. *Import my
Hipo applications* settles it.

### Staying signed in

Board sign-ins expire at different rates: eJobs renews itself, BestJobs lasts months, and **Hipo
lapses after six hours** without a visit. *Keep me signed in* visits every two hours to hold it. It
does not wake a sleeping PC, so a machine that sleeps overnight will have lost the Hipo session by
morning.

**Saving a board password (optional, off).** Under *Settings → Job board accounts* you can save a
sign-in so the scheduled run can log back in on its own when a board has signed you out. It is
stored in one file on this PC, encrypted so only your Windows account can read it, and is never
sent anywhere except the board's own login page. It is left out of the shared zip and the
repository.

Worth knowing before you do: a password is worth more than a cookie — it does not expire, it often
opens other sites too, and it can change the account's email. Encryption protects a copied file, not
something already running on your PC as you. **Not trusting a tool from the internet with your
password is a perfectly sensible choice** — leave it empty and sign in by hand; nothing else
changes.

## The scheduled run

Under *Settings → Scheduled run*, Windows can run your search on its own, so the list is already
searched and scored when you open the app. It works with the app closed, and a run missed because
the PC was off happens the next time it is on.

Pick any days of the week and a time. By default it searches and scores, and leaves applying to you.
Its search box has the same role-family picker as the one at the top, plus *Use my job titles* and
*Suggest terms from my CV*, so you are not retyping what you already set up above — and the same
city, county and freehire filters, so the unattended run searches for what you actually asked for
rather than a subset of it.

Worth thinking about rather than ticking every day: each run spends AI quota whether or not you look
at the result, and a job is posted once rather than daily — so seven days a week costs seven times
as much for mostly the same jobs.

### Applying without you there

A second switch, off until you turn it on, and it asks again before it takes effect. When it is on,
the run also applies to the best of what it found:

| | default |
|---|---|
| boards | eJobs, BestJobs and Hipo. Never an employer form |
| score | 85 or above, your choice |
| how many | 5 per run, up to 50 |
| which jobs | only ones you have not touched |
| screening questions | marked and left for you |

Ticking the switch shows you **the actual jobs that would go out** at your current settings, by name
and employer. If you change the score or the cap afterwards, it asks again.

Think about it first. **An application cannot be recalled.** It sends the salary figure from your
profile and the CV on your board profile, not a tailored one, and you find out afterwards.

Whatever it sent is listed in the panel next time you open the app, along with what the search
found — and under it, **Recent runs**: the last twenty, each with what it found, what it sent, and
**why anything failed**. A run that quietly stops applying looks exactly like a quiet week until you
can see the week.

## The AI model

Pick a provider under *Settings* and paste its key — the *Get a key* link beside each one goes
straight to where they hand them out, and several are free. Press *Save & test* to check it works.

If you set up more than one, the app uses them in order and moves to the next whenever one is busy
or out of quota, so a free tier running dry does not stop your search.

If your floor sits above anything the current model has ever given, the dashboard says so instead of
just showing you an empty list — that is a setting to lower, not a market with no jobs in it.

**Scores only compare within one model.** The same ad can score 85 from one model and 35 from
another, so your score floor means something slightly different if you change model. The app records
which model scored each job and quietly re-scores anything that came from a different one, so your
list settles back onto one scale by itself.

**If a model stops working**, the app finds a replacement for you: it asks the provider what it
currently offers and tries them until one answers, then tells you in the AI panel which it picked. A
free model is only ever replaced by another free one, so this never starts costing money.

**Test which model is best** scores one real job from your list with each of that provider's models
and shows which worked and how fast. It asks first, because it spends one call per model, and it
changes nothing by itself — it fills in the box and you press *Save & test*. **Find one that works**,
next to the model box, does the same on demand.

Bigger is not better: an 8b model has done the same job correctly in 1.2 seconds where a 550b model
took 30.

## After you apply

Everything you applied to is kept in the **Applied** view, newest first with the date it went out,
20 to a page. Applied jobs cannot be deleted or changed — that list is your record of what you sent,
and it is what stops the same job being offered back to you.

**What the boards say happened.** Press *Ask the boards what happened* and the app reads each
board's own verdict onto the card:

| | |
|---|---|
| **with them, not opened yet** | sent, nobody has looked |
| **opened by the employer** | somebody has read it |
| **closed** | rejected, withdrawn or the posting is over |

The board's own wording is on hover, with when it was last checked. Nothing here needs keeping up to
date by you. On eJobs a very long history only reads the most recent page.

**A nudge after ten days.** Every applied job shows how long it has been waiting — *sent today*,
*waiting 4 days* — and after ten days the line turns amber to say it is worth following up.

*Mark applied* is for applications you sent outside the app; *Undo* works for two minutes if you
click it by mistake. **Import my Hipo applications**, under *Settings → Job board accounts*, copies
your Hipo history in with Hipo's own dates, so jobs you applied to by hand stop showing as still to
do.

## Getting a newer version

Double-click **Update.bat**. It downloads the current code from
[github.com/FrostyDog222/jobhunter](https://github.com/FrostyDog222/jobhunter) and replaces the
app's files with it. Nothing else is needed — no GitHub account, no git.

**It only ever touches the app's own files.** Your API keys, profile, job list, applied history,
board sign-ins, settings and generated CVs are left exactly as they are. Anything it does
replace is copied into `backup\<date>-<time>` first, so a bad update can be undone by hand.

It tells you what changed, and says nothing if you are already up to date. If the dependencies
changed it installs them for you. Close the app's black window and start it again afterwards.

If the folder is a git checkout it runs `git pull` instead, and says so.

By hand, if you would rather: `git pull` in a checkout, or download the zip again with one of
the commands under [Getting it](#getting-it) and copy the files over the top. Keep your own files
when you do — everything starting with a dot (`.env`, `.creds.json`, `.session.json`,
`.boards.json`), `profile.json`, `profile.previous.json`, `settings.json`, `db.sqlite`,
`photo.jpg`, `auto.log`, `auto_last.json`, and the `out` folder. **`.creds.json` is the one worth
naming twice**: it holds your board sign-ins, and it was missing from this list. That is the
bookkeeping Update.bat does for you, which is the reason to use it instead.

## Giving the app to someone else

Double-click **share.bat**. It makes `jobhunter.zip` containing the app and nothing of yours: no
API keys, no profile, no job list, no board sign-ins, no CVs. Send the zip; they unzip it to a
short local folder such as `C:\jobhunter` (not inside OneDrive) and double-click
**FirstTimeSetup.bat**.

Do not copy the folder by hand. It holds your keys and your signed-in sessions, and whoever
receives it could apply to jobs as you.

They can equally get it themselves from GitHub — see [Getting it](#getting-it) — which is the
better route, since it is always the current version. The zip is for handing it to someone with
no internet at that moment, or for pinning them to the version you are running.

## Erasing everything

At the bottom of the Profile tab, **Erase everything** removes every trace of you from this
folder: your profile and photo, every job found and scored, the applied history, the CVs written
for you, the board sign-ins, your settings, and the two Windows scheduled tasks. It asks twice
and the second answer has to be typed, because nothing here can bring any of it back — the
previous-copy file goes with the rest.

Two things it cannot reach: applications already sent to an employer stay sent, and your account
on eJobs, BestJobs or Hipo is untouched. It signs this app out of them; it does not close them.

Use it before handing the PC to someone else. Deleting the folder does the same job, apart from
the two scheduled tasks, which would stay behind and fail quietly on every run.

## Moving to a new PC (keeping your own data)

Copy the whole folder **except** `.venv` and `__pycache__`, then double-click run.bat on the new
PC — it will spot that the environment is missing and offer to set it up. Your profile, job
list, history and keys come along. Sign in to the job boards again; sessions do not survive the
move.

If you copied `.venv` too, nothing breaks: it cannot run on the new PC, and run.bat detects that
and rebuilds it.

## When something goes wrong

| what you see | what to do |
|---|---|
| The dashboard does not open | Wait for the black window to finish, then open http://127.0.0.1:8777 yourself. |
| "Python not found" | Run FirstTimeSetup.bat — it installs Python. If that fails, get it from python.org and tick *Add to PATH*. |
| "Windows protected your PC" | Click *More info*, then *Run anyway*. |
| "Setup failed" | Check the internet connection and run FirstTimeSetup.bat again. If it keeps failing, delete the `.venv` folder first. |
| "This copy has not been set up on this PC yet" | Answer Y — run.bat hands over to FirstTimeSetup and then starts the app. |
| "The AI model has used up its free quota" | Wait a few minutes, or add a second provider key. |
| "The API key was refused" | Paste the key again under *Settings*. |
| A board shows *not signed in* | Sign in again under *Settings*. Board sessions expire. |
| A search finds nothing on one board | Boards change their pages. The search reports which one failed; the others still work. Run Update.bat — a fix may already be out. |
| An update broke something | The files it replaced are in `backup\<date>-<time>`. Copy them back over the top. |

## For whoever maintains it

    FirstTimeSetup.bat  installs Python, the packages and Chromium, then self-checks
    run.bat             starts the app; hands over to FirstTimeSetup if it is not set up
    Update.bat          pulls the current code from GitHub, keeping your data
    share.bat           builds the clean zip for someone else

    app.py        routes, database, PDF rendering
    llm.py        provider table, failover, the prompts
    scrape.py     the four sources
    prefill.py    browser automation: sign-in, apply, form filling, reading application lists
    templates/    dashboard, profile, the CV, and templates/cv/*.css (one file per CV template)
    share.py      builds the clean zip
    update.py     the update, and the one list of what it may never overwrite
    auto.py       the scheduled run, started by Windows Task Scheduler
    auto_apply.py the applying step of that run, and the limits on it
    lang.py       the Romanian for every sentence in the app, keyed by the English
    creds.py      optional board sign-ins, encrypted to the Windows account (DPAPI)
    test_app.py   the whole suite; `python test_app.py` prints ok or the first failure
    restart.ps1   restarts the server while you work on it; nothing in the app calls it

    profile.json  your data          settings.json  your preferences
    db.sqlite     jobs and history   out/           generated CVs
    .env          API keys           .session.json  board sign-ins
    auto.log      what the scheduled run did         auto_last.json  its last summary
    .boards.json  which board states were last read  .shortlist.json the cached "today" answer
    .llm_down.json which providers are resting, and why - read by every run, not just this one

None of those leave the machine: `share.py` excludes every one, and `.gitignore` keeps them out of
the repository.

**Conventions worth knowing before you change something:**

- Job ads are untrusted input. Every prompt that sees one opens with a trust boundary and wraps the
  ad in `<JOB_POSTING>` tags, or `<JOB_LIST>` where a prompt is handed many at once. That raises the
  bar; it is not a sandbox.
- Requests carrying somebody else's `Origin` are refused. The server has no password, and several
  endpoints take no parameters — `/api/auto/run` sends real applications. No `Origin` at all is
  allowed: that is curl, the scheduled task and the test suite.
- Model ids are filtered to ids shaped like ids before being written, because the repair walk puts
  whichever model answers into `.env`.
- Anything the dashboard needs to know about the Python — the county list, which boards can be
  applied on — is rendered into the template rather than written out twice. The hand-kept copy went
  stale twice. `test_app.py` pins the remaining pairs and sweeps every `t()` string for a missing
  Romanian.

**Adding a CV template:** one CSS file in `templates/cv/`, first comment line
`/* Name - one-line description */`. It appears in the picker on the next reload.

**Adding a provider:** one line in `llm.PROVIDERS` if it speaks the OpenAI API, plus one in
`KEY_URLS` in `templates/dashboard.html` or its *Get a key* link renders dead. Optionally one in
`llm.KEY_PREFIX`, which catches a key pasted into the wrong box.

Check it still works: `python test_app.py`
