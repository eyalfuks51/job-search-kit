# Setup procedure (first session)

Goal: from an empty `me/` to a first shortlist in about 30–45 minutes of the user's time. Ask **one question at a time**, never more than about 8 questions in total, and keep every message short.

## 1. Start

1. Tell the user in 2–3 lines what will happen:
   - you'll read their CV;
   - ask a few questions;
   - agree on what to search for and where;
   - run a first search.
   - Nothing is ever sent to any employer.
2. Find Python (CLAUDE.md §4). Then run `<python> kit/doctor.py --setup` and fix any `FIX` line.

## 2. CV → fact ledger

1. Ask the user to attach their CV as a PDF, or paste its text.
   - A Word file can't be read. Ask them to save it as PDF (in Word: File → Save As → PDF) or to paste the text.
2. Save a plain-text version to `me/cv/cv.md`.
3. Build a draft **fact ledger**: jobs with years, responsibilities, results, tools and systems, education, languages, certifications.
   - Only what the CV says. Nothing inferred.
4. Suggest **2–4 adjacent role families** the user may not have considered, each with one line tied to a CV fact. Examples:
   - a customer success manager → implementation, onboarding, account management, support operations;
   - an office manager → operations coordinator, HR coordinator, procurement.

## 3. Questions (one at a time, skip what the CV already answers)

1. Which roles to search: confirm or adjust your suggestions.
2. Where: cities, or how far they can travel. Is remote OK? Hybrid?
3. Full time or part time? Any hours constraint?
4. Level: what they want next (same level, a step up, open).
5. Anything they won't do (dealbreakers: e.g. sales targets, shifts, a sector).
6. Working languages.
7. Employers they already want, if any. This is optional: "Not needed, I'll find employers myself."

Salary: if the user mentions it, note it. Never use it to filter out roles.

## 4. Approve and write the profile

1. Show a plain-language summary in 6–10 lines. Ask: "Is this right? Anything to change?"
2. Only after a yes, write `me/profile.md`:

```markdown
# Profile
Approved: YYYY-MM-DD

## Facts (only these may be claimed about me)
- ...
## Target roles
- ...
## Adjacent paths worth checking
- ...
## Places and work arrangement
- ...
## Dealbreakers
- ...
## Languages
- ...
## Noted, not used for filtering
- ...
## Changelog
- YYYY-MM-DD: created
```

3. Then write `me/search.json`.
   - **locations.include:** case-insensitive patterns for the user's places.
     - Each place in every common spelling and in Hebrew.
     - Include the country, so "Israel" alone matches.
     - Keep patterns simple.
   - **locations.exclude:** look-alikes to remove before matching. For Israel: `US-IL`, `chicago(,\s*IL\b)?`, `illinois`.
   - **keep_unplaced_remote:** true only if the user is open to remote work. It keeps roles whose location just says "Remote" (in the Israeli pack that is about 500 extra roles, many of them US-only).
   - **priority_keywords:** broad English and Hebrew variants of the target roles and adjacent paths, as word fragments (`implement` catches implementation and implementer; `הטמע`, `מיישמ`). Aim for 15–40 terms. This decides what is skimmed and read first. It **never** hides a role, so be generous.
   - **smartrecruiters_country:** a two-letter code, only when all the user's places are in one country.

   Israel example:

```json
{
  "locations": {
    "include": ["israel", "ישראל", "tel.?aviv", "תל.?אביב", "herzl", "הרצליה", "ramat.?gan", "רמת.?גן", "petah", "פתח.?תקו", "\\bIL\\b", "\\bTLV\\b"],
    "exclude": ["US-IL", "chicago(,\\s*IL\\b)?", "illinois"],
    "keep_unplaced_remote": false
  },
  "priority_keywords": ["customer success", "onboarding", "implementation", "account manag", "הצלחת לקוח", "הטמע"],
  "smartrecruiters_country": "il"
}
```

Include only the user's places. A user in Haifa doesn't need Herzliya, but "Israel" and "IL" stay, so country-only locations match.

## 5. Sources: which employers to watch

Explain in one line that the kit can read some employers' job boards directly, but not all of them.

1. **Ready-made pack.**
   - If the user is in Israel and the roles exist at tech companies (most office roles do: operations, HR, finance, marketing, customer-facing, product, support), offer the Israeli tech pack: "about 290 Israeli tech companies".
   - On a yes, run `boards.py add-pack israel-tech`.
2. **Employers the user named.** For each one:
   - WebSearch "<employer> careers" or "<employer> jobs";
   - run `boards.py detect <careers page URL>`, then `boards.py check` on a hit;
   - add the working ones with `boards.py add`.
3. **Discover more** (best effort, about 15 searches at most):
   - search for employers in the user's field and area (e.g. "<field> companies in <city>", "largest <sector> employers <country>", "<role> jobs <city> greenhouse OR lever OR comeet");
   - pick 10–20 plausible employers, run `detect` on each careers page, check and add the supported ones.
   - Native web search is weak for Hebrew and local queries. Say so if results are thin.
4. **Coverage report** for the user (short):
   - "Watching N employers."
   - "These you named aren't covered: X (uses an unsupported system), Y (no readable careers page)."
   - What to set up themselves:
     - a LinkedIn job alert with the exact search terms you suggest;
     - alerts on local job sites (Israel: AllJobs, Drushim);
     - the employer's own alerts.
   - "Paste any job you get from those and I'll check it."
5. Ask the user to approve the list in one sentence ("watch these N employers?") **before** adding non-pack employers in bulk.

If almost nothing is covered (e.g. a non-tech field outside the pack), say it plainly. The kit is then mainly a fit-checker and tracker for roles the user pastes, plus the alerts above. That's a useful outcome, not a failure.

## 6. First search

1. Run the job search as in `docs/screening.md`.
   - The first run sees every open role, so the inbox is big.
   - Follow the first-run cap there.
2. After the shortlist, explain the routine in 3 lines:
   - say "מה חדש?" every day or two;
   - paste any job you find;
   - tell me what you liked or didn't, and why.
3. Then add: "Next time, start a new session in this same folder, so everything runs without extra approval prompts."
