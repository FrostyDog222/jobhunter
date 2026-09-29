<!-- GitHub strips CSS out of a README, so the background cannot be set around the image -
     it has to be part of it. static/banner.png is the artwork on its own navy, edge to edge. -->
<img src="static/banner.png" alt="jobhunter - Find Jobs. Tailor Your CV. Get Hired." width="100%">

# jobhunter

A local job-hunting assistant for the Romanian market. It finds jobs, scores each one against
your profile, writes a CV tailored to the ad, and applies on the boards that allow it.

Everything stays on your PC except the calls to the AI model you choose — and with Ollama, not
even those.

## Getting it

The repository is public, so none of this needs a GitHub account or a login.

Easiest: open [github.com/FrostyDog222/jobhunter](https://github.com/FrostyDog222/jobhunter),
press **Code → Download ZIP**, and unzip it somewhere short like `C:\jobhunter` — not inside
OneDrive.

Or from a terminal. With git:

```
git clone https://github.com/FrostyDog222/jobhunter.git
```

Without git, in PowerShell:

```
Invoke-WebRequest https://github.com/FrostyDog222/jobhunter/archive/refs/heads/main.zip -OutFile jobhunter.zip
Expand-Archive jobhunter.zip -DestinationPath .
```

Or with curl, which ships with Windows 10 and later:

```
curl -L -o jobhunter.zip https://github.com/FrostyDog222/jobhunter/archive/refs/heads/main.zip
```

The zip unpacks into a folder called `jobhunter-main`; git gives you `jobhunter`. Either is
fine — the app runs from whatever folder it is in. Then carry on below.

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
   ones you like.

   Declare every language you work in. A job that demands a language you have not listed is
   skipped before it is scored.

   The *Application answers* card holds your salary expectation, notice period and earliest
   start. Boards ask for these, and the app answers with exactly what you wrote there.

3. **Search.** Pick a role family from *Preset* — your own job titles are at the top of the
   list — or type your own terms, separated by commas. Then *Search & score*.

   Romanian boards index Romanian wording, so search both: `suport clienti, relatii clienti,
   customer support`.

## Finding jobs

Four sources are searched at once:

| source | what it covers |
|---|---|
| eJobs | the largest Romanian board |
| BestJobs | the second largest |
| Hipo | Romanian board, strong on graduate and corporate roles |
| freehire | international index, including remote roles and employer career pages |

Every job gets a score from 0 to 100 with a short reason, what you **bring** that the ad asks
for, and the **gaps**. *Best for you* is everything scoring 75 or more.

**How many people you are up against.** BestJobs publishes, for every ad, how many have already
applied — and no other board here does. Where it is known the card says so, and the colour is the
point: under 25 is green and worth today, over 150 is red and your CV has a pile to survive
first. It also breaks ties. Almost every score lands on a multiple of five, so the whole *Best
for you* band is two or three values wide; within a band, the ad with 46 applicants now comes
before the one with 1437. The **Few applicants** tile shows just those.

It also decides which ads get read in full. One request to BestJobs returns 100 and only 20 are
worth a detail fetch and a model call: half of those go to the board's own relevance order, and
half to the least crowded of the rest. Measured on one search, that moves the median from 128
applicants to 21.

**A salary is only a salary if the employer said it.** BestJobs publishes its own estimate for
ads that state no pay, and that estimate used to be shown as fact. It now appears as `~ 900 - 1000
EUR/month (est.)` — dimmer, and marked. Do not quote an estimate back to an employer.

Lists show 20 jobs to a page. The filter box narrows what is already found by title, company or
city as you type, and ignores diacritics — `iasi` finds `Iași`.

**Ad age.** Each job carries a green **new** badge for the first week after it was posted and an
amber **old** one after that. Anything past two weeks is dropped on every search: those ads are
filled or abandoned, and scoring them wastes a call. Jobs you applied to, tailored, opened or
skipped stay regardless of age.

## Tailored CVs

*Tailor CV* rewrites and reorders **your own** facts for that one ad and saves a PDF. Nothing is
invented: no employer, date, degree, tool or achievement that is not in your profile.

- **Language** follows the ad by default — a Romanian ad gets a Romanian CV — or you can fix it
  to one language under *Settings*.
- **Template**: pick a default under *Settings*, or leave *Ask me every time* on and choose per
  CV. Every template is plain text underneath, with no tables or columns, so applicant tracking
  systems read it correctly.

## Applying

| where the job is | what the app does |
|---|---|
| eJobs, BestJobs | Applies for you, after you confirm. Tick several and send up to 20 in one run. |
| Hipo | Applies for you, after you confirm — see the note below on what it does and does not tell you. Some Hipo ads redirect to the employer's own site instead; those are marked and opened, never submitted. |
| Manual apply view | The *Manual apply* card filters to everything you have to send yourself. Those jobs are never picked up by batch apply or the weekly run. |
| Employer forms (Greenhouse, Lever, Ashby, Workable, Workday and others) | Opens the form with your details filled in and the CV attached, then stops. You read it and press submit. |
| Anything else | Opens the ad and your tailored CV side by side. |

**How long a sign-in lasts.** Measured by removing one cookie at a time from a copy of the saved
session and reloading the board:

| | |
|---|---|
| **eJobs** | the access token lives 1 hour, but the app mints a new one from a 13-month refresh token on the next visit after it expires. Heals itself; survives the PC being off. |
| **BestJobs** | about six months, renewed on every visit. Effectively never expires. |
| **Hipo** | a rolling 6 hours — every visit resets it to a full six. Stays signed in for ever while the PC is on, and lapses if it is off overnight. |

*Keep me signed in* therefore visits every two hours, which is set by Hipo and nothing else. It
does not wake a sleeping machine: the only board that cannot survive a night is the one this app
never applies on anyway.

**Signing in again by itself (optional, off).** The weekly run happens with nobody at the
keyboard, so a board that has signed you out by then means no applications that week. Under
*Settings → Job board accounts* you can save a board sign-in and let the app log in again on its
own — once, only when the board has just said you are signed out, and never twice in a row.

It stays on this PC. One file in this folder, encrypted with Windows DPAPI so only your Windows
account can read it, never sent anywhere except the board's own login page. It is excluded from
the shared zip and from the repository.

Two honest caveats. The encryption means a copy taken anywhere else — a backup, a stolen drive —
is unreadable, but nothing stored on a computer can protect against something already running as
you. And a password is worth more than the cookie beside it: it does not expire, it often opens
other sites too, and it can change the account's email. **Not trusting a tool from the internet
with your password is a perfectly sensible choice** — leave it empty and sign in by hand; nothing
else changes.

Sign in once under *Settings → Job board accounts*. You type your password into the browser
window that opens, never into this app — unless you save the sign-in (below), which is optional
and off. All three need it to apply.

**Hipo applies like the others now.** It used to be manual because a sign-in made in this app
was not accepted once you left the window that made it. That stopped being true when every
browser context here was given one identity, and it was checked properly: signed out completely,
signed back in headlessly from a saved password, and a members-only page then read from a
separate headless context. Three boards, three times, all pass.

One thing to know about it: **Hipo confirms nothing.** When an application goes through it
removes the apply button and says nothing at all — no message, no badge, the word "aplică" gone
from the page entirely. So the button's absence is the confirmation, and the app reads it that
way. The same absence also appears when a posting simply closes, and those two cannot be told
apart from the page, so a Hipo job with no apply button is reported as "either it closed or you
already applied" rather than guessed at. *Import my Hipo applications* settles it.

**A board application sends the CV stored on your board profile**, not the tailored PDF. Keep
those profiles current — the links are under *Settings*.

**Screening questions.** Some eJobs ads add their own questions. Salary, notice period and start
date are answered from your *Application answers*; if every question is answered the
application is sent, and if even one is left blank the app stops and opens it for you to finish.
The salary figure you wrote goes to every employer that asks, so set one you would stand behind.

## The weekly run

Under *Settings → Weekly run*, Windows can run your search once a week on its own, so the list
is already searched and scored when you next open the app. It works with the app closed — the
black window does not need to be open — and a run missed because the PC was off happens the next
time it is on.

By default it searches and scores, and leaves the applying to you.

**Applying without you there** is a second switch, off until you turn it on, and it asks once
more before it takes. When it is on the weekly run also applies to the best of what it found:

| limit | default |
|---|---|
| boards | eJobs and BestJobs only — never Hipo, never an employer form |
| score | 85 or above, your choice |
| how many | 5 per week, your choice, never more than 20 |
| which rows | only ones nobody has touched; applied, opened, skipped and vetoed are left alone |
| screening questions | marked and left for you — no browser window opens on an empty desk |

Everything it sent is listed in the panel with its score, so Monday morning shows you exactly
what went out.

Ticking the switch does not just warn you in the abstract: it lists **the actual jobs that would
have gone out this week** at your current score and cap, by name and employer, and tells you how
many a stricter score would send. If you change the score or the cap afterwards, it asks again.

Think about it before switching it on. An application cannot be recalled; it carries the salary
figure from your profile and the CV stored on your **board** profile, not a tailored one; the
score is a model's opinion; and you find out a week later.

## Applied history

Everything you applied to is kept, with the date and time, newest first, 20 to a page. Applied
jobs cannot be deleted or changed — that list is your record of what you sent.

*Mark applied* is for applications you sent yourself outside the app. If you click it by
mistake, *Undo* works for two minutes.

**Import my Hipo applications** (under *Settings → Job board accounts*) reads the list Hipo
keeps in your own account and copies it into this history, with Hipo's dates. Jobs you applied
to by hand then stop showing up as still to do. It only ever adds.

## After you apply

Pressing Apply is the start of the part that gets you hired, not the end. Every applied job shows
how long it has been waiting, and once that passes **ten days** the line turns amber and says it
is worth a nudge — long enough not to pester someone still reading, short enough that the job is
not filled by the time you write.

Four buttons on each applied card end the wait, one click each, nothing to type:

| | |
|---|---|
| **seen** | the employer opened your application — a different silence from one who never looked |
| **interview** | they want to talk to you |
| **rejected** | a no. Worth recording: it stops that one taking up room |
| **offer** | the point of all this |

Two views go with them. **Waiting to hear** is everything with no answer yet, longest wait first,
so the top of the list is what to do something about today. **Worth a nudge** is the subset that
has gone past ten days.

Rejections are kept, not deleted. A board that already has your application will not take a second
one, and the record is what stops the weekly run offering the same employer back to you.

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
the commands under [Getting it](#getting-it) and copy the files over the top. Keep your own
files when you do — `.env`, `profile.json`, `settings.json`, `db.sqlite`, `.session.json`,
`.boards.json` and the `out` folder. That is the bookkeeping Update.bat does for you.

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
the scheduled tasks, which would stay behind and fail quietly every week.

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
    auto.py       the weekly run, started by Windows Task Scheduler
    auto_apply.py the applying step of the weekly run, and the limits on it
    lang.py       the Romanian for every sentence in the app, keyed by the English
    creds.py      optional board sign-ins, encrypted to the Windows account (DPAPI)
    test_app.py   the whole suite; `python test_app.py` prints ok or the first failure
    restart.ps1   restarts the server while you work on it; nothing in the app calls it

    profile.json  your data          settings.json  your preferences
    db.sqlite     jobs and history   out/           generated CVs
    .env          API keys           .session.json  board sign-ins
    auto.log      what the weekly run did            auto_last.json  its last summary

None of those leave the machine: `share.py` excludes every one of them, and `.gitignore` keeps
them out of the repository.

Adding a CV template is one CSS file in `templates/cv/`; its first comment line is
`/* Name - one-line description */` and it appears in the picker on the next reload.

Adding a provider is one line in `llm.PROVIDERS`, if it speaks the OpenAI API.

Job ads are untrusted input: every prompt that sees one opens with a trust boundary and wraps
the ad in `<JOB_POSTING>` tags. That raises the bar; it is not a sandbox.

Check it still works: `python test_app.py`
