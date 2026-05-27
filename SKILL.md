---
name: pletor-pipeline-setup
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
tools: Bash, Read, Write, Edit, AskUserQuestion, mcp__claude_ai_Pletor__execute
---

# pletor-pipeline-setup — wizard for new Pletor pipeline skills

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
🛠  pletor-pipeline-setup — generates a new Pletor pipeline skill on your machine.

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
| `pletor-api` skill | `test -f ~/.claude/skills/pletor-api/SKILL.md` | Companion REST-API reference (recommended) — get it at https://docs.pletor.ai/automate/api-integrations#agent-skills |

If any prerequisite is missing, print the install command (e.g. `brew install rclone jq`, `pip install requests`) but **do not stop** — let the user continue if they want to fix it later.

### Phase 1 — Ask: API key handling

**Before asking** : probe candidate existing env files with `find ~ -maxdepth 4 -name "*.env" -type f 2>/dev/null | xargs grep -l "^PLETOR_API_KEY=" 2>/dev/null | head -5`. If hits exist, surface them as concrete options (instead of the abstract "Existing file" choice).

Use `AskUserQuestion`:

1. **Question 1 — env file location**:
   - For each detected env containing `PLETOR_API_KEY=`, one option per path (e.g. "`/Users/j/Brain/00_Clients/.env` (detected)")
   - "New file at ~/.pletor.env (will be created)"
   - "Existing file at a path I'll type" (free-text follow-up)
   - "Skip — I'll set it up manually later"

2. **Question 2 — API key value** (only if env-file path was provided AND the file does NOT already contain `PLETOR_API_KEY=`):
   - "Paste it now (I'll write it with `umask 077` so it's mode 600)"
   - "Skip — I'll add it manually"

