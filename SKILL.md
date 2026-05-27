---
name: pletor-claude-code-setup
description: |
  Interactive wizard that scaffolds a new self-contained Pletor pipeline skill on
  the user's machine. Asks for the Pletor API key, the pipeline name, how many
  Pletor flows are in the chain (1 to N linear), each flow's ID + label, Google
  Drive integration, and project directory. Generates a complete, ready-to-use
  Claude Code skill at ~/.claude/skills/<pipeline-name>/ from templates. Trigger
  whenever the user says "set up a new Pletor pipeline", "create a pletor pipeline
  skill", "scaffold a pletor pipeline", "bootstrap pletor", "configure pletor for
  Claude Code", "build me a pletor pipeline", or any close variation. Optionally
  publishes the generated skill to GitHub as a final step.
tools: Bash, Read, Write, Edit, AskUserQuestion
---

# pletor-claude-code-setup — wizard for new Pletor pipeline skills

## Mission

Walk the user through scaffolding a new self-contained Claude Code skill that runs a Pletor pipeline (linear chain of 1 to N flows). Output: a complete folder at `~/.claude/skills/<pipeline-name>/` ready to use after a Claude Code restart.

The wizard NEVER fires any Pletor run, NEVER uploads anything, and NEVER spends credits. Its only side effects are:
- Writing files under `~/.claude/skills/<pipeline-name>/`
- Creating directories under `<project_dir>/Inputs/` and `<project_dir>/Outputs/`
- Writing/updating the env file (with the user's consent)
- Optionally creating a GitHub repo (last step, with explicit user consent)

## Constants

```
SKILL_DIR        = $(dirname "$0")   # this skill's own folder, contains templates/
TEMPLATES_DIR    = $SKILL_DIR/templates
SKILLS_ROOT      = $HOME/.claude/skills
```

## Workflow

### Phase 0 — Welcome + prerequisite check

Print a short welcome message:

```
🛠  pletor-claude-code-setup — generates a new Pletor pipeline skill on your machine.

I'll ask you a few questions and write a ready-to-use skill at ~/.claude/skills/<your-name>/.
No Pletor runs will be fired and no credits will be spent here.
```

Then probe each prerequisite and print ✓/✗:

| Check | Command | What it confirms |
|---|---|---|
| Claude Code | (always ✓ if you're reading this) | You're using it. |
| rclone installed | `command -v rclone` | rclone binary present |
| rclone remotes | `rclone listremotes` | At least one remote (Drive) configured |
| jq | `command -v jq` | JSON parser for rclone output |
| Python 3 | `command -v python3 && python3 -c "import requests" 2>/dev/null` | Python + requests library available |

If any prerequisite is missing, print the install command (e.g. `brew install rclone jq`, `pip install requests`) but **do not stop** — let the user continue if they want to fix it later.

### Phase 1 — Ask: API key handling

Use `AskUserQuestion`:

1. **Question 1 — env file location**:
   - "New file at ~/.pletor.env (recommended)"
   - "Existing file (I'll specify the path)"
   - "Skip — I'll set it up manually later"

2. **Question 2 — API key value** (only if env-file path was provided):
   - "Paste it now (I'll write it with `umask 077` so it's mode 600)"
   - "Skip — I'll add it manually"

If the user picks "Paste it now", AskUserQuestion with a free-text answer for the key (note: AskUserQuestion shows the answer in the conversation — warn the user that they can also pick "Skip" and add it manually after).

If they paste it:
```bash
(umask 077 && cat > "$ENV_FILE_PATH" <<EOF
PLETOR_API_KEY=<key>
EOF
)
```

Where to GET an API key (instruct the user in chat):
> Get your key at https://app.pletor.ai → account settings → API keys → generate. Keys start with `sk-…`.

Where to ADD the Pletor MCP server in Claude Code (instruct the user):
> The Pletor MCP server gives Claude the tools to run flows on your behalf. Add it via Claude Code's MCP settings — see https://claude.com/claude-code for the latest instructions on connecting MCP servers.

### Phase 2 — Ask: pipeline name

`AskUserQuestion` free-text: "What's the name of your new pipeline skill? (kebab-case, e.g. `my-furniture-pipeline`, `puig-frag-launch`, `yves-rocher-claim-strip`)"

**Sanitize the name** before using anywhere:

```python
import re
name = re.sub(r'[^a-z0-9-]+', '-', user_input.lower()).strip('-')[:60]
assert name, "name cannot be empty"
```

Set `SKILL_TARGET = $SKILLS_ROOT/<name>`.

If `$SKILL_TARGET` already exists, `AskUserQuestion`:
- "Overwrite (deletes the existing skill folder)"
- "Pick a new name"
- "Cancel the wizard"

### Phase 3 — Ask: number of flows

`AskUserQuestion`:
- "1 — single step (upload + run a single flow)"
- "2 — two-step chain (output of step 1 → input of step 2)"
- "3 or more — custom (I'll ask how many)"

If "3 or more", follow up with `AskUserQuestion` free-text: "How many flows? (2–10)". Parse as int, clamp to [2, 10].

Set `N_FLOWS` accordingly.

### Phase 4 — For each flow, ask details

Loop `k = 1..N_FLOWS`. Per iteration, one `AskUserQuestion` round with two questions:

1. **Question 1 — flow ID for step k**: free-text. Validate the format:
   ```python
   import re
   assert re.fullmatch(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}', value), \
       "expected a UUID like aaaaaaaa-1111-2222-3333-bbbbbbbbbbbb"
   ```
   If invalid, re-ask until valid.

2. **Question 2 — short label for step k**: free-text, default `step{k}`. Sanitize same as pipeline name. Examples to suggest: `static`, `video`, `upscale`, `inpaint`, `mask`.

After all flows captured, **summarize back** to the user as a markdown table and confirm with one final `AskUserQuestion`:

```
Here's your pipeline:

| step | label   | flow_id                              |
|------|---------|--------------------------------------|
| 1    | static  | aaaaaaaa-1111-2222-3333-bbbbbbbbbbbb |
| 2    | video   | cccccccc-4444-5555-6666-dddddddddddd |

Confirm? (Yes / Restart / Cancel)
```

On `Restart`, loop back to Phase 2. On `Cancel`, exit with no side effects.

### Phase 5 — Ask: Google Drive integration (optional, per-flow)

Drive integration depends on the SPECIFIC flow definitions: some Pletor flows have a text input that takes a Drive folder URL (so the flow writes its outputs to that Drive folder), others don't. The wizard asks once, globally, whether ANY flow in the pipeline uses this pattern.

`AskUserQuestion`:
- "Yes — at least one of my flows takes a Google Drive folder URL as a text input"
- "No — none of my flows use a Drive URL input (outputs stay on Pletor + downloaded locally only)"
- "Not sure — let me skip; I can edit `config.json` later"

If "Yes":

1. **Rclone remote name** — free-text, default `gdrive`. Validate via `rclone listremotes | grep -q "^${remote}:"`. If invalid, re-ask with the list of available remotes.
2. **Drive root folder ID** — free-text. Hint: "The long string in `https://drive.google.com/drive/folders/<this part>`". Validate format: `^[A-Za-z0-9_-]{20,}$` (Drive IDs are typically 33+ chars).

Optionally probe access:
```bash
rclone mkdir "${REMOTE}:wizard-test-$$" --drive-root-folder-id="${ROOT_ID}" 2>&1 \
  && rclone purge  "${REMOTE}:wizard-test-$$" --drive-root-folder-id="${ROOT_ID}" 2>&1
```
If this fails, warn the user but allow continuing.

If "No" or "Not sure": set `drive_root_id = ""`, `rclone_remote = ""` in the generated config. The generated skill will detect per-flow at discovery time whether a Drive URL input exists and adapt:
- If a flow has no Drive URL input → no Drive folder is created for that step, the input is omitted from the payload.
- If a flow HAS a Drive URL input but `drive_root_id` is empty → the generated skill STOPS with a clear error at run time, telling the user to set `drive_root_id` in `config.json`.

### Phase 6 — Ask: project directory

`AskUserQuestion` with the default offered first:
- "`${HOME}/<pipeline-name>-workspace` (recommended)"
- "Custom path — I'll type it"

If custom, free-text answer. Expand `${HOME}`. Refuse paths inside system directories (`/etc/`, `/usr/`, `/`, `/private/`, `/var/`).

### Phase 7 — Generate the skill files

Now write everything. Confirm with one final `AskUserQuestion` before writing:

```
About to write:
  Skill folder : $SKILL_TARGET/
    ├── SKILL.md
    ├── upload.py
    ├── config.json
    ├── config.example.json
    └── README.md

  Workspace    : $PROJECT_DIR/
    ├── Inputs/
    └── Outputs/

  Env file     : $ENV_FILE_PATH       (with umask 077, only if you pasted a key earlier)

Proceed?  (Yes / Cancel)
```

On Yes:

1. **Render `templates/SKILL.md.tmpl` → `$SKILL_TARGET/SKILL.md`** with substitutions:
   - `{{PIPELINE_NAME}}` → sanitized name
   - `{{PIPELINE_DESCRIPTION}}` → auto-generated one-liner, e.g. "Run a {{N_FLOWS}}-step Pletor pipeline ({{STEP_LABELS_JOINED}}) with mandatory Yes/No validation before each fire."
   - `{{TRIGGER_PHRASES}}` → comma-separated list, e.g. `"run <name>", "kick off <name>", "launch the <name> pipeline"`
   - `{{N_FLOWS}}` → integer
   - `{{GENERATED_AT}}` → ISO-8601 UTC timestamp
   - `{{PIPELINE_STEPS_BULLET_LIST}}` → bullet list like:
     ```
     1. **static** — Pletor flow `aaaaaaaa-1111-…` (takes asset, returns image)
     2. **video** — Pletor flow `cccccccc-4444-…` (takes step 1's output, returns video)
     ```

2. **Copy `templates/upload.py` → `$SKILL_TARGET/upload.py`** verbatim (no substitutions). `chmod +x` it.

3. **Render `templates/config.example.json.tmpl` → `$SKILL_TARGET/config.example.json`** with placeholder values (e.g. `"REPLACE_WITH_…"` for IDs, but actual values for poll/budget defaults).

4. **Render `config.example.json.tmpl` → `$SKILL_TARGET/config.json`** with the user's REAL values:
   - `flows`: array of `{id, label, poll_timeout_seconds, budget_warn}` per step
     - For step 0 (typically the upload step), `poll_timeout_seconds: 600`, `budget_warn: 10`
     - For step k > 0, `poll_timeout_seconds: 1200`, `budget_warn: 5` (videos/heavy steps are slower and fan-in is small)
     - User can edit these later
   - `drive_root_id`, `rclone_remote`, `project_dir`, `env_file` from the answers
   - `poll_tick_seconds: 5`, `input_extensions: [".png", ".jpg", ".jpeg", ".webp"]`

5. **Render `templates/README.md.tmpl` → `$SKILL_TARGET/README.md`** with the same substitutions as SKILL.md.

6. **Write a `.gitignore`** at `$SKILL_TARGET/.gitignore`:
   ```
   config.json
   flows.json
   asset_map.json
   *.env
   __pycache__/
   .DS_Store
   ```

7. **`mkdir -p`** the workspace: `$PROJECT_DIR/Inputs/`, `$PROJECT_DIR/Outputs/`.

### Phase 8 — Verify

After writing, do quick sanity checks and print results:

```bash
python3 -c "import ast; ast.parse(open('$SKILL_TARGET/upload.py').read())" && echo "✓ upload.py syntax ok"
python3 -c "import json; json.load(open('$SKILL_TARGET/config.json'))" && echo "✓ config.json valid"
head -1 "$SKILL_TARGET/SKILL.md" | grep -q '^---' && echo "✓ SKILL.md has frontmatter"
```

If any check fails, report it but don't auto-rollback — let the user inspect.

### Phase 9 — Done + optional GitHub publish

Print a success summary:

```
✓ Generated skill: $SKILL_TARGET/
  Trigger phrases: <list from frontmatter>

Next steps:
  1. Drop input assets into $PROJECT_DIR/Inputs/
  2. Restart Claude Code so it picks up the new skill
  3. Type one of the trigger phrases to run the pipeline
```

Then `AskUserQuestion`:

- "Publish this skill to GitHub now (public repo)?"
- "No — I'll handle Git later"

If "Publish":

1. Check `gh auth status`. If not logged in: print `gh auth login` instructions and skip.
2. `AskUserQuestion`: repo visibility — `Public` (default) / `Private`.
3. Run:
   ```bash
   cd "$SKILL_TARGET"
   git init -q
   git add .
   git -c user.email="$(git config user.email || echo nobody@example.com)" \
       -c user.name="$(git config user.name || echo Anonymous)" \
       commit -q -m "Initial commit: $(basename $SKILL_TARGET)

   Generated by pletor-claude-code-setup."
   gh repo create "$(basename $SKILL_TARGET)" --$VISIBILITY --source=. --remote=origin --push \
     --description "Pletor pipeline skill generated by pletor-claude-code-setup"
   ```
4. Print the resulting repo URL.

**WARNING to the user before pushing**: confirm that `config.json` is in `.gitignore` and won't be pushed (the wizard always writes it there, but double-check `git status` shows only the safe files).

## Hard rules

1. **No Pletor MCP calls** in this skill — only file operations + AskUserQuestion + rclone preflight.
2. **No deletions** of existing files unless the user explicitly says "Overwrite" in Phase 2.
3. **API key handling** — only write the env file with `umask 077`. Never echo the key back. Never log it.
4. **GitHub push** — gated by explicit user consent in Phase 9. Never proactive. Always verify `.gitignore` covers `config.json` and `*.env`.
5. **All paths sanitized** — pipeline name + step labels go through the slug regex before being used in filesystem paths.
6. **Idempotent re-runs** — if the user re-runs the wizard with the same name and chooses "Overwrite", regenerate cleanly. If they pick a new name, leave existing skills untouched.

## Failure modes

| Failure | Reaction |
|---|---|
| rclone remote check fails | Warn, allow user to continue (they can configure rclone later) |
| Flow ID format invalid | Re-ask in Phase 4 |
| Skill target exists | Phase 2 branch: Overwrite / Rename / Cancel |
| Env file write fails (permissions) | Report path + error, continue without writing env |
| Templates missing in `$SKILL_DIR/templates/` | STOP — bootstrap is misinstalled |
| `gh auth status` fails | Skip publish, instruct user to run `gh auth login` |
| User says Cancel at any prompt | Exit cleanly. No partial files written. |
