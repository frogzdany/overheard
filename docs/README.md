# Team docs

Planning and submission material for Overheard, kept separate from the code so the root
`README.md` can stay focused on running the app.

- **TEAM-BRIEF.md** — the original hackathon brief: the idea, the architecture (ears, brain,
  hands), the sponsor map, and how the work was split.
- **MILESTONES.md** — the execution plan, milestone by milestone, with a "Where we are" section
  at the top telling you what is done and what is still open.
- **SUBMISSION.md** — the draft submission package: title, description, video shot list, social
  posts, and prize angles.
- **EVENT.md** — a summary of the hackathon rules: timeline, submission checklist, judging, and
  prizes.
- **SPONSOR-RESEARCH.md** — background research on each sponsor's tooling, used to decide how
  each one fits into Overheard.

## Reading order for a new teammate

1. **TEAM-BRIEF.md** — get the idea and the architecture.
2. The root **README.md** — run the app keyless, with no accounts needed.
3. **MILESTONES.md**, starting at "Where we are" — see what's verified and what's open.
4. **SUBMISSION.md** — see what still needs to happen before the project is submitted.

## Two rules

- Never commit keys. Every `.env.example` in this repo holds placeholders only; real keys live
  in `.env` / `.env.local` files that are gitignored.
- Before pushing, run a privacy grep for personal names, employer names, absolute home-directory
  paths, and tenant-specific hostnames across any file you changed. It must return nothing.