**Validation after user picks a path** (CRITICAL — catches the #1 wizard bug : pointing to a non-existent env file) :

```bash
ENV_FILE_PATH="<user answer>"
ENV_FILE_PATH="${ENV_FILE_PATH/#~/$HOME}"   # expand ~ to absolute
if [ "$EXISTING_PATH_CHOICE" = "true" ]; then
  test -f "$ENV_FILE_PATH" || { echo "⚠️  env file not found at $ENV_FILE_PATH"; AskUserQuestion to re-pick or continue without; }
  grep -q "^PLETOR_API_KEY=" "$ENV_FILE_PATH" \
    || echo "⚠️  $ENV_FILE_PATH exists but has no PLETOR_API_KEY= line — generated skill will fail Phase 0 preflight until you add it"
fi
```

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

### Phase 4 — For each flow, ask details + discover input shape

Loop `k = 1..N_FLOWS`. Per iteration :

**Step 4a — Capture flow_id + label** (one `AskUserQuestion` round) :

1. **Question 1 — flow ID for step k**: free-text. Validate the format:
   ```python
   import re
   assert re.fullmatch(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}', value), \
       "expected a UUID like aaaaaaaa-1111-2222-3333-bbbbbbbbbbbb"
   ```
   If invalid, re-ask until valid.

2. **Question 2 — short label for step k**: free-text, default `step{k}`. Sanitize same as pipeline name. Examples to suggest: `static`, `video`, `upscale`, `inpaint`, `mask`, `clone-ads`, `localizer`.

**Step 4b — Discover flow shape via MCP** (CRITICAL : prevents the "Phase 0 fails because the SKILL.md hardcoded 1 image_input" bug — many Pletor flows have multiple unlocked inputs and the scaffold must capture them all at setup time, not at runtime) :

Call `mcp__claude_ai_Pletor__execute` with `operation: get_workflow_definition`, `params: {id: <flow_id>}`. Parse the returned `dsl` text to extract every node :
- For each line `**<node_name>** (<node_type>) [id=<uuid>]: <label>`, capture `{uuid, name, node_type, label}`.
- Categorise nodes by type :
  - `image_input` → asset role candidates (winning_ad, packshot, reference, logo, etc.)
  - `text_input` → text role candidates (drive_url, products_names, prompt, target_languages, etc.)
  - `brand_system_input` → typically locked (brand_context)
  - Other node types (image_generation, llm, rename_asset, googledrive_upload_file) → ignore

- Identify locked inputs : the wizard's heuristic is "any input named `logo`, `brand_colors`, `brand_context`, or `visual_references` is locked by default; the user can override". Locked inputs are stored separately and **never** included in batch payloads.

**Step 4c — Assign a role per unlocked input** (one `AskUserQuestion` per input, with options) :

For each unlocked input from step 4b, ask the user to map it to a known role. Predefined role enum (with hints):

| Role | Type | Description |
|---|---|---|
| `winning_ad_template` | image_input | The reference ad to clone (used by clone-ads workflows) |
| `packshot` | image_input | The product asset to insert (Zelesta clone-ads, fashion static) |
| `reference_image` | image_input | A reference image (style, mood) |
| `source_video` / `source_image` | image_input | A previous step's output (chained pipelines) |
| `drive_url` | text_input | Drive folder URL where the workflow exports its output |
| `products_names` | text_input | Product names/labels passed as context to the LLM |
| `target_languages` | text_input | Languages to translate to (localizer workflows) |
| `prompt` | text_input | Free-text prompt or instruction |
| `asset_name` | text_input | Filename hint for the output |
| `brand_context` | brand_system_input | Brand profile (almost always LOCKED) |
| `logo` / `brand_colors` | image_input | Brand assets (almost always LOCKED) |
| `LOCKED` | any | "Don't include this input in payloads — it's pre-set on the agent" |
| `other` | any | Free-text label (escape hatch for unusual flows) |

`AskUserQuestion` per input. Pre-select `LOCKED` for inputs whose name matches the locked heuristic. The user confirms or overrides.

**Step 4d — Build the per-flow shape dict** :

```python
flow_shape = {
    "flow_id": "<uuid>",
    "label": "<sanitized>",
    "name": "<workflow name from dsl>",
    "inputs": {
        # role → {id, node_type}
        "winning_ad_template": {"id": "...", "node_type": "image_input"},
        "packshot":            {"id": "...", "node_type": "image_input"},
        "products_names":      {"id": "...", "node_type": "text_input"},
        "drive_url":           {"id": "...", "node_type": "text_input"},
    },
    "locked_inputs": [
        {"id": "...", "label": "Logo",          "node_type": "image_input"},
        {"id": "...", "label": "Brand Colors",  "node_type": "image_input"},
        {"id": "...", "label": "Brand context", "node_type": "brand_system_input"},
    ],
    "discovered_at": "<ISO-8601 UTC>",
}
```

Store in a dict keyed by label, written to `flows.json` in Phase 7.

**After all flows captured**, summarise back to the user as a markdown table (one row per flow with all detected roles) and confirm with one final `AskUserQuestion` :

```
Here's your pipeline:

| step | label    | flow_id      | roles                                              | locked              |
|------|----------|--------------|----------------------------------------------------|---------------------|
| 1    | static   | aaaaaaaa-... | packshot, drive_url                                | visual_examples     |
| 2    | localize | cccccccc-... | source_image, target_languages, drive_url, prompt  | brand_context, logo |

Confirm? (Yes / Restart / Cancel)
```

On `Restart`, loop back to Phase 2. On `Cancel`, exit with no side effects.

**Failure modes during step 4b** :
- If MCP `get_workflow_definition` errors (invalid flow_id, no MCP access) → AskUserQuestion : "Skip discovery and proceed with stub flows.json ?" (user fills it later) / "Re-enter flow_id" / "Cancel".
- If the parsed dsl has zero `image_input` → warn (most pipelines have at least one input asset).

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

   **Substitution placeholders in `config.example.json.tmpl`** :
   - `{{PIPELINE_NAME}}` → sanitized name
   - `{{FLOWS_ARRAY}}` → **the COMPLETE JSON array** including outer `[` and `]`, with each flow as a complete object `{...}`. Build via `json.dumps(flows_list, indent=2)` and inject as one substitution. **Never strip the outer `[]` or per-object `{}`** — the template uses `"flows": {{FLOWS_ARRAY}},` (no surrounding brackets in the template, the array is the whole value). Common bug : substituting bare key:value pairs without `{}` produces invalid JSON.
   - `{{DRIVE_ROOT_ID}}`, `{{RCLONE_REMOTE}}`, `{{PROJECT_DIR}}`, `{{ENV_FILE}}` → string values (the wizard handles quoting in the template via `"…"`)

   After rendering, **validate the output** : `python3 -c "import json; json.load(open(path))"` on both config.json and config.example.json. If either fails, STOP — the substitution is bugged.

5. **Render `templates/README.md.tmpl` → `$SKILL_TARGET/README.md`** with the same substitutions as SKILL.md.

5b. **Write `flows.json`** at `$SKILL_TARGET/flows.json` with the rich shape captured in Phase 4 (one entry per flow, keyed by label). Schema :

   ```json
   {
     "<label>": {
       "flow_id": "<uuid>",
       "name": "<workflow name from MCP discovery>",
       "inputs": {
         "<role>": {"id": "<uuid>", "node_type": "image_input | text_input | brand_system_input"}
       },
       "locked_inputs": [
         {"id": "<uuid>", "label": "<name>", "node_type": "<type>"}
       ],
       "discovered_at": "<ISO-8601 UTC>"
     }
   }
   ```

   The generated `SKILL.md` reads this file in its own Phase 1 instead of doing brittle runtime discovery. If a future flow update adds/changes inputs, the user re-runs the wizard with `--refresh-flow <label>` (TODO) OR the generated skill exposes a `--refresh-flows` flag that calls MCP again to update flows.json in place.

   Validate the written JSON : `python3 -c "import json; json.load(open(path))"`. If invalid, STOP.

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

   Generated by pletor-pipeline-setup."
   gh repo create "$(basename $SKILL_TARGET)" --$VISIBILITY --source=. --remote=origin --push \
     --description "Pletor pipeline skill generated by pletor-pipeline-setup"
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

## Related skill

**`pletor-api`** — the canonical reference for Pletor's REST API (auth via `X-Api-Key`, `POST /assets/upload/`, `POST /runs/`, polling, asset download). Install it alongside this wizard so Claude has the authoritative wire contract when writing or debugging code that touches the REST API (notably `upload.py`, or any future REST-direct alternative to `prepare_batch`):

- Official source: https://docs.pletor.ai/automate/api-integrations#agent-skills
- Drop the file at `~/.claude/skills/pletor-api/SKILL.md` and restart Claude Code.

If the user already has it installed, do nothing. If not, mention it at Phase 0 when prereqs are checked.
