"""Romanian for the interface. English is the source; this is the other half.

Keyed by the English string itself, not by an invented name. Two reasons: the templates stay
readable English rather than a wall of t("btn_apply_43"), and a string nobody has translated yet
falls back to the English that is already written there instead of showing a key to the user.

Whitespace is normalised before lookup, so a paragraph wrapped across three lines in the HTML
still matches the single line written here.
"""

RO = {
    # ---- chrome, navigation, the things on every page
    "Dashboard": "Panou",
    "Profile": "Profil",
    "Settings": "Setări",
    "Save": "Salvează",
    "Cancel": "Renunță",
    "Remove": "Șterge",
    "Delete": "Șterge",
    "Skip": "Renunț la el",
    "Close": "Închide",
    "Search": "Caută",
    "Loading…": "Se încarcă…",
    "working...": "se lucrează...",
    "jobhunter — built by": "jobhunter — făcut de",
    "Everything it knows stays in this folder.":
        "Tot ce știe rămâne în acest folder.",

    # ---- the search bar
    "Search & score": "Caută și punctează",
    "More filters": "Mai multe filtre",
    "Freshness": "Prospețime",
    "Work mode": "Mod de lucru",
    "Seniority": "Nivel",
    "Application type": "Tip de aplicare",
    "City": "Oraș",
    "County": "Județ",
    "Country": "Țară",
    "Anywhere": "Oriunde",
    "Romania": "România",
    "Worldwide": "Global",

    # ---- the list, its filters and its counts
    "All jobs": "Toate joburile",
    "New": "Noi",
    "CV ready": "CV pregătit",
    "Opened": "Deschise",
    "Applied": "Aplicate",
    "Skipped": "Refuzate",
    "Near me / remote": "Aproape de mine / remote",
    "Closing within a week": "Se închid într-o săptămână",
    "Vetoed on language": "Respinse pe limbă",
    "Any fit": "Orice potrivire",
    "Fit 50+": "Potrivire 50+",
    "Fit 70+": "Potrivire 70+",
    "Fit 75+ (strong)": "Potrivire 75+ (bună)",
    "Fit 85+": "Potrivire 85+",
    "Total": "Total",
    "Best for you": "Cele mai bune pentru tine",
    "Closing this week": "Se închid săptămâna asta",
    "Manual apply": "Aplicare manuală",
    "Select all shown": "Selectează tot ce se vede",
    "Score these again": "Punctează-le din nou",
    "Apply to selected": "Aplică la cele selectate",
    "Clear": "Golește",

    # ---- one job card
    "Open posting": "Deschide anunțul",
    "Open to apply": "Deschide ca să aplici",
    "Tailor CV": "Adaptează CV-ul",
    "Re-tailor CV": "Adaptează CV-ul din nou",
    "Mark applied": "Marchează ca aplicat",
    "Read the job ad": "Citește anunțul",
    "prefillable form": "formular precompletabil",
    "manual apply": "aplicare manuală",
    "near you": "aproape de tine",
    "not scored": "nepunctat",
    "strong": "bună",
    "maybe": "poate",
    "weak": "slabă",
    "new": "nou",
    "old": "vechi",

    # ---- the AI panel
    "Provider": "Furnizor",
    "Model": "Model",
    "API key": "Cheie API",
    "List models": "Arată modelele",
    "Save & test": "Salvează și testează",
    "Get a key ↗": "Ia o cheie ↗",

    # ---- defaults and preferences
    "Defaults": "Setări implicite",
    "CV language": "Limba CV-ului",
    "Match the job ad": "Ca anunțul",
    "Always English": "Mereu engleză",
    "Always Romanian": "Mereu română",
    "ATS prefill": "Precompletare ATS",
    "Open the browser to review": "Deschide browserul ca să verific",
    "Dry run — just report": "Simulare — doar raportează",
    "Clock": "Ceas",
    "24-hour — 14:30": "24 de ore — 14:30",
    "12-hour — 2:30 PM": "12 ore — 2:30 PM",
    "Interface language": "Limba interfeței",
    "English": "English",
    "Romanian": "Română",
    "Where you can work": "Unde poți lucra",
    "My county": "Județul meu",
    "Do not judge distance": "Nu judeca distanța",

    # ---- the scheduled run
    "Day": "Ziua",
    "Time": "Ora",
    "Monday": "Luni", "Tuesday": "Marți", "Wednesday": "Miercuri", "Thursday": "Joi",
    "Friday": "Vineri", "Saturday": "Sâmbătă", "Sunday": "Duminică",
    "Save the schedule": "Salvează programarea",
    "Run it now": "Rulează acum",
    "Use my current search": "Folosește căutarea mea de acum",
    "Copy the search above": "Copiază căutarea de mai sus",
    "Use my job titles": "Folosește titlurile mele",
    "Worth my attention from": "Merită atenția mea de la",
    "Only jobs scoring": "Doar joburi cu scorul",
    "At most, per run": "Cel mult, pe rulare",

    # ---- CV templates
    "Put my photo on it": "Pune-mi poza pe el",
    "Tailor with this template": "Adaptează cu acest model",
    "better with one": "arată mai bine cu poză",
    "this one is better without": "acesta arată mai bine fără",
    "either works": "merge și așa, și așa",

    # ---- the rest of the interface, added after the chrome
    "Austria": "Austria",
    "Belgium": "Belgia",
    "Bulgaria": "Bulgaria",
    "France": "Franța",
    "Germany": "Germania",
    "Hungary": "Ungaria",
    "Ireland": "Irlanda",
    "Italy": "Italia",
    "Moldova": "Moldova",
    "Netherlands": "Olanda",
    "Poland": "Polonia",
    "Spain": "Spania",
    "United Kingdom": "Regatul Unit",
    "United States": "Statele Unite",
    "Anywhere in the country": "Oriunde în țară",
    "Any county": "Orice județ",
    "Any": "Oricare",
    "Mid": "Mediu",
    "Junior": "Junior",
    "Senior": "Senior",
    "Lead": "Lead",
    "Intern": "Intern",
    "Remote": "Remote",
    "Hybrid": "Hibrid",
    "On-site": "La birou",
    "Any age": "Orice vechime",
    "Fresh only": "Doar recente",
    "e.g. 30 days": "ex. 30 de zile",
    "Preset": "Set gata făcut",
    "Pick a role family…": "Alege un domeniu…",
    "ATS form only": "Doar formular ATS",
    "Strong 75+": "Bune 75+",
    "Medium 50-74": "Medii 50-74",
    "Weak &lt;50": "Slabe &lt;50",
    "Search jobs for": "Caută joburi pentru",
    "Filter by title or company…": "Filtrează după titlu sau companie…",
    "and": "și",
    "not": "nu",
    "and use": "și folosește",
    "the dashboard": "panoul",
    "far from you": "departe de tine",
    "signed in": "autentificat",
    "Clear results": "Golește rezultatele",
    "Basics": "Date de bază",
    "Full name": "Nume complet",
    "Email": "Email",
    "Phone": "Telefon",
    "Location": "Localitate",
    "Links": "Linkuri",
    "Photo": "Poză",
    "Headline / target role": "Titlu profesional / rolul dorit",
    "Summary": "Rezumat",
    "Experience": "Experiență",
    "Education": "Studii",
    "Skills": "Competențe",
    "Languages": "Limbi",
    "Language": "Limba",
    "Certifications": "Certificări",
    "Projects": "Proiecte",
    "Interests / hobbies": "Interese / hobby-uri",
    "Skills &amp; more": "Competențe și altele",
    "Save profile": "Salvează profilul",
    "Upload photo": "Încarcă o poză",
    "+ Add role": "+ Adaugă un rol",
    "+ Add education": "+ Adaugă studii",
    "+ Add language": "+ Adaugă o limbă",
    "+ Add project": "+ Adaugă un proiect",
    "Start from an existing CV": "Pornește de la un CV existent",
    "Upload &amp; autofill": "Încarcă și completează",
    "or paste CV text": "sau lipește textul CV-ului",
    "Paste your CV here...": "Lipește-ți CV-ul aici...",
    "Parse pasted text": "Citește textul lipit",
    "Download my CV": "Descarcă-mi CV-ul",
    "CV template": "Model de CV",
    "Put my photo on the CV": "Pune-mi poza pe CV",
    "AI review": "Analiză AI",
    "Suggest improvements": "Propune îmbunătățiri",
    "Application answers": "Răspunsuri la aplicare",
    "Salary expectation": "Salariul dorit",
    "Notice period": "Perioada de preaviz",
    "Earliest start": "Cel mai devreme început",
    "currency": "moneda",
    "e.g. 5500 net / month": "ex. 5500 net / lună",
    "e.g. immediately": "ex. imediat",
    "Erase everything": "Șterge tot",
    "Erase all my data": "Șterge-mi toate datele",
    "Profile · jobhunter": "Profil · jobhunter",
    "Dashboard · jobhunter": "Panou · jobhunter",
    "AI model": "Model AI",
    "Get a key": "Ia o cheie",
    "provider default": "modelul implicit al furnizorului",
    "leave blank to keep the saved one": "lasă gol ca să păstrezi cheia salvată",
    "Settings → AI model": "Setări → Model AI",
    "⚠ No AI model is set up yet": "⚠ Niciun model AI nu este configurat încă",
    "Job board accounts": "Conturi pe site-urile de joburi",
    "Keep me signed in": "Ține-mă autentificat",
    "Keep me signed in to the boards": "Ține-mă autentificat pe site-urile de joburi",
    "Import my Hipo applications": "Importă aplicările mele de pe Hipo",
    "Hipo is": "Hipo este",
    "Scheduled run": "Rulare programată",
    "scheduled run": "rulare programată",
    "Applying for you": "Aplică în locul tău",
    "Also apply for me": "Aplică și tu în locul meu",
    "Also apply for me, without asking": "Aplică în locul meu, fără să mă întrebi",
    "Job titles to search for": "Titlurile de job de căutat",
    "⚙ Automation — what runs without you": "⚙ Automatizare — ce rulează fără tine",
    "⚠ Read this before you switch it on": "⚠ Citește asta înainte să o pornești",
    "Show more — exactly what each one does": "Arată mai mult — exact ce face fiecare",
    "Switching any of them off": "Oprirea oricăreia dintre ele",
    "It runs with nobody watching.": "Rulează fără să se uite nimeni.",
    "It is your account doing it.": "O face contul tău.",
    "jobhunter scheduled search": "jobhunter scheduled search",
    "jobhunter keep signed in": "jobhunter keep signed in",
    "Which template for this CV?": "Ce model pentru acest CV?",
    "Remember this as my default": "Ține minte asta ca implicit",
    "Ask me which template to use every time I tailor a CV":
        "Întreabă-mă ce model să folosesc de fiecare dată când adaptez un CV",
    "Pick one. You can set a default under Settings so this stops asking.":
        "Alege unul. Poți seta un model implicit în Setări ca să nu mai întrebe.",
    "is the template built around one.": "este modelul construit în jurul ei.",
    "What employers keep asking for": "Ce cer angajatorii în mod repetat",
    "Find jobs. Tailor your CV. Get hired.": "Găsește joburi. Adaptează-ți CV-ul. Angajează-te.",
    "or batch apply.": "sau aplicare în grup.",
    ". Everything it knows stays in this folder.": ". Tot ce știe rămâne în acest folder.",
    "How times are shown on this page. It changes nothing that is stored.":
        "Cum sunt afișate orele pe pagină. Nu schimbă nimic din ce este salvat.",
    "The language of this page. The language your CV is written in is the setting to the left.":
        "Limba acestei pagini. Limba în care este scris CV-ul este setarea din stânga.",
    "The list is sorted best-first anyway, so this hides the tail rather than finding the head.":
        "Lista este oricum ordonată cu cele mai bune primele, așa că asta ascunde coada, nu găsește capul.",
    "Narrows the list below as you type. It searches what is already found, not the boards.":
        "Restrânge lista de mai jos pe măsură ce scrii. Caută în ce este deja găsit, nu pe site-uri.",
    "Judetul. Picking a city already narrows it further, so a city wins over this.":
        "Județul. Alegerea unui oraș restrânge și mai mult, așa că orașul are prioritate.",
    "Fills the box with terms for one role family. Edit before searching if you like.":
        "Completează caseta cu termeni pentru un domeniu. Poți edita înainte de a căuta.",
    "Fill this with the job titles on your profile":
        "Completează cu titlurile de job din profilul tău",
    "Copy what is in the search bar above into these boxes":
        "Copiază ce este în bara de căutare de mai sus în aceste casete",
    "Copy whatever is in the search bar at the top of the page":
        "Copiază ce este în bara de căutare din capul paginii",
    "Counts everything you have ticked, including jobs on other pages":
        "Numără tot ce ai bifat, inclusiv joburile de pe alte pagini",
    "Jobs scoring this or higher are counted in the summary":
        "Joburile cu scorul acesta sau mai mare sunt numărate în rezumat",
    "Writes the currency into the answer beside your figure":
        "Scrie moneda în răspuns, lângă suma ta",
    "Job titles, separated by commas. Each one is searched on its own.":
        "Titluri de job, separate prin virgulă. Fiecare este căutat separat.",
    "Pick from the suggestions or type your own, separated by commas":
        "Alege din sugestii sau scrie ale tale, separate prin virgulă",
    "The model reviews what you wrote and proposes rewrites. Accept the ones you like.":
        "Modelul recitește ce ai scris și propune reformulări. Le accepți pe cele care îți plac.",
    "The score is a model's opinion, not a fact.": "Scorul este părerea unui model, nu un fapt.",
    "It is a useful sort order, not a judgement you should act on without reading the ad.":
        "Este o ordine utilă de sortare, nu o judecată după care să te iei fără să citești anunțul.",
    "An application cannot be recalled.": "O aplicare nu poate fi retrasă.",
    "The score is the only thing holding it back.":
        "Scorul este singurul lucru care o ține în loc.",
    "Check your board CV before you switch this on.":
        "Verifică CV-ul de pe site înainte să pornești asta.",
    ": pick a provider, press": ": alege un furnizor, apasă",
    ", paste it back and press": ", lipește-o înapoi și apasă",
    "customer support, suport clienti, relatii clienti":
        "customer support, suport clienti, relatii clienti",
    "customer support, suport clienti, technical support":
        "customer support, suport clienti, technical support",
    "Four Romanian job boards, read and scored against your own profile. Nothing leaves this PC except the calls to the AI model you picked.":
        "Patru site-uri românești de joburi, citite și punctate față de propriul tău profil. Nimic nu pleacă de pe acest PC în afară de apelurile către modelul AI ales de tine.",
    "These four narrow the freehire results only — eJobs and Hipo have no equivalent, so they come back unfiltered.":
        "Aceste patru filtre restrâng doar rezultatele de pe freehire — eJobs și Hipo nu au echivalent, așa că vin nefiltrate.",
    "Upload a PDF/DOCX/TXT and the profile below is filled in automatically. Nothing is invented — blanks stay blank.":
        "Încarcă un PDF/DOCX/TXT și profilul de mai jos se completează automat. Nu se inventează nimic — ce lipsește rămâne gol.",
    "Delete results you never acted on, so a new search starts from a clean list. Applied, opened, tailored and skipped jobs stay.":
        "Șterge rezultatele pe care nu le-ai atins, ca o căutare nouă să pornească de la o listă curată. Joburile aplicate, deschise, adaptate și refuzate rămân.",
    "Read each job ad first — these go straight to the employer with the salary from your profile. Up to 50 per run.":
        "Citește mai întâi fiecare anunț — acestea ajung direct la angajator, cu salariul din profilul tău. Cel mult 50 pe rulare.",
    "Boards notice patterns. Searches are ordinary traffic; a burst of applications at 09:00 every Sunday is not.":
        "Site-urile observă tiparele. Căutările sunt trafic obișnuit; un val de aplicări la 09:00 în fiecare duminică nu este.",
    "Every tailored CV is rendered in one of these. All four are plain text underneath — no tables, no columns — so applicant tracking systems read them correctly.":
        "Fiecare CV adaptat este generat într-unul dintre acestea. Toate patru sunt text simplu dedesubt — fără tabele, fără coloane — ca sistemele de recrutare să le citească corect.",
    "Your profile as it stands, in whichever style you want — nothing is tailored to a job and no AI is used, so it is instant. The tailored ones are written per posting, from the job list.":
        "Profilul tău așa cum este, în ce stil vrei — nimic nu este adaptat unui job și nu se folosește AI, deci este instantaneu. Cele adaptate se scriu pentru fiecare anunț, din lista de joburi.",
    "Hipo keeps its own list of what you applied to. This copies it into your Applied history, with the dates, so jobs you sent by hand stop showing up as still to do.":
        "Hipo își ține propria listă cu aplicările tale. Asta o copiază în istoricul tău de Aplicate, cu date cu tot, ca joburile trimise manual să nu mai apară ca nefăcute.",
    "Every week it spends API quota on scoring, whether or not you look at the result. If a free tier runs dry it fails quietly and you find out days later, in the summary.":
        "În fiecare săptămână consumă din cota API pentru punctare, fie că te uiți la rezultat, fie că nu. Dacă un plan gratuit se golește, eșuează în tăcere și afli peste câteva zile, din rezumat.",
    "Counted across the jobs already scored, not a new question to the AI. A thing many employers want and your profile never mentions is either the next thing to learn — or something you have and forgot to write down.":
        "Numărat din joburile deja punctate, nu o întrebare nouă către AI. Un lucru pe care mulți angajatori îl cer și pe care profilul tău nu îl pomenește este fie următorul lucru de învățat — fie ceva ce ai și ai uitat să scrii.",
    # ---- the long explanations, which are most of what this app says
    "Save &amp; test":
        "Salvează și testează",
    "Search &amp; score":
        "Caută și punctează",
    "Upload &amp; autofill":
        "Încarcă și completează",
    "Two separate things, both off unless you switch them on. The":
        "Două lucruri separate, ambele oprite până le pornești tu.",
    "The job titles you would type into the search bar at the top —":
        "Titlurile de job pe care le-ai scrie în bara de căutare din capul paginii —",
    ". Several are free. You can still fill this page in by hand without one.":
        ". Mai multe sunt gratuite. Poți completa pagina și de mână, fără niciunul.",
    "Reading a CV, suggesting improvements and scoring jobs all need one. Open":
        "Citirea unui CV, propunerile de îmbunătățire și punctarea joburilor au nevoie de unul. Deschide",
    "is a second switch inside it, and it is the one that sends real applications in your name.":
        "este un al doilea comutator în interiorul ei, și este cel care trimite aplicări reale în numele tău.",
    "does your search and scores the results on its own, so the list is ready when you next open the app.":
        "îți face căutarea și punctează rezultatele singură, ca lista să fie gata când deschizi aplicația data viitoare.",
    "A board apply sends the CV stored on your board profile, not the tailored PDF — so keep those profiles current:":
        "O aplicare de pe site trimite CV-ul salvat în profilul tău de pe acel site, nu PDF-ul adaptat — așa că ține acele profiluri la zi:",
    "Most boards are nationwide, so a search from a village in Timiș fills up with jobs in București. Pick your county and anything outside it is marked":
        "Majoritatea site-urilor sunt naționale, așa că o căutare dintr-un sat din Timiș se umple de joburi în București. Alege-ți județul și tot ce este în afara lui este marcat",
    "A few points either way changes how much goes out, so start high with a cap of one or two and watch what it picks for a few weeks before loosening it.":
        "Câteva puncte în plus sau în minus schimbă mult cât pleacă, așa că pornește sus, cu o limită de una sau două, și urmărește ce alege câteva săptămâni înainte să o slăbești.",
    "— marked, not hidden, because a job worth moving for is your call. Remote and hybrid ads are never flagged, and ads that name no location are left alone.":
        "— marcat, nu ascuns, pentru că un job pentru care merită să te muți este decizia ta. Anunțurile remote și hibride nu sunt niciodată marcate, iar cele care nu spun unde sunt rămân neatinse.",
    "removes the Windows task straight away. Nothing keeps running in the background afterwards, and you can check for yourself in Task Scheduler — they are named":
        "șterge imediat sarcina din Windows. Nimic nu mai rulează în fundal după aceea, și poți verifica singur în Task Scheduler — se numesc",
    "· Separate spellings with commas — each is searched on freehire, eJobs, BestJobs and Hipo. Ads demanding a language you have not declared are skipped before scoring, so they cost nothing.":
        "· Separă variantele de scriere cu virgulă — fiecare este căutată pe freehire, eJobs, BestJobs și Hipo. Anunțurile care cer o limbă pe care nu ai declarat-o sunt sărite înainte de punctare, deci nu costă nimic.",
    "A board application sends the CV stored on your eJobs and BestJobs profile, not a tailored one. If it is out of date, every application it sends is out of date. Both profile links are above.":
        "O aplicare de pe site trimite CV-ul salvat în profilul tău de eJobs și BestJobs, nu unul adaptat. Dacă este vechi, fiecare aplicare pe care o trimite este veche. Ambele linkuri către profiluri sunt mai sus.",
    "a description of yourself. Separate them with commas: each one is searched on its own, so listing a job in both Romanian and English finds ads the other wording misses. Click the box for suggestions from your own CV.":
        "o descriere a ta. Separă-le cu virgulă: fiecare este căutat separat, așa că scriind un job și în română și în engleză găsești anunțuri pe care cealaltă formulare le ratează. Dă clic în casetă pentru sugestii din propriul tău CV.",
    "JPG or PNG. With no photo saved this is ignored, so the CV simply has none. A photo is normal on a CV in Romania and most of Europe; for the UK, Ireland or the US it is usually better left off, which is what the tick is for.":
        "JPG sau PNG. Dacă nu ai nicio poză salvată, setarea este ignorată și CV-ul pur și simplu nu are una. Poza este normală pe un CV în România și în mare parte din Europa; pentru Marea Britanie, Irlanda sau SUA este de obicei mai bine fără, și pentru asta este bifa.",
    "Board sign-ins expire on their own after a while. Until you sign in again, applying to those jobs fails and the scheduled run sends nothing — it re-checks before it applies, rather than trusting this panel. Use the button below.":
        "Autentificările pe site-uri expiră singure după o vreme. Până te autentifici din nou, aplicarea la acele joburi eșuează și rularea programată nu trimite nimic — verifică din nou înainte să aplice, în loc să se încreadă în acest panou. Folosește butonul de mai jos.",
    "eJobs and BestJobs only let you apply while signed in. You type the password into the browser that opens, never into this app. eJobs often hangs on its redirect afterwards — that is fine, the session is already saved; just close the tab once it says":
        "eJobs și BestJobs te lasă să aplici doar autentificat. Parola o scrii în browserul care se deschide, niciodată în această aplicație. eJobs se blochează des la redirecționarea de după — este în regulă, sesiunea este deja salvată; închide fila când scrie",
    "Employers on eJobs often attach a short \"mini interviu\" before your application goes through. These are the questions no CV answers, so the app fills them with exactly what you write here and leaves them blank if you do not. It never invents a figure.":
        "Angajatorii de pe eJobs atașează des un scurt \"mini interviu\" înainte ca aplicarea ta să treacă. Sunt întrebările la care niciun CV nu răspunde, așa că aplicația le completează exact cu ce scrii aici și le lasă goale dacă nu scrii nimic. Nu inventează niciodată o sumă.",
    "With applying switched on, the salary figure from your profile and whatever CV currently sits on your board profile reach real employers, on ads nobody read, and you find out a week later. Those are the same employers you might have wanted to approach properly.":
        "Cu aplicarea pornită, suma de salariu din profilul tău și orice CV se află acum în profilul tău de pe site ajung la angajatori reali, pe anunțuri pe care nu le-a citit nimeni, și afli o săptămână mai târziu. Sunt aceiași angajatori la care poate ai fi vrut să te prezinți cum trebuie.",
    "— the checkbox further up, next to the sign-in buttons. Boards renew a sign-in whenever the site is opened, so Windows visits them every two hours and the session never lapses. Hipo's lasts about six hours on its own. It only loads the pages: nothing is searched, sent, or spent.":
        "— bifa de mai sus, lângă butoanele de autentificare. Site-urile reînnoiesc autentificarea de fiecare dată când sunt deschise, așa că Windows le vizitează la două ore și sesiunea nu expiră niciodată. A celor de la Hipo ține cam șase ore de la sine. Doar încarcă paginile: nu se caută, nu se trimite și nu se consumă nimic.",
    "Deletes everything this app holds about you — your profile and photo, every job it found and scored, your applied history, the CVs it wrote, the board sign-ins, your settings and the schedule. It cannot be undone, and it does not touch anything on eJobs, BestJobs or Hipo: applications you have already sent stay sent.":
        "Șterge tot ce știe aplicația despre tine — profilul și poza, fiecare job găsit și punctat, istoricul aplicărilor, CV-urile scrise, autentificările pe site-uri, setările și programarea săptămânală. Nu se poate anula, și nu atinge nimic pe eJobs, BestJobs sau Hipo: aplicările deja trimise rămân trimise.",
    "— Windows starts it on the days and at the time you pick, with the app closed; the black run.bat window does not need to be open. It searches the same terms you saved, across the same boards, and scores everything new against your profile. It sends nothing. Each run spends AI quota on the scoring, whether or not you look at the result.":
        "— Windows o pornește în ziua și la ora pe care le alegi, cu aplicația închisă; fereastra neagră run.bat nu trebuie să fie deschisă. Caută aceiași termeni pe care i-ai salvat, pe aceleași site-uri, și punctează tot ce este nou față de profilul tău. Nu trimite nimic. Fiecare rulare consumă din cota AI pentru punctare, fie că te uiți la rezultat, fie că nu.",
    "Boards renew a sign-in whenever the site is opened, so Windows visits them every few hours in the background and the session never lapses. Hipo's lasts about six hours on its own, so without this it is signed out most of the time. It sends nothing and applies to nothing — it only loads each board. Turn it off and sign-ins expire on their own again.":
        "Site-urile reînnoiesc autentificarea de fiecare dată când sunt deschise, așa că Windows le vizitează la câteva ore în fundal și sesiunea nu expiră niciodată. A celor de la Hipo ține cam șase ore de la sine, deci fără asta ești deconectat mai tot timpul. Nu trimite nimic și nu aplică nicăieri — doar încarcă fiecare site. Oprește-o și autentificările expiră din nou singure.",
    "Back to top": "Înapoi sus",
    # ---- saving as you go
    "saved":
        "salvat",
    "saving...":
        "se salvează...",
    "not saved yet":
        "nesalvat încă",
    "could not save - press Save profile":
        "nu s-a putut salva - apasă Salvează profilul",
    "Your last change could not be saved, so it is still only on this page. Press Save profile to try again before you leave.":
        "Ultima modificare nu a putut fi salvată, deci există doar pe această pagină. Apasă Salvează profilul ca să încerci din nou înainte să pleci.",
    # ---- the two languages, which are not the same thing
    "Language of the CV":
        "Limba CV-ului",
    "Which language the downloaded PDF is written in. The language of this page is the switch at the top.":
        "În ce limbă este scris PDF-ul descărcat. Limba acestei pagini este comutatorul de sus.",
    "The language of this page and the dashboard. The CV has its own setting further up.":
        "Limba acestei pagini și a panoului. CV-ul are propria setare mai sus.",
    # ---- the Ollama walkthrough
    "Running the model on your own PC with Ollama — step by step":
        "Rulează modelul pe propriul PC cu Ollama — pas cu pas",
    "Free, and nothing leaves this PC — not even the job ads. You can leave a hosted provider first and keep Ollama behind it as a backstop for when a free tier runs dry.":
        "Gratuit, și nimic nu pleacă de pe acest PC — nici măcar anunțurile. Este mai lent pe anunț decât un furnizor online, așa că se potrivește unei căutări mici sau unui PC cu placă video bună. Poți lăsa un furnizor online primul și să ții Ollama în spate, ca rezervă pentru când un plan gratuit se golește.",
    # ---- the Ollama walkthrough, step by step
    "Install Ollama from {link} and let it finish. It then runs quietly in the background whenever your PC is on.":
        "Instalează Ollama de la {link} și lasă-l să termine. Apoi rulează discret în fundal ori de câte ori PC-ul este pornit.",
    "It is running on this PC.":
        "Rulează pe acest PC.",
    "Not answering on this PC yet.":
        "Încă nu răspunde pe acest PC.",
    "Download a model. Open Terminal or PowerShell and type {cmd}, then wait - it is a couple of gigabytes, once.":
        "Descarcă un model. Deschide Terminal sau PowerShell, scrie {cmd} și așteaptă - sunt câțiva gigabytes, o singură dată.",
    "{n} already downloaded:":
        "{n} descărcate deja:",
    "Back here: set Provider to ollama. The Model box fills itself from what you downloaded.":
        "Înapoi aici: pune Furnizor pe ollama. Caseta Model se completează singură din ce ai descărcat.",
    "{model} is a good first choice.":
        "{model} este o primă alegere bună.",
    "Leave API key empty. There is no key and none is needed - that is the point of running it here.":
        "Lasă cheia API goală. Nu există nicio cheie și nici nu e nevoie - tocmai ăsta e rostul rulării locale.",
    "Press Save & test. It asks the model one small question and tells you what came back. The first answer is slow while the model loads into memory; after that it settles.":
        "Apasă Salvează și testează. Pune modelului o întrebare mică și îți spune ce a răspuns. Primul răspuns este lent cât se încarcă modelul în memorie; după aceea se așază.",
    # ---- the banner at the top of the page
    "Signed out of":
        "Deconectat de la",
    "Applying to those boards fails until you sign in again, and the scheduled run sends nothing. It re-checks before it applies, so this is the only warning you get.":
        "Aplicarea pe acele site-uri eșuează până te autentifici din nou, iar rularea programată nu trimite nimic. Verifică din nou înainte să aplice, deci acesta este singurul avertisment pe care îl primești.",
    "Sign in":
        "Autentifică-te",
    "Your profile is missing":
        "Din profilul tău lipsește",
    "your name":
        "numele tău",
    "an email address or a phone number":
        "o adresă de email sau un număr de telefon",
    "Every CV this app writes carries these across unchanged, so a CV without them reaches an employer with no way to answer it.":
        "Fiecare CV scris de aplicație le preia neschimbate, așa că un CV fără ele ajunge la angajator fără nicio cale de a-ți răspunde.",
    "Fill it in":
        "Completează",
    "No answers saved for the application questions":
        "Niciun răspuns salvat pentru întrebările de aplicare",
    "eJobs often attaches a short mini-interview - salary expectation, notice period, earliest start. With these blank the app leaves them blank rather than inventing a figure, and some employers will not accept that.":
        "eJobs atașează des un scurt mini-interviu - salariul dorit, perioada de preaviz, cel mai devreme început. Cu ele goale, aplicația le lasă goale în loc să inventeze o sumă, iar unii angajatori nu acceptă asta.",
    "Add them":
        "Adaugă-le",
    # ---- choosing a local model
    "Free, and nothing leaves this PC — not even the job ads. You can leave a hosted provider first and keep Ollama behind it as a backstop for when a free tier runs dry.":
        "Gratuit, și nimic nu pleacă de pe acest PC — nici măcar anunțurile. Poți lăsa un furnizor online primul și să ții Ollama în spate, ca rezervă pentru când un plan gratuit se golește.",
    "⚠ Expect it to be much slower.":
        "⚠ Așteaptă-te să fie mult mai lent.",
    "A hosted model scores an ad in a second or two; a local one takes tens of seconds, and a search scores dozens of ads. A run that takes two minutes in the cloud can take half an hour here.":
        "Un model online punctează un anunț în una-două secunde; unul local ia zeci de secunde, iar o căutare punctează zeci de anunțuri. O rulare care durează două minute în cloud poate dura o jumătate de oră aici.",
    "Pick a 7B–14B instruct model, and avoid reasoning models.":
        "Alege un model instruct de 7B–14B și evită modelele care raționează.",
    "are the ones that answer in the right format. Anything that thinks before it answers — names with":
        "sunt alegeri sigure. Orice model care gândește înainte să răspundă — nume cu",
    ", and several of the newest gemma and qwen builds — writes its reasoning instead of the answer and this app gets nothing back. Models under about 7B return JSON of the wrong shape, which shows up as jobs that never get a score.":
        ", și câteva dintre cele mai noi versiuni gemma și qwen — își scrie raționamentul în loc de răspuns, iar aplicația nu primește nimic. Modelele sub circa 7B tind să returneze JSON de forma greșită, ceea ce se vede ca joburi care nu primesc niciodată un scor.",
    # ---- what a local model actually costs you in accuracy
    "are the ones that answer in the right format. Anything that thinks before it answers — names with":
        "sunt cele care răspund în formatul corect. Orice model care gândește înainte să răspundă — nume cu",
    ", and several of the newest gemma and qwen builds — writes its reasoning instead of the answer and this app gets nothing back. Models under about 7B return JSON of the wrong shape, which shows up as jobs that never get a score.":
        ", și câteva dintre cele mai noi versiuni gemma și qwen — își scrie raționamentul în loc de răspuns, iar aplicația nu primește nimic. Modelele sub circa 7B returnează JSON de forma greșită, ceea ce se vede ca joburi care nu primesc niciodată un scor.",
    "The scores will be rougher.":
        "Scorurile vor fi mai aproximative.",
    "Measured here on twelve real ads: llama3.1:8b answered 11 of them in about 30 seconds each, but its score differed from the hosted model by around 30 points and it scored higher five times out of six — it parks near 60 for almost everything, including jobs a hosted model rates 10. A list full of 60s looks like a good week and is not. Writing a tailored CV asks much more of it and succeeded once in three tries, taking a minute or two each. Worth it for privacy, or as the backstop when a free tier runs dry; not the one to judge which jobs deserve an application. With a hosted provider saved as well, a local failure costs only the wait, because the next provider in the chain picks it up.":
        "Măsurat aici pe douăsprezece anunțuri reale: llama3.1:8b a răspuns la 11 dintre ele în circa 30 de secunde fiecare, dar scorul lui a diferit de cel al modelului online cu aproximativ 30 de puncte și a punctat mai sus de cinci ori din șase — se oprește pe la 60 aproape pentru orice, inclusiv pentru joburi pe care un model online le dă 10. O listă plină de 60 pare o săptămână bună, dar nu este. Merită pentru intimitate sau ca rezervă când un plan gratuit se golește; nu pentru a judeca ce joburi merită o aplicare.",
    "Measured here on twelve real ads: llama3.1:8b answered 11 of them in about 30 seconds each, but its score differed from the hosted model by around 30 points and it scored higher five times out of six — it parks near 60 for almost everything, including jobs a hosted model rates 10. A list full of 60s looks like a good week and is not. Writing a tailored CV asks much more of it and succeeded once in three tries, taking a minute or two each. Worth it for privacy, or as the backstop when a free tier runs dry; not the one to judge which jobs deserve an application. With a hosted provider saved as well, a local failure costs only the wait, because the next provider in the chain picks it up.":
        "Măsurat aici pe douăsprezece anunțuri reale: llama3.1:8b a răspuns la 11 dintre ele în circa 30 de secunde fiecare, dar scorul lui a diferit de cel al modelului online cu aproximativ 30 de puncte și a punctat mai sus de cinci ori din șase — se oprește pe la 60 aproape pentru orice, inclusiv pentru joburi pe care un model online le dă 10. O listă plină de 60 pare o săptămână bună, dar nu este. Scrierea unui CV adaptat îi cere mult mai mult și a reușit o dată din trei încercări, cu un minut-două de fiecare dată. Merită pentru intimitate sau ca rezervă când un plan gratuit se golește; nu pentru a judeca ce joburi merită o aplicare. Dacă ai salvat și un furnizor online, un eșec local costă doar așteptarea, pentru că preia următorul furnizor din lanț.",
    # ---- pausing and removing a provider
    "Fallback order — when one runs out of quota the next takes over:":
        "Ordinea de rezervă — când unul rămâne fără cotă, preia următorul:",
    "paused":
        "pe pauză",
    "spent":
        "epuizat",
    "Pause":
        "Pune pe pauză",
    "Resume":
        "Reia",
    "Keep the key, but stop using this one for now":
        "Păstrează cheia, dar nu-l mai folosi deocamdată",
    "Start using this one again":
        "Începe să-l folosești din nou",
    "Delete this key. You will have to paste it again to use this provider.":
        "Șterge această cheie. Va trebui să o lipești din nou ca să folosești acest furnizor.",
    "is paused. Its key is kept.":
        "este pe pauză. Cheia lui este păstrată.",
    "is back in the chain.":
        "este din nou în lanț.",
    "removed. Its key is deleted.":
        "șters. Cheia lui a fost ștearsă.",
    "pausing...":
        "se pune pe pauză...",
    "resuming...":
        "se reia...",
    "removing...":
        "se șterge...",
    "Delete the saved key for":
        "Ștergi cheia salvată pentru",
    "This cannot be undone - you will have to paste the key again to use this provider. Pause it instead if you only want to stop using it for a while.":
        "Asta nu se poate anula - va trebui să lipești cheia din nou ca să folosești acest furnizor. Pune-l pe pauză dacă vrei doar să nu-l mai folosești o vreme.",
    # ---- starting out, with no paid job yet
    "I am new to the workforce — no paid job yet.":
        "Sunt la început de drum — încă niciun job plătit.",
    "Scoring stops treating \"no experience\" as a fault on every ad and looks at what an employer hiring a beginner actually checks: your studies, a licence, languages, and whether the job trains you. Fill in Education and Projects below — a summer job or volunteering goes under Experience.":
        "Punctarea nu mai tratează \"lipsa experienței\" ca pe un defect la fiecare anunț și se uită la ce verifică de fapt un angajator care ia un începător: studiile tale, un permis, limbile și dacă jobul te instruiește. Completează Studii și Proiecte mai jos — un job de vară sau voluntariatul intră la Experiență.",
    "First job / no experience (RO boards)":
        "Primul job / fără experiență (site-uri RO)",
    "First job / no experience (English)":
        "Primul job / fără experiență (engleză)",
    "Fill in your profile first - there is nothing to match jobs against. Your studies or a project counts, not only paid work.":
        "Completează-ți mai întâi profilul - nu există nimic cu care să potrivim joburi. Studiile sau un proiect contează, nu doar munca plătită.",
    "One run is already going. Two at once can send the same application twice, so this one was not started.":
        "O rulare este deja în curs. Două în același timp pot trimite aceeași candidatură de două ori, așa că aceasta nu a fost pornită.",
    "Job title":
        "Postul",
    "Employer":
        "Angajator",
    "Where":
        "Unde",
    "From":
        "Din",
    "Until":
        "Până",
    "Qualification":
        "Calificare",
    "School or university":
        "Școală sau universitate",
    "Project":
        "Proiect",
    "What it was":
        "În ce a constat",
    "Link":
        "Link",
    "What you did":
        "Ce ai făcut",
    "Nothing yet.":
        "Încă nimic.",
    "No languages yet.":
        "Încă nicio limbă.",
    "No suggestions — looks solid.":
        "Nicio sugestie — arată bine.",
    "+ add":
        "+ adaugă",
    "level…":
        "nivel…",
    "Native":
        "Nativ",
    "Advanced":
        "Avansat",
    "Upper-intermediate":
        "Intermediar-avansat",
    "Intermediate":
        "Intermediar",
    "Beginner":
        "Începător",
    "Use this":
        "Folosește",
    "better with a photo":
        "mai bun cu poză",
    "better without photo":
        "mai bun fără poză",
    "works either way":
        "arată bine oricum",
    "Default template: {name}.":
        "Șablon implicit: {name}.",
    "Could not read the AI model settings.":
        "Nu am putut citi setările modelului AI.",
    "The AI model panel could not load. The app itself is fine - reload the page, and if it keeps happening check the black window for an error.":
        "Panoul modelului AI nu s-a putut încărca. Aplicația în sine funcționează - reîncarcă pagina, iar dacă se repetă, verifică fereastra neagră pentru o eroare.",
    "searching...":
        "caut...",
    "parsing...":
        "citesc...",
    "thinking...":
        "mă gândesc...",
    "starting...":
        "pornesc...",
    "testing...":
        "testez...",
    "loading...":
        "încarc...",
    "uploading...":
        "încarc...",
    "clearing...":
        "șterg...",
    "erasing...":
        "șterg tot...",
    "queueing...":
        "adaug la coadă...",
    "applying...":
        "aplic...",
    "reading CV...":
        "citesc CV-ul...",
    "reading Hipo...":
        "citesc Hipo...",
    "writing CV...":
        "scriu CV-ul...",
    "opening...":
        "deschid...",
    "sending, ~15s...":
        "trimit, ~15s...",
    "applying, ~15s each...":
        "aplic, ~15s fiecare...",
    "Could not reach the website or the app. Check your internet connection, and that the black run.bat window is still open.":
        "Nu am putut ajunge la site sau la aplicație. Verifică conexiunea la internet și că fereastra neagră run.bat este încă deschisă.",
    "The AI model has used up its free quota for now. Wait a few minutes, or add another provider key under Settings.":
        "Modelul AI și-a consumat cota gratuită deocamdată. Așteaptă câteva minute sau adaugă cheia altui furnizor în Setări.",
    "The API key was refused. Open Settings and paste it again.":
        "Cheia API a fost refuzată. Deschide Setări și lipește-o din nou.",
    "The app hit an internal error. Close the black window and double-click run.bat again.":
        "Aplicația a întâmpinat o eroare internă. Închide fereastra neagră și dă dublu-clic pe run.bat din nou.",
    "Fill in your profile first: open the Profile tab and upload your CV.":
        "Completează-ți mai întâi profilul: deschide fila Profil și încarcă-ți CV-ul.",
    "Go back one step":
        "Înapoi cu un pas",
    "Every save keeps the copy it replaced. If an upload read your CV badly, or you deleted something you wanted, this puts that copy back. One step only — it is the profile as it was immediately before the most recent save.":
        "Fiecare salvare păstrează copia pe care a înlocuit-o. Dacă o încărcare ți-a citit greșit CV-ul sau ai șters ceva ce voiai să păstrezi, asta pune copia la loc. Doar un pas — este profilul așa cum era imediat înainte de ultima salvare.",
    "Restore the previous copy":
        "Restaurează copia anterioară",
    "This replaces what is on the page now with the copy from before your last save. Anything typed since then is lost. Continue?":
        "Asta înlocuiește ce este acum pe pagină cu copia dinainte de ultima salvare. Tot ce ai scris de atunci se pierde. Continui?",
    "Put back the copy from before your last save.":
        "Am pus la loc copia dinainte de ultima salvare.",
    "restoring...":
        "restaurez...",
    "Paste the text of your CV into the box first.":
        "Lipește mai întâi textul CV-ului în casetă.",
    "This replaces your whole profile with whatever the model reads out of that text. The copy it replaces is kept as profile.previous.json. Continue?":
        "Asta îți înlocuiește tot profilul cu ce citește modelul din acel text. Copia înlocuită este păstrată ca profile.previous.json. Continui?",
    "Your last change could not be saved, so the CV was not built. Fix that first or the PDF will be out of date.":
        "Ultima modificare nu a putut fi salvată, așa că CV-ul nu a fost generat. Rezolvă asta întâi, altfel PDF-ul va fi depășit.",
    "Building your CV — the download starts in a moment.":
        "Îți generez CV-ul — descărcarea începe imediat.",
    "building...":
        "generez...",
    "Could not load the ad.":
        "Nu am putut încărca anunțul.",
    "Could not check the board sign-ins just now.":
        "Nu am putut verifica acum autentificările pe site-uri.",
    "Could not read your profile, so the checklist and the alerts above are not showing. The app itself is fine - reload the page.":
        "Nu am putut citi profilul, așa că lista de verificare și alertele de mai sus nu apar. Aplicația în sine funcționează - reîncarcă pagina.",
    "Could not read the CV templates. The rest of the page still works.":
        "Nu am putut citi șabloanele de CV. Restul paginii funcționează.",
    "No templates found in templates/cv/.":
        "Niciun șablon găsit în templates/cv/.",
    "Your photo will be put on new CVs.":
        "Poza ta va fi pusă pe CV-urile noi.",
    "New CVs will be written without a photo.":
        "CV-urile noi vor fi scrise fără poză.",
    "Erased {n} item(s). Starting fresh.":
        "Am șters {n} element(e). O luăm de la capăt.",
    "Erased {n} item(s), but {k} could NOT be removed and are still on this PC: {which}. Close the app (the black run.bat window) and press this again.":
        "Am șters {n} element(e), dar {k} NU au putut fi șterse și sunt încă pe acest PC: {which}. Închide aplicația (fereastra neagră run.bat) și apasă din nou aici.",
    "{n} applied":
        "{n} au aplicat",
    "(est.)":
        "(est.)",
    "The board's own estimate for an ad that states no pay. The employer never said this - do not quote it back to them.":
        "Estimarea site-ului pentru un anunț care nu menționează salariul. Angajatorul nu a spus asta - nu i-o cita înapoi.",
    "Hardly anyone has applied yet. Apply today.":
        "Aproape nimeni nu a aplicat încă. Aplică azi.",
    "A normal queue for this board.":
        "O coadă obișnuită pentru acest site.",
    "A long queue. Your CV has to survive a pile this big before a person reads it.":
        "O coadă lungă. CV-ul tău trebuie să supraviețuiască unui teanc atât de mare înainte să îl citească un om.",
    "Few applicants":
        "Puțini candidați",
    "Few applicants so far":
        "Puțini candidați deocamdată",
    "Few applicants — these are the ones worth your time.":
        "Puțini candidați — acestea sunt cele care merită timpul tău.",
    "Applying is not free: a tailored CV is a model call and twenty minutes of your attention, and an ad with two thousand people in the queue will not repay either. Only BestJobs publishes how many have applied, so this list is BestJobs ads only — the other boards do not say.":
        "Aplicarea nu este gratuită: un CV adaptat înseamnă un apel către model și douăzeci de minute din atenția ta, iar un anunț cu două mii de oameni la coadă nu îți va răsplăti niciuna dintre ele. Doar BestJobs publică numărul de candidați, așa că lista conține doar anunțuri BestJobs — celelalte site-uri nu spun.",
    "Worth a nudge":
        "Merită un memento",
    "sent today":
        "trimisă azi",
    "waiting {n} days":
        "așteaptă de {n} zile",
    "{n} days — worth a nudge":
        "{n} zile — merită un memento",
    "Long enough that a short, polite follow-up is normal and welcome.":
        "A trecut destul timp încât un mesaj scurt și politicos de revenire este normal și binevenit.",
    "Still inside the time employers usually take.":
        "Încă în intervalul în care angajatorii răspund de obicei.",
    "seen":
        "văzută",
    "interview":
        "interviu",
    "rejected":
        "respinsă",
    "offer":
        "ofertă",
    "applied":
        "ai aplicat",
    "applied (date not recorded)":
        "ai aplicat (data nu a fost înregistrată)",
    "Sign in again by itself, if a session lapses while you are away":
        "Autentificare automată, dacă o sesiune expiră cât ești plecat",
    "The scheduled run happens with nobody at the keyboard. If a board has signed you out by then, it sends nothing at all. Save the sign-in here and it can log in again by itself —":
        "Rularea programată are loc fără nimeni la tastatură. Dacă un site te-a deconectat până atunci, nu trimite nimic deloc. Salvează aici datele de autentificare și se poate conecta singur —",
    "once":
        "o singură dată",
    ", only when the board has just said you are signed out, and never twice in a row.":
        ", doar când site-ul tocmai a spus că ești deconectat, și niciodată de două ori la rând.",
    "It stays on this PC.":
        "Rămâne pe acest PC.",
    "It is written to one file in this folder, encrypted so that only your Windows account can read it, and it is never sent anywhere except the board's own login page — the same page you would type it into yourself. Nothing goes to this app's author, to GitHub, or to any server. It is left out of the zip you share with friends and out of the repository.":
        "Se scrie într-un singur fișier din acest folder, criptat astfel încât doar contul tău Windows să îl poată citi, și nu este trimis nicăieri în afară de pagina de login a site-ului — aceeași pagină în care ai scrie-o și tu. Nimic nu ajunge la autorul aplicației, pe GitHub sau pe vreun server. Este exclus din arhiva pe care o dai prietenilor și din depozitul de cod.",
    "Two honest caveats, then it is your call. The encryption means a copy of the file taken anywhere else — a backup, a stolen drive — is unreadable, but it cannot protect against something already running as you on this PC; nothing stored on a computer can. And a password is worth more than the cookie beside it: it does not expire, it often opens other sites too, and it can change the account's email.":
        "Două avertismente sincere, apoi decizia îți aparține. Criptarea înseamnă că o copie a fișierului dusă oriunde altundeva — o copie de siguranță, un disc furat — este ilizibilă, dar nu te poate apăra de ceva ce rulează deja ca tine pe acest PC; nimic stocat pe un calculator nu poate. Iar o parolă valorează mai mult decât cookie-ul de lângă ea: nu expiră, deseori deschide și alte site-uri și poate schimba emailul contului.",
    "Not trusting a tool from the internet with your password is a perfectly sensible choice.":
        "Să nu ai încredere într-un program de pe internet cu parola ta este o alegere cât se poate de rezonabilă.",
    "Leave these empty and sign in by hand with the buttons above — everything else in the app works exactly the same, you just sign in yourself when a session lapses.":
        "Lasă câmpurile goale și autentifică-te manual cu butoanele de mai sus — tot restul aplicației funcționează exact la fel, doar că te conectezi singur când expiră o sesiune.",
    "Show password":
        "Arată parola",
    "Hide password":
        "Ascunde parola",
    "not saved":
        "nesalvat",
    "Encrypted to this Windows account. It never leaves this PC.":
        "Criptat pentru acest cont Windows. Nu părăsește niciodată acest PC.",
    "Hipo applies like the other two now — its sign-in used to stop working the moment the login window closed, and that was fixed. One thing to know: Hipo confirms nothing. When an application goes through it simply removes the apply button, so that is what the app reads as success. Many Hipo ads also hand you to the employer's own site rather than taking an application; those are marked and opened for you, never submitted.":
        "Hipo aplică la fel ca celelalte două acum — autentificarea lui se strica în momentul în care se închidea fereastra de login, iar asta a fost rezolvat. Un lucru de știut: Hipo nu confirmă nimic. Când o candidatură trece, pur și simplu elimină butonul de aplicare, iar asta este ce citește aplicația drept succes. Multe anunțuri Hipo te trimit la site-ul angajatorului în loc să primească o candidatură; acelea sunt marcate și deschise pentru tine, niciodată trimise.",
    "You send these yourself.":
        "Pe acestea le trimiți tu.",
    "Everything the app cannot submit for you: freehire, the employer-run forms, and any board posting whose apply button hands you to the employer's own website rather than taking an application.":
        "Tot ce aplicația nu poate trimite în locul tău: freehire, formularele angajatorilor și orice anunț de pe un site al cărui buton de aplicare te trimite la pagina angajatorului în loc să primească o candidatură.",
    "then":
        "apoi",
    "is the flow — the app writes the PDF and opens the form with what it can fill already filled, and you press send. None of these is ever picked up by":
        "este fluxul — aplicația scrie PDF-ul și deschide formularul cu ce poate completa deja completat, iar tu apeși trimite. Niciunul dintre acestea nu este preluat vreodată de",
    "You apply yourself":
        "Aplici tu",
    "you apply":
        "aplici tu",
    "The app cannot send this one - tailor a CV and apply on their site":
        "Aplicația nu poate trimite această candidatură - adaptează un CV și aplică pe site-ul lor",
    "or batch apply, so nothing here goes out by accident.":
        "sau de aplicarea în lot, așa că nimic de aici nu pleacă din greșeală.",
    "— after that search, it applies to the highest-scoring jobs on the boards that take an application directly: eJobs, BestJobs and Hipo. Employer forms, and ads that hand you to the employer's own site, are never sent for you. A board apply attaches the CV stored on that board's profile, not the tailored PDF this app writes, so an out-of-date board profile is what the employer sees. Read the warning below before turning it on.":
        "— după acea căutare, aplică la joburile cu cel mai mare punctaj de pe site-urile care primesc o candidatură direct: eJobs, BestJobs și Hipo. Formularele angajatorilor și anunțurile care te trimit pe site-ul angajatorului nu sunt trimise niciodată în locul tău. O aplicare pe un site atașează CV-ul salvat în profilul de pe acel site, nu PDF-ul adaptat pe care îl scrie aplicația, așa că un profil neactualizat este ceea ce vede angajatorul. Citește avertismentul de mai jos înainte să o pornești.",
    "Why the cap stops at 50.":
        "De ce limita se oprește la 50.",
    "Not because fifty applications take too long — they are about twenty minutes, and the task is allowed two hours. Because an unattended run that sends fifty applications with an out-of-date board profile is fifty employers who saw it, and you find out afterwards. The number is a wall against typing 500 by mistake. In practice the score does the limiting: a floor of 85 usually leaves single figures waiting, so the cap rarely comes into it at all. If you want more applications going out, lower the score before you raise the cap — that changes which jobs qualify, which is the decision that actually matters.":
        "Nu pentru că cincizeci de candidaturi durează prea mult — durează cam douăzeci de minute, iar sarcina are voie două ore. Ci pentru că o rulare fără supraveghere care trimite cincizeci de candidaturi cu un profil neactualizat pe site înseamnă cincizeci de angajatori care l-au văzut, iar tu afli după. Numărul este un zid împotriva tastării lui 500 din greșeală. În practică punctajul este cel care limitează: un prag de 85 lasă de obicei sub zece joburi în așteptare, așa că limita rareori intră în discuție. Dacă vrei să plece mai multe candidaturi, coboară punctajul înainte să ridici limita — asta schimbă ce joburi se califică, ceea ce este decizia care contează cu adevărat.",
    "Anything from 1 to 50.":
        "Orice valoare între 1 și 50.",
    "The score above usually decides this, not the number here":
        "Punctajul de mai sus decide de obicei, nu numărul de aici",
    "— at 85 there are rarely more than a handful of jobs waiting, so asking for 50 simply sends however many qualify. 50 is a wall against a slipped keystroke, not a target. Employer forms and ads that redirect to the employer's own site are never sent for you.":
        "— la 85 rareori așteaptă mai mult de câteva joburi, așa că dacă ceri 50 pur și simplu se trimit câte se califică. 50 este un zid împotriva unei apăsări greșite de tastă, nu o țintă. Formularele angajatorilor și anunțurile care trimit către site-ul angajatorului nu sunt trimise niciodată în locul tău.",
    "replies":
        "răspunde",
    "The board says this employer answers applications. No other signal here is about the employer rather than about you.":
        "Site-ul spune că acest angajator răspunde la candidaturi. Niciun alt indiciu de aici nu este despre angajator, ci despre tine.",
    "Days":
        "Zile",
    "Every day":
        "În fiecare zi",
    "Weekdays":
        "Zile lucrătoare",
    "Once a week":
        "O dată pe săptămână",
    "Mon":
        "Lun",
    "Tue":
        "Mar",
    "Wed":
        "Mie",
    "Thu":
        "Joi",
    "Fri":
        "Vin",
    "Sat":
        "Sâm",
    "Sun":
        "Dum",
    "It has to run on at least one day.":
        "Trebuie să ruleze în cel puțin o zi.",
    "Search and score on its own, on the days you pick":
        "Caută și punctează singur, în zilele pe care le alegi",
    "Each run spends AI quota on the scoring, whether or not you look at the result — so seven days a week costs seven times one, for mostly the same jobs, since a posting appears once rather than daily. Daily suits a hard hunt in a fast market; it is not automatically better.":
        "Fiecare rulare consumă din cota AI pentru punctare, indiferent dacă te uiți sau nu la rezultat — așa că șapte zile pe săptămână costă de șapte ori cât una, pentru cam aceleași joburi, fiindcă un anunț apare o dată, nu zilnic. Zilnic se potrivește unei căutări intense pe o piață rapidă; nu este automat mai bine.",
    "— Windows starts it on the days and at the time you pick, with the app closed; the black run.bat window does not need to be open. It searches the same terms you saved, across the same boards, and scores everything new against your profile. It sends nothing. Each run spends AI quota on the scoring, whether or not you look at the result — so seven days a week costs seven times one, for mostly the same jobs, since a posting appears once rather than daily. Daily suits a hard hunt in a fast market; it is not automatically better.":
        "— Windows o pornește în ziua și la ora pe care le alegi, cu aplicația închisă; fereastra neagră run.bat nu trebuie să fie deschisă. Caută aceiași termeni pe care i-ai salvat, pe aceleași site-uri, și punctează tot ce este nou față de profilul tău. Nu trimite nimic. Fiecare rulare consumă din cota AI pentru punctare, indiferent dacă te uiți sau nu la rezultat — așa că șapte zile pe săptămână costă de șapte ori cât una, pentru cam aceleași joburi, fiindcă un anunț apare o dată, nu zilnic. Zilnic se potrivește unei căutări intense pe o piață rapidă; nu este automat mai bine.",
    "Forget":
        "Uită",
    "Forget the saved sign-in for this board?":
        "Uit datele de autentificare salvate pentru acest site?",
    "Forgotten.":
        "Am uitat-o.",
    "Nothing saved. Sessions that lapse while you are away will simply mean no applications go out.":
        "Nimic salvat. Sesiunile care expiră cât ești plecat vor însemna pur și simplu nicio candidatură în acea perioadă.",
    "Saved for {which}. Used only by the scheduled run, and only when the board says you are signed out.":
        "Salvat pentru {which}. Folosit doar de rularea programată și doar când site-ul spune că ești deconectat.",
    "Saved, encrypted to this Windows account.":
        "Salvat, criptat pentru acest cont Windows.",
    "Stopped using this one - it failed twice. Save it again to re-enable.":
        "Nu o mai folosesc - a eșuat de două ori. Salveaz-o din nou pentru a o reactiva.",
    "Type both the username and the password first.":
        "Scrie mai întâi și utilizatorul, și parola.",
    "email or username":
        "email sau utilizator",
    "password":
        "parolă",
    "saved — type to replace":
        "salvat — scrie pentru a înlocui",
    "Applied jobs stay in the history and cannot be changed.":
        "Joburile la care ai aplicat rămân în istoric și nu pot fi modificate.",
    "Applied jobs stay in the history and cannot be deleted.":
        "Joburile la care ai aplicat rămân în istoric și nu pot fi șterse.",
    "Applying happens during the scheduled run, so switch that on too.":
        "Aplicarea are loc în timpul rulării programate, deci pornește-o și pe aceea.",
    "Could not read text from that file (scanned image PDF?). Paste the text instead.":
        "Nu am putut citi text din acel fișier (PDF scanat ca imagine?). Lipește textul în loc.",
    "Fill in your profile first - there is nothing to put on a CV.":
        "Completează-ți mai întâi profilul - nu este nimic de pus pe un CV.",
    "Not confirmed, so nothing was erased.":
        "Neconfirmat, așa că nu s-a șters nimic.",
    "Not confirmed.":
        "Neconfirmat.",
    "Only new or vetoed rows can be cleared.":
        "Doar rândurile noi sau respinse pot fi curățate.",
    "Only vetoed or skipped jobs can be queued again. Applied jobs are the record of what you sent.":
        "Doar joburile respinse sau sărite pot fi puse din nou la coadă. Cele la care ai aplicat sunt evidența a ceea ce ai trimis.",
    "Pick at least one day for it to run on.":
        "Alege cel puțin o zi în care să ruleze.",
    "Refusing to delete rows you have acted on.":
        "Refuz să șterg rânduri pe care ai acționat deja.",
    "That does not look like a JPG or a PNG. Those are the two a CV can carry safely.":
        "Asta nu pare a fi un JPG sau un PNG. Acestea două sunt singurele pe care un CV le poate purta în siguranță.",
    "That is the only provider left, so pausing it would stop the app doing anything. Add another one first.":
        "Acesta este singurul furnizor rămas, așa că oprirea lui ar împiedica aplicația să mai facă ceva. Adaugă altul mai întâi.",
    "There is no previous copy to go back to yet.":
        "Nu există încă o copie anterioară la care să revii.",
    "Too late to undo - applied jobs stay in the history.":
        "Prea târziu pentru anulare - joburile la care ai aplicat rămân în istoric.",
    "Type what the scheduled run should search for.":
        "Scrie ce ar trebui să caute rularea programată.",
    "lang must be auto, en or ro":
        "lang trebuie să fie auto, en sau ro",
    "no photo saved":
        "nicio poză salvată",
    "no such template":
        "nu există acest șablon",
    "nothing selected":
        "nimic selectat",
    "path must be a dotted string into the profile":
        "path trebuie să fie un șir cu puncte care indică în profil",
    "status must be a list of statuses":
        "status trebuie să fie o listă de stări",
    "suggestion has no path":
        "sugestia nu are o cale",
    "the score and the cap must be numbers":
        "punctajul și limita trebuie să fie numere",
    "time must be HH:MM, e.g. 09:00":
        "ora trebuie să fie HH:MM, de exemplu 09:00",
    "url is required":
        "url este obligatoriu",
    "That file is named .docx but does not open as one. If you renamed a .doc, use Save As in Word to make a real .docx - or paste the text in.":
        "Fișierul se numește .docx dar nu se deschide ca atare. Dacă ai redenumit un .doc, folosește Salvare ca în Word pentru a face un .docx real - sau lipește textul aici.",
    "That file is named .pdf but does not open as one. If you renamed it, use Save As in Word instead - or paste the text in.":
        "Fișierul se numește .pdf dar nu se deschide ca atare. Dacă l-ai redenumit, folosește Salvare ca în Word - sau lipește textul aici.",
    "That is an old Word (.doc) file, which this app cannot read. Open it in Word and use Save As to make a .docx or a PDF - or paste the text in instead.":
        "Acesta este un fișier Word vechi (.doc), pe care aplicația nu îl poate citi. Deschide-l în Word și folosește Salvare ca pentru a face un .docx sau un PDF - sau lipește textul aici.",
    "That would have emptied your whole profile, so it was not saved. Reload the page - if the fields come back, the page had failed to load rather than your data being gone.":
        "Asta ți-ar fi golit tot profilul, așa că nu a fost salvat. Reîncarcă pagina - dacă revin câmpurile, pagina nu se încărcase, nu ți-au dispărut datele.",
    "That would have emptied your whole profile, so nothing was saved. If a CV you uploaded came back almost empty, the file probably has no readable text - try the PDF, or paste the text in instead.":
        "Asta ți-ar fi golit tot profilul, așa că nu s-a salvat nimic. Dacă un CV încărcat a revenit aproape gol, fișierul probabil nu are text lizibil - încearcă PDF-ul sau lipește textul aici.",
    "Your profile file is on disk but could not be read, so this page came up blank and the save was refused rather than writing that blank page over it. Check profile.json is valid JSON - your data is still in there.":
        "Fișierul de profil este pe disc dar nu a putut fi citit, așa că pagina a apărut goală iar salvarea a fost refuzată în loc să scrie pagina goală peste el. Verifică dacă profile.json este JSON valid - datele tale sunt încă acolo.",
    " — across {n} scored jobs":
        " — din {n} joburi punctate",
    "({n} more are ticked; one run sends {cap}, the rest stay selected.)":
        "({n} în plus sunt bifate; o rulare trimite {cap}, restul rămân selectate.)",
    ", answered {n} question(s)":
        ", a răspuns la {n} întrebare/întrebări",
    ", left {n} for you":
        ", a lăsat {n} pentru tine",
    ", {n} closed or aged out":
        ", {n} închise sau expirate",
    " (<b>{n}</b> of them you would have applied to)":
        " (<b>{n}</b> dintre ele la care ai fi aplicat)",
    ". <b>{n}</b> waiting at {floor}+.":
        ". <b>{n}</b> în așteptare la {floor}+.",
    "About to send {n} real application(s):":
        "Pe punctul de a trimite {n} candidatură/candidaturi reale:",
    "Added {n} to your Applied history: {which}":
        "S-au adăugat {n} în istoricul aplicărilor: {which}",
    "Cancel = not yet.":
        "Anulează = încă nu.",
    "Delete {n} result(s) you have not acted on?":
        "Ștergi {n} rezultat(e) pe care nu le-ai atins?",
    "Did you send your application for:":
        "Ai trimis candidatura pentru:",
    "Dry run on {ats}: filled {n} field(s)":
        "Test pe {ats}: a completat {n} câmp(uri)",
    "Hipo lists {n} application(s), and none of them are jobs in your list ({old} were sent before this app knew about them).":
        "Hipo listează {n} candidatură/candidaturi, și niciuna nu este un job din lista ta ({old} au fost trimise înainte ca aplicația să știe de ele).",
    "It is sent as your {where} profile — the CV stored on {where}, not the tailored PDF.":
        "Se trimite ca profilul tău de {where} — CV-ul salvat pe {where}, nu PDF-ul adaptat.",
    "Last run {when}: ":
        "Ultima rulare {when}: ",
    "Nothing scores {floor}+ right now, so it would send nothing.":
        "Nimic nu are {floor}+ acum, așa că nu ar trimite nimic.",
    "OK = yes, add it to my Applied history.":
        "OK = da, adaug-o în istoricul aplicărilor.",
    "Opening the {ats} form with your details filled in. Check every field, then submit it yourself.":
        "Se deschide formularul {ats} cu datele tale completate. Verifică fiecare câmp, apoi trimite-l tu.",
    "Scheduled with Windows.":
        "Programată în Windows.",
    "Scheduled — next run <b>{when}</b>.":
        "Programată — următoarea rulare <b>{when}</b>.",
    "Signed in to {board}.":
        "Autentificat pe {board}.",
    "Still not signed in to {board}. Sign in inside the window this app opened — a session in your normal Chrome is not shared with it.":
        "Încă nu ești autentificat pe {board}. Autentifică-te în fereastra deschisă de aplicație — o sesiune din Chrome-ul tău obișnuit nu este partajată cu ea.",
    "This one has a mini interviu ({n} question(s)). Opening it with your answers filled in — read it and press Trimite.":
        "Acesta are un mini interviu ({n} întrebare/întrebări). Se deschide cu răspunsurile tale completate — citește-l și apasă Trimite.",
    "With your settings (score {floor}+, at most {cap} a run), THESE would have":
        "Cu setările tale (punctaj {floor}+, cel mult {cap} pe rulare), ACESTEA ar fi fost",
    "You are not signed in to {who}, so nothing would be sent":
        "Nu ești autentificat pe {who}, așa că nu s-ar trimite nimic",
    "You are signed out of {who}":
        "Ești deconectat de la {who}",
    "been sent, with nobody reading them first:":
        "trimise, fără ca nimeni să le citească înainte:",
    "until you are.":
        "până când o faci.",
    "{found} ads seen, {fresh} new, {scored} scored":
        "{found} anunțuri văzute, {fresh} noi, {scored} punctate",
    "{found} ads seen, {fresh} new. Scored {scored}.":
        "{found} anunțuri văzute, {fresh} noi. Punctate {scored}.",
    "{kept} stay: everything applied, opened, tailored or skipped. Skipped rows are kept on purpose so a job you rejected does not come straight back on the next search.":
        "{kept} rămân: tot ce e aplicat, deschis, adaptat sau refuzat. Rândurile refuzate sunt păstrate intenționat, ca un job pe care l-ai respins să nu revină imediat la următoarea căutare.",
    "{n} closed or aged out.":
        "{n} închise sau expirate.",
    "{n} of those you would have applied to.":
        "{n} dintre acelea la care ai fi aplicat.",
    "{n} failed — search again to retry them.":
        "{n} au eșuat — caută din nou pentru a le reîncerca.",
    "{n} job(s) queued — press Search & score to re-run them.":
        "{n} job(uri) în coadă — apasă Caută și punctează pentru a le relua.",
    "{n} match, selected the first {cap} — that is the most one run will send.":
        "{n} se potrivesc, s-au selectat primele {cap} — atât trimite o rulare.",
    "{n} re-opened by the language check.":
        "{n} redeschise de verificarea limbii.",
    "{n} skipped on language.":
        "{n} sărite din cauza limbii.",
    "Added {term}. Save the schedule when you are done.":
        "S-a adăugat {term}. Salvează programarea când ai terminat.",
    "Click any of these to add it. Each one says what in your CV it came from.":
        "Apasă pe oricare pentru a o adăuga. Fiecare spune din ce parte a CV-ului tău provine.",
    "Nothing to suggest from your profile yet - fill in your experience and skills first.":
        "Nu este nimic de sugerat din profilul tău încă - completează mai întâi experiența și competențele.",
    "{term} is already in the box.":
        "{term} este deja în casetă.",
    "Suggest terms from my CV":
        "Sugerează termeni din CV-ul meu",
    "Read the CV and propose titles you might not think of. Nothing is filled in until you click one.":
        "Citește CV-ul și propune titluri la care poate nu te-ai gândi. Nu se completează nimic până nu apeși pe una.",
    "reading your CV...":
        "citesc CV-ul tău...",
    "Fill in your profile first - there is nothing here to read yet.":
        "Completează mai întâi profilul - deocamdată nu este nimic de citit aici.",
    "Still waiting on the AI provider. The first request after a quiet spell can be slow while one that has gone quiet is dropped.":
        "Încă se așteaptă furnizorul AI. Prima cerere după o pauză poate fi lentă, cât timp unul care a amuțit este scos din listă.",
    "{n} suggestion(s) left out: they were built on words that have never found you a job.":
        "{n} sugestie/sugestii lăsate deoparte: erau construite pe cuvinte care nu ți-au găsit niciodată un job.",
    "Could not read your settings just now, so the controls below show defaults. Nothing on disk was changed - reload to try again.":
        "Nu am putut citi setările acum, așa că opțiunile de mai jos arată valorile implicite. Nimic de pe disc nu a fost modificat - reîncarcă pagina pentru a încerca din nou.",
    "Running it now, exactly as Windows will. It takes a few minutes — this panel shows the result when it lands.":
        "Rulează acum, exact cum o va face Windows. Durează câteva minute — panoul afișează rezultatul când sosește.",}

# Longest first, so replacing a short string can never eat part of a longer one that contains it.
PAIRS = sorted(RO.items(), key=lambda kv: -len(kv[0]))
