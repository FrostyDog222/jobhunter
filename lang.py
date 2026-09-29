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
    "All counties": "Toate județele",
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
    "Manual apply only": "Doar aplicare manuală",
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

    # ---- the weekly run
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
    "At most, per week": "Cel mult, pe săptămână",

    # ---- CV templates
    "Put my photo on it": "Pune-mi poza pe el",
    "Tailor with this template": "Adaptează cu acest model",
    "better with one": "arată mai bine cu poză",
    "this one is better without": "acesta arată mai bine fără",
    "either works": "merge și așa, și așa",
}

# Longest first, so replacing a short string can never eat part of a longer one that contains it.
PAIRS = sorted(RO.items(), key=lambda kv: -len(kv[0]))
