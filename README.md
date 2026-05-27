# pletor-pipeline-setup

A [Claude Code](https://claude.com/claude-code) skill that scaffolds **other** Pletor pipeline skills. Run it once per pipeline you want to build, answer a few questions, and you get a complete, self-contained pipeline skill ready to use.

## What it does

When triggered, it asks you:

1. **API key** — where to store it (default `~/.pletor.env`), and optionally pastes it in for you with `umask 077`
2. **Skill name** — kebab-case, becomes the folder under `~/.claude/skills/`
3. **Pipeline shape** — 1, 2, or N (up to 10) Pletor flows in a linear chain
4. **Per flow** — flow ID + a short label (e.g. `static`, `video`, `upscale`)
5. **Drive integration** — optional, per-flow at run time (some flows take a Drive URL input, some don't)
6. **Project dir** — local workspace for Inputs/Outputs

Then it generates:

```
~/.claude/skills/<your-pipeline-name>/
├── SKILL.md              ← rendered from a template; reads config.json at runtime
├── upload.py             ← REST helper for local file → Pletor asset_id
├── config.json           ← filled in with YOUR answers
├── config.example.json   ← template version (committable)
├── README.md             ← user-facing instructions
└── .gitignore            ← protects config.json + asset_map.json + flows.json + *.env
```

Plus:

```
<project_dir>/
├── Inputs/    ← drop your assets here
└── Outputs/   ← batch folders end up here
```

And, optionally as a final step, **publishes the generated skill to GitHub** as a public or private repo (you'll be asked).

## What it does NOT do

- **Never fires a Pletor run** — zero credit spend during scaffolding.
- **Never uploads any asset** — the generated skill does that, only after you say Yes.
- **Never overwrites files without confirmation** — if the target skill folder exists, you'll be asked.
- **Never echoes your API key back** — it's only written to the env file, never logged.

## Pipeline topology supported

Linear chain of 1 to N flows where:
- Step 0 takes assets from `Inputs/` (one variation per asset, all in parallel).
- Step k > 0 takes the **first successful output** of step k-1 (alphabetical by source filename). One variation.

For each step, the generated skill prints a preview table and waits for Yes/No before firing `prepare_batch`. **No silent fires, ever.**

## When to use

- You have a single-step Pletor pipeline (e.g. upscale a batch of images) → 1-flow setup.
- You have a chained two-step pipeline (e.g. static ad → video) → 2-flow setup.
- You have a longer chain (e.g. extract → enhance → upscale → composite) → N-flow setup.

If your pipeline is a DAG with forks/joins, this scaffold doesn't cover it — edit the generated SKILL.md by hand.

## Trigger phrases

- "set up a new Pletor pipeline"
- "create a pletor pipeline skill"
- "scaffold a pletor pipeline"
- "bootstrap pletor for Claude Code"
- "build me a pletor pipeline"

## Companion skill: `pletor-api`

This wizard generates skills that use **MCP `prepare_batch`** (draft + review URL in the Pletor UI). The companion **`pletor-api`** skill is the canonical reference for Pletor's **REST API** — `POST /assets/upload/`, `POST /runs/`, polling, asset download. Drop both into `~/.claude/skills/` so Claude has both paradigms in context:

- **`pletor-api`** — REST contract authority. Used by `upload.py` (asset upload) and any REST-direct extension you write. Get it at https://docs.pletor.ai/automate/api-integrations#agent-skills
- **`pletor-pipeline-setup`** (this skill) — orchestrates MCP `prepare_batch` with mandatory Yes/No review.

The two skills don't conflict — they cover different paradigms. The wizard checks for `pletor-api` in its prereq probe and gently recommends installing it if missing.

## License

MIT.
