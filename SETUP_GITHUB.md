# Putting this on GitHub

I prepared the repository — it is initialised, everything is committed, and the history
is clean. What I cannot do is create the remote or push, because both need your GitHub
credentials and handling those on your behalf is not something you should let any agent
do. Those two steps are yours.

## What you do

**1. Create an empty repo** at https://github.com/new

- Name: `ffagent` (or anything)
- **Private** unless you want it public
- **Do not** tick "add a README", "add .gitignore", or "choose a licence" — the repo
  already has all three and an initialised remote will cause a merge conflict on the
  first push

**2. Unzip and push**

```bash
unzip ffagent-repo.zip && cd ffagent
git remote add origin https://github.com/YOUR_USERNAME/ffagent.git
git push -u origin main
```

That is it. The `.git` directory is already inside the zip with the commit made, so
there is no `git init`, `add` or `commit` to run.

If it asks for a password, GitHub wants a **personal access token**, not your account
password — https://github.com/settings/tokens, scope `repo`. Or use the GitHub CLI
(`gh auth login`) which handles it.

## Why this fixes the file problem

Once it is up, any future session can read the current code directly:

```
https://raw.githubusercontent.com/YOUR_USERNAME/ffagent/main/LOGIC.md
https://raw.githubusercontent.com/YOUR_USERNAME/ffagent/main/ffagent/myboard.py
```

`raw.githubusercontent.com` is reachable from my sandbox, so I can fetch any file on
demand. No uploading, no `.py` extension rejections, and — the part that matters — **no
stale copies**. The project-knowledge markdown bundles go out of date silently the moment
we change code, which is the exact failure that has already bitten this build twice.

Tell a new session: *"the repo is at github.com/YOUR_USERNAME/ffagent, read LOGIC.md and
HANDOFF.md"* and it can work from current source.

**If the repo is private** my sandbox cannot reach it without a token, and I will not ask
you for one. Either make it public, or keep pasting `LOGIC.md` and `HANDOFF.md` into
project knowledge and treat the repo as your own backup.

## What is in it

85 files tracked. Deliberately excluded via `.gitignore`:

- `data/*.db` — rankings, decisions and calibration state. Per-machine, and the current
  contents are test data I injected to verify the plumbing.
- `dashboard.html` — a build artefact, regenerate with `python build_dash.py`
- `__pycache__/`, scratch screenshots

`data/gamelogs.json` and `data/career.json` **are** tracked despite being regenerable,
because regenerating them takes several minutes and a network round trip to nflverse.
