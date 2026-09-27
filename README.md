# jobhunter

A local job-hunting assistant for the Romanian market. It finds jobs, scores each one against
your profile, writes a CV tailored to the ad, and applies on the boards that allow it.

Everything stays on your PC except the calls to the AI model you choose — and with Ollama, not
even those.

## Start

Double-click **run.bat**. The first run takes a few minutes: it creates a Python environment,
installs what it needs and downloads a browser. After that it starts in seconds and the
dashboard opens by itself at http://127.0.0.1:8777.

Keep the black window open while you use the app. Closing it stops the app.

You need Python 3.10 or newer from python.org, installed with **Add to PATH** ticked.

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

Lists show 20 jobs to a page. The filter box narrows what is already found by title, company or
city as you type.

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
| Hipo | **Manual**: opens the ad in your own browser; you press apply there. |
| Employer forms (Greenhouse, Lever, Ashby, Workable, Workday and others) | Opens the form with your details filled in and the CV attached, then stops. You read it and press submit. |
| Anything else | Opens the ad and your tailored CV side by side. |

To apply on eJobs and BestJobs, sign in once under *Settings → Job board accounts*. You type
your password into the browser window that opens, never into this app.

**A board application sends the CV stored on your board profile**, not the tailored PDF. Keep
those profiles current — the links are under *Settings*.

**Screening questions.** Some eJobs ads add their own questions. Salary, notice period and start
date are answered from your *Application answers*; if every question is answered the
application is sent, and if even one is left blank the app stops and opens it for you to finish.
The salary figure you wrote goes to every employer that asks, so set one you would stand behind.

## Applied history

Everything you applied to is kept, with the date and time, newest first, 20 to a page. Applied
jobs cannot be deleted or changed — that list is your record of what you sent.

*Mark applied* is for applications you sent yourself outside the app. If you click it by
mistake, *Undo* works for two minutes.

## Giving the app to someone else

Double-click **share.bat**. It makes `jobhunter.zip` containing the app and nothing of yours: no
API keys, no profile, no job list, no board sign-ins, no CVs. Send the zip; they unzip it to a
short local folder such as `C:\jobhunter` (not inside OneDrive) and double-click run.bat.

Do not copy the folder by hand. It holds your keys and your signed-in sessions, and whoever
receives it could apply to jobs as you.

## Moving to a new PC (keeping your own data)

Copy the whole folder **except** `.venv` and `__pycache__`, then run run.bat on the new PC. Your
profile, job list, history and keys come along. Sign in to the job boards again — sessions do
not survive the move.

## When something goes wrong

| what you see | what to do |
|---|---|
| The dashboard does not open | Wait for the black window to finish, then open http://127.0.0.1:8777 yourself. |
| "Python not found" | Install Python from python.org and tick *Add to PATH*. |
| "Windows protected your PC" | Click *More info*, then *Run anyway*. |
| "Setup failed" | Delete the `.venv` folder and run run.bat again. |
| "The AI model has used up its free quota" | Wait a few minutes, or add a second provider key. |
| "The API key was refused" | Paste the key again under *Settings*. |
| A board shows *not signed in* | Sign in again under *Settings*. Board sessions expire. |
| A search finds nothing on one board | Boards change their pages. The search reports which one failed; the others still work. |

## For whoever maintains it

    app.py        routes, database, PDF rendering
    llm.py        provider table, failover, the prompts
    scrape.py     the four sources
    prefill.py    browser automation: sign-in, apply, form filling
    templates/    dashboard, profile, the CV, and templates/cv/*.css (one file per CV template)
    share.py      builds the clean zip

    profile.json  your data          settings.json  your preferences
    db.sqlite     jobs and history   out/           generated CVs
    .env          API keys           .session.json  board sign-ins

Adding a CV template is one CSS file in `templates/cv/`; its first comment line is
`/* Name - one-line description */` and it appears in the picker on the next reload.

Adding a provider is one line in `llm.PROVIDERS`, if it speaks the OpenAI API.

Job ads are untrusted input: every prompt that sees one opens with a trust boundary and wraps
the ad in `<JOB_POSTING>` tags. That raises the bar; it is not a sandbox.

Check it still works: `python test_app.py`
