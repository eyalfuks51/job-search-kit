# Job search procedure ("מה חדש?" / "Find me new jobs")

Goal: a few well-judged roles, not a long list. Every role you don't show has a recorded verdict and reason.

## 1. Collect

1. Run `<python> kit/collect.py` with a 10-minute timeout.
2. Note `new`, `reposts`, `failed` and `out_of_area_top`.
3. Look at `out_of_area_top`. If a location there is clearly one of the user's places in a spelling you missed (e.g. "Tel-Aviv-Yafo", a Hebrew city name), propose adding it to `me/search.json`. It's a small fix: tell the user in one line, no approval needed. Roles excluded this run come back once the term is added only if they are posted again, so mention it.

## 2. Skim all titles (cheap, never skip)

1. Get titles one tier at a time, 300 per page: `roles.py inbox --titles-only --tier manual`, then `--tier priority`, then `--tier other`. The header gives the next page (`--after-id N`). Record set-asides after each page; the cursor stays correct.
   - **First run with a big pack** (thousands of roles): skim all manual and priority titles, then at most about 4 pages of `other`. Stop there. The rest stay unreviewed, which is the visible backlog; say how many. Continue on later runs or when the user says "תמשיך".
2. Read **every** title you fetch:
   - **Candidates:** every `manual` and `priority` role, every title that could plausibly fit the profile or its adjacent paths, and every vague title ("Generalist", "Rockstar", "Specialist"). **When unsure, it's a candidate.**
   - **Set aside** only titles that are clearly another profession, e.g. backend developer for a non-developer. Give the reason as a category: `title: software engineering`, `title: hardware`, `title: sales quota role`.
     - A seniority word alone ("Senior", "Lead") is never a reason.
     - Location is never a set-aside reason for area roles.
3. Record set-asides in bulk:

```json
[{"ids": [4, 7, 9], "verdict": "set-aside", "reasons": "title: software engineering"}]
```

## 3. Read job texts and judge

- Read candidates with `roles.py show`, about 10–15 per call: manual first, then priority, then newest.
- **Cap:** about 30–40 full reads per session. The rest stay unreviewed: that's the visible backlog. Tell the user the count, and work through it on later runs or when they ask "תמשיך".
- The first run with a large pack will have hundreds of candidates. Read the 30–40 best by priority and newest, and keep the rest in the backlog.

**Verdicts.** Every verdict cites the job text.

| Verdict | When |
|---|---|
| `strong` | Meets the job's stated must-haves, and the core of the job matches profile facts |
| `possible` | Most must-haves met; gaps are bridgeable (adjacent experience, a learnable tool, 1–2 years short) |
| `stretch` | A real gap (years, domain), but worth a look. Also: thin, missing or unreadable job text ("verify manually") |
| `no-fit` | A **named required** item clearly isn't met (quote it), or it hits a dealbreaker from the profile (place, hours, type of work) |

**Rules:**
- Count only what's required. "Advantage", "preferred", "nice to have", "יתרון" are not requirements. "חובה" and "must" are.
- A degree with "or equivalent experience" is not a block.
- Never treat the title alone as `no-fit`.
- Check where the job is and the work arrangement against the profile. Part-time wishes are matched against what the job states.
- Gaps are listed honestly. Never claim the user has something the profile doesn't show.
- **Reposts:** a role marked as a repost of an earlier role that the user already decided on is not news.
  - If the earlier one was skipped, set it aside with "repost of #N, skipped before".
  - If it was saved or applied, mention it in one line ("X was reposted").

Record the verdicts in one `apply` file:

```json
[{"id": 12, "verdict": "possible", "reasons": "Asks for 2+ yrs onboarding B2B customers (she has 4)", "gaps": "Salesforce admin required"}]
```

## 4. Show the shortlist

- At most 10 roles: strong first, then possible, then the best stretches.
- Then: "N more possible/stretch roles, want to see them?"

Format, in the user's language:

```
3. **Company – Title** (City · hybrid) — strong
   Why: 1–2 short reasons, quoting the job
   Gaps: what's missing, or "none important"
   Link: <original URL>
```

Mark manual roles "(you sent this)" and reposts "(reposted)". If a link was not verified, for example text the user pasted without a URL, say so.

**Audit line, always, in one or two sentences:**
"Checked N employers (M didn't respond). X new roles in your area since last time and Y reposts. I read A in full, set aside B by title (mostly: <top reasons>), C are waiting for review."

Add a coverage reminder when relevant, e.g. if the user named employers the kit can't watch.

## 5. Feedback

- Ask: "Which of these interest you? For the ones that don't, a word on why helps me next time."
- Record every decision the same turn (CLAUDE.md §7).
- Saved roles: when asked, or at the start of a later search, mention any saved role whose `on_board_last_run` is false ("may have closed").
