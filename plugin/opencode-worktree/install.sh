#!/usr/bin/env bash
set -euo pipefail

SCRIPT_SOURCE="${BASH_SOURCE[0]}"
if command -v readlink >/dev/null 2>&1; then
  if readlink -f -- "$SCRIPT_SOURCE" >/dev/null 2>&1; then
    SCRIPT_SOURCE="$(readlink -f -- "$SCRIPT_SOURCE")"
  else
    # Portable symlink resolution for systems without `readlink -f` (macOS).
    while [ -L "$SCRIPT_SOURCE" ]; do
      link_target="$(readlink "$SCRIPT_SOURCE")" || break
      case "$link_target" in
        /*) SCRIPT_SOURCE="$link_target" ;;
        *) SCRIPT_SOURCE="$(cd -P "$(dirname "$SCRIPT_SOURCE")" && pwd -P)/$link_target" ;;
      esac
    done
  fi
fi
SCRIPT_DIR="$(cd "$(dirname "$SCRIPT_SOURCE")" && pwd -P)"
SRC_DIR="$SCRIPT_DIR/src/plugin"
MANIFEST="$SCRIPT_DIR/package.json"
HARNESS_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd -P)"

SANDBOX_SRC="$HARNESS_ROOT/sandbox"
SANDBOX_FILES=(
  AGENTS.md
  README.md
  main.py
  display.py
  sensor.py
  thermostat.py
  test_display.py
  test_main.py
  test_thermostat.py
)
AGENT_FILES=(orchestrator lead planner coder reviewer researcher)
COMMAND_FILES=(issues feature ship status)
ISSUE_STATES=(todo inprogress review completed)
ISSUE_QUEUE_SRC="$HARNESS_ROOT/.opencode/scripts/issue_queue.py"
ISSUES_SRC="$SCRIPT_DIR/templates/issues"

warn() { printf 'warning: %s\n' "$*" >&2; }
err() { printf 'error: %s\n' "$*" >&2; }
note() { printf 'note: %s\n' "$*" >&2; }

usage() {
  printf 'Usage: %s [OPTIONS] [TARGET_PROJECT_DIR]\n' "$(basename "$0")"
  printf '\n'
  printf 'Install the opencode engineering harness and/or the opencode-worktree\n'
  printf 'plugin into TARGET_PROJECT_DIR. TARGET_PROJECT_DIR defaults to the\n'
  printf 'current working directory. A full harness install writes only the\n'
  printf 'runtime files under .opencode/ plus the local issues/ queue scaffolding\n'
  printf 'and a root-anchored /issues/ .gitignore entry; it leaves the target\n'
  printf 'workspace notes, docs, root scripts, and root config untouched.\n'
  printf '\n'
  printf 'Modes:\n'
  printf '  (default)        Full harness when run from a harness checkout, else plugin only\n'
  printf '  --plugin-only    Install only the worktree plugin\n'
  printf '\n'
  printf 'Options:\n'
  printf '  --with-sandbox   Also install the sandbox demo project (implies full harness)\n'
  printf '  --force          Back up and replace existing .opencode/worktree.jsonc,\n'
  printf '                   issue scaffolding, or sandbox/ (not AGENTS.md)\n'
  printf '  -h, --help       Show this help\n'
  printf '  --               End of options\n'
}

PLUGIN_ONLY=0
WITH_SANDBOX=0
FORCE=0
TARGET=""

while [ "$#" -gt 0 ]; do
  case "$1" in
    -h | --help)
      usage
      exit 0
      ;;
    --plugin-only)
      PLUGIN_ONLY=1
      shift
      ;;
    --with-sandbox)
      WITH_SANDBOX=1
      shift
      ;;
    --force)
      FORCE=1
      shift
      ;;
    --)
      shift
      break
      ;;
    -*)
      err "unknown option: $1"
      usage >&2
      exit 2
      ;;
    *)
      if [ -n "$TARGET" ]; then
        err "unexpected extra argument: $1"
        usage >&2
        exit 2
      fi
      TARGET="$1"
      shift
      ;;
  esac
done

while [ "$#" -gt 0 ]; do
  if [ -n "$TARGET" ]; then
    err "unexpected extra argument: $1"
    usage >&2
    exit 2
  fi
  TARGET="$1"
  shift
done

if [ "$PLUGIN_ONLY" -eq 1 ] && [ "$WITH_SANDBOX" -eq 1 ]; then
  err "--plugin-only and --with-sandbox cannot be used together"
  usage >&2
  exit 2
fi

TARGET="${TARGET:-$PWD}"

if [ ! -d "$TARGET" ]; then
  err "target directory does not exist or is not a directory: $TARGET"
  exit 1
fi

TARGET_ABS="$(cd "$TARGET" && pwd -P)"
TARGET_OC="$TARGET_ABS/.opencode"

if [ -e "$TARGET_OC" ] && [ ! -d "$TARGET_OC" ]; then
  err "target .opencode exists but is not a directory: $TARGET_OC"
  exit 1
fi

if [ -e "$TARGET_OC/package.json" ] && [ ! -f "$TARGET_OC/package.json" ]; then
  err "target .opencode/package.json exists but is not a regular file: $TARGET_OC/package.json"
  exit 1
fi

HARNESS_DETECTED=0
if [ -f "$HARNESS_ROOT/.opencode/opencode.json" ] &&
  [ -f "$HARNESS_ROOT/.opencode/constitution.md" ] &&
  [ -f "$HARNESS_ROOT/.opencode/agents/lead.md" ]; then
  HARNESS_DETECTED=1
fi

if [ "$PLUGIN_ONLY" -eq 1 ]; then
  MODE="plugin"
elif [ "$WITH_SANDBOX" -eq 1 ]; then
  if [ "$HARNESS_DETECTED" -ne 1 ]; then
    err "--with-sandbox requires a harness checkout (expected .opencode/opencode.json, .opencode/constitution.md and .opencode/agents/lead.md under $HARNESS_ROOT)"
    exit 1
  fi
  MODE="full"
elif [ "$HARNESS_DETECTED" -eq 1 ]; then
  MODE="full"
else
  MODE="plugin"
  if [ "$WITH_SANDBOX" -eq 0 ]; then
    note "harness checkout not detected at $HARNESS_ROOT; falling back to plugin-only mode"
  fi
fi

if [ "$MODE" = "full" ] && [ "$TARGET_ABS" = "$HARNESS_ROOT" ]; then
  err "refusing to install the full harness into its own checkout: $TARGET_ABS"
  err "run the installer against another project, or use --plugin-only"
  exit 1
fi

if [ "$MODE" = "full" ] && [ -e "$TARGET_OC/opencode.jsonc" ]; then
  err "target has .opencode/opencode.jsonc: $TARGET_OC/opencode.jsonc"
  err "cannot safely merge JSONC with the harness .opencode/opencode.json"
  err "merge the config manually, or re-run with --plugin-only"
  exit 1
fi

if [ "$MODE" = "full" ]; then
  if [ -e "$TARGET_ABS/opencode.json" ]; then
    warn "target has a root opencode.json: $TARGET_ABS/opencode.json"
    warn "opencode loads .opencode/opencode.json after the root config, so the harness config wins on conflicting keys; the root file is left untouched"
  fi
  if [ -e "$TARGET_ABS/opencode.jsonc" ]; then
    warn "target has a root opencode.jsonc: $TARGET_ABS/opencode.jsonc"
    warn "opencode loads .opencode/opencode.json after the root config, so the harness config wins on conflicting keys; the root file is left untouched"
  fi

  # Legacy installs are warned about, never deleted or rewritten.
  if [ -e "$TARGET_ABS/scripts/issue_queue.py" ]; then
    warn "target still has the legacy root scripts/issue_queue.py: $TARGET_ABS/scripts/issue_queue.py"
    warn "use .opencode/scripts/issue_queue.py instead; the legacy file was left untouched"
  fi
  if [ -e "$TARGET_ABS/docs/validation.md" ]; then
    warn "target still has the legacy harness docs/validation.md: $TARGET_ABS/docs/validation.md"
    warn "the harness no longer installs docs; the legacy file was left untouched"
  fi
  if [ -f "$TARGET_ABS/AGENTS.md" ] &&
    grep -qF -- '> Project-specific facts and conventions for agents working in this repository.' "$TARGET_ABS/AGENTS.md"; then
    warn "target AGENTS.md looks harness-installed (it still has the old template marker): $TARGET_ABS/AGENTS.md"
    warn "the harness no longer installs or manages AGENTS.md; the file was left untouched"
  fi
fi

# Validate every destination type before any target write so a bad path cannot
# fail halfway through the install.
require_dir_or_absent() {
  local path="$1"
  local label="$2"
  if [ -e "$path" ] && [ ! -d "$path" ]; then
    err "$label exists but is not a directory: $path"
    exit 1
  fi
}

require_file_or_absent() {
  local path="$1"
  local label="$2"
  if [ -e "$path" ] && [ ! -f "$path" ]; then
    err "$label exists but is not a regular file: $path"
    exit 1
  fi
}

require_dir_or_absent "$TARGET_OC/plugin" ".opencode/plugin"
require_file_or_absent "$TARGET_OC/package.json" ".opencode/package.json"
require_file_or_absent "$TARGET_OC/.gitignore" ".opencode/.gitignore"
require_dir_or_absent "$TARGET_OC/.install-backups" ".opencode/.install-backups"

if [ "$MODE" = "full" ]; then
  require_dir_or_absent "$TARGET_ABS/issues" "issues"
  require_dir_or_absent "$TARGET_OC/agents" ".opencode/agents"
  require_dir_or_absent "$TARGET_OC/commands" ".opencode/commands"
  require_dir_or_absent "$TARGET_OC/scripts" ".opencode/scripts"
  require_file_or_absent "$TARGET_ABS/.gitignore" ".gitignore"
  require_file_or_absent "$TARGET_OC/opencode.json" ".opencode/opencode.json"
  require_file_or_absent "$TARGET_OC/worktree.jsonc" ".opencode/worktree.jsonc"
  require_file_or_absent "$TARGET_OC/constitution.md" ".opencode/constitution.md"
  require_file_or_absent "$TARGET_OC/scripts/issue_queue.py" ".opencode/scripts/issue_queue.py"
  require_file_or_absent "$TARGET_ABS/issues/README.md" "issues/README.md"
  require_file_or_absent "$TARGET_ABS/issues/.gitignore" "issues/.gitignore"
  for state in "${ISSUE_STATES[@]}"; do
    require_dir_or_absent "$TARGET_ABS/issues/$state" "issues/$state"
    require_file_or_absent "$TARGET_ABS/issues/$state/.gitkeep" "issues/$state/.gitkeep"
  done
  for agent in "${AGENT_FILES[@]}"; do
    require_file_or_absent "$TARGET_OC/agents/$agent.md" ".opencode/agents/$agent.md"
  done
  for command in "${COMMAND_FILES[@]}"; do
    require_file_or_absent "$TARGET_OC/commands/$command.md" ".opencode/commands/$command.md"
  done
fi

if [ "$MODE" = "full" ] && [ "$WITH_SANDBOX" -eq 1 ]; then
  require_dir_or_absent "$TARGET_ABS/sandbox" "sandbox"
fi

if [ -d "$SRC_DIR" ]; then
  while IFS= read -r -d '' source; do
    rel="${source#"$SRC_DIR"/}"
    require_file_or_absent "$TARGET_OC/plugin/$rel" ".opencode/plugin/$rel"
  done < <(find "$SRC_DIR" -type f -print0)
fi

MISSING=()
add_missing_file() {
  if [ ! -f "$1" ]; then
    MISSING+=("$1")
  fi
}

add_missing_file "$SRC_DIR/worktree.ts"
add_missing_file "$MANIFEST"

if [ "$MODE" = "full" ]; then
  add_missing_file "$HARNESS_ROOT/.opencode/opencode.json"
  add_missing_file "$HARNESS_ROOT/.opencode/constitution.md"
  add_missing_file "$HARNESS_ROOT/.opencode/worktree.jsonc"
  add_missing_file "$ISSUE_QUEUE_SRC"
  add_missing_file "$ISSUES_SRC/README.md"
  add_missing_file "$ISSUES_SRC/.gitignore"
  for state in "${ISSUE_STATES[@]}"; do
    add_missing_file "$ISSUES_SRC/$state/.gitkeep"
  done
  for agent in "${AGENT_FILES[@]}"; do
    add_missing_file "$HARNESS_ROOT/.opencode/agents/$agent.md"
  done
  for command in "${COMMAND_FILES[@]}"; do
    add_missing_file "$HARNESS_ROOT/.opencode/commands/$command.md"
  done
  if [ "$WITH_SANDBOX" -eq 1 ]; then
    if [ ! -d "$SANDBOX_SRC" ]; then
      MISSING+=("$SANDBOX_SRC")
    fi
    for file in "${SANDBOX_FILES[@]}"; do
      add_missing_file "$SANDBOX_SRC/$file"
    done
  fi
fi

if [ "${#MISSING[@]}" -gt 0 ]; then
  err "required file(s) not found:"
  printf '  %s\n' "${MISSING[@]}" >&2
  exit 1
fi

MERGE_RUNNER=""
if command -v node >/dev/null 2>&1; then
  MERGE_RUNNER="node"
elif command -v bun >/dev/null 2>&1; then
  MERGE_RUNNER="bun"
else
  err "neither node nor bun is on PATH; one is required to merge JSON config"
  exit 1
fi

INSTALLER=""
if command -v bun >/dev/null 2>&1; then
  INSTALLER="bun"
elif command -v npm >/dev/null 2>&1; then
  INSTALLER="npm"
else
  err "neither bun nor npm is on PATH; cannot install plugin dependencies in $TARGET_OC"
  exit 1
fi

if ! git -C "$TARGET_ABS" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  warn "target is not a git work tree; worktree tools require git"
fi

TMP_DIR="$(mktemp -d)"
cleanup() {
  rm -rf -- "$TMP_DIR"
}
trap cleanup EXIT

BACKUP_TS="$(date +%Y%m%d%H%M%S)"
BACKUP_ROOT="$TARGET_OC/.install-backups/$BACKUP_TS-$$"

ensure_backup_root() {
  mkdir -p -- "$BACKUP_ROOT"
  chmod 0700 -- "$(dirname -- "$BACKUP_ROOT")" "$BACKUP_ROOT"
}

backup_file() {
  local abs="$1"
  local rel="$2"
  local dest="$BACKUP_ROOT/$rel"
  ensure_backup_root
  mkdir -p "$(dirname "$dest")"
  cp -p -- "$abs" "$dest"
  note "backed up $rel -> $dest"
}

backup_dir() {
  local abs="$1"
  local rel="$2"
  local dest="$BACKUP_ROOT/$rel"
  ensure_backup_root
  mkdir -p "$(dirname "$dest")"
  cp -a -- "$abs" "$dest"
  note "backed up $rel -> $dest"
}

# Install a harness-owned file. Identical files are left untouched; differing
# files are backed up before being replaced.
install_managed_file() {
  local src="$1"
  local rel="$2"
  local dest="$TARGET_ABS/$rel"

  if [ -e "$dest" ]; then
    if [ ! -f "$dest" ]; then
      err "cannot install $rel: destination exists and is not a regular file: $dest"
      exit 1
    fi
    if cmp -s "$src" "$dest"; then
      return 0
    fi
    backup_file "$dest" "$rel"
  fi

  mkdir -p "$(dirname "$dest")"
  cp -- "$src" "$dest"
}

# Install a template file only when absent, unless --force is given. Never
# clobbers an existing project-specific file without a backup.
INSTALL_IF_ABSENT_STATUS=""
install_if_absent() {
  local src="$1"
  local rel="$2"
  local dest="$TARGET_ABS/$rel"

  if [ -e "$dest" ]; then
    if [ ! -f "$dest" ]; then
      err "cannot install $rel: destination exists and is not a regular file: $dest"
      exit 1
    fi
    if cmp -s "$src" "$dest"; then
      INSTALL_IF_ABSENT_STATUS="kept existing (unchanged)"
      return 0
    fi
    if [ "$FORCE" -eq 1 ]; then
      backup_file "$dest" "$rel"
      cp -- "$src" "$dest"
      INSTALL_IF_ABSENT_STATUS="replaced (backup)"
      return 0
    fi
    INSTALL_IF_ABSENT_STATUS="kept existing (use --force to replace)"
    warn "keeping existing $rel; use --force to back it up and replace it"
    return 0
  fi

  mkdir -p "$(dirname "$dest")"
  cp -- "$src" "$dest"
  INSTALL_IF_ABSENT_STATUS="installed"
}

# Issue scaffolding is project-owned: install only when absent (or with
# --force), never clobber an existing queue or its docs.
ISSUES_STATUS="not installed"
ISSUES_INSTALLED=0
ISSUES_KEPT=0
install_issue_file() {
  install_if_absent "$1" "$2"
  case "$INSTALL_IF_ABSENT_STATUS" in
    installed | replaced*)
      ISSUES_INSTALLED=$((ISSUES_INSTALLED + 1))
      ;;
    *)
      ISSUES_KEPT=$((ISSUES_KEPT + 1))
      ;;
  esac
}

ensure_opencode_gitignore() {
  local file="$TARGET_OC/.gitignore"
  local lines=(node_modules package.json package-lock.json bun.lock .install-backups)
  local missing=()
  local line

  mkdir -p "$TARGET_OC"

  if [ ! -e "$file" ]; then
    printf '%s\n' "${lines[@]}" >"$file"
    return 0
  fi
  if [ ! -f "$file" ]; then
    err "cannot update .opencode/.gitignore: not a regular file: $file"
    exit 1
  fi

  for line in "${lines[@]}"; do
    if ! grep -qxF -- "$line" "$file"; then
      missing+=("$line")
    fi
  done

  if [ "${#missing[@]}" -eq 0 ]; then
    return 0
  fi

  backup_file "$file" ".opencode/.gitignore"

  for line in "${missing[@]}"; do
    if [ -s "$file" ] && [ "$(tail -c 1 "$file" | wc -l)" -eq 0 ]; then
      printf '\n' >>"$file"
    fi
    printf '%s\n' "$line" >>"$file"
  done

  note "updated .opencode/.gitignore (+${#missing[@]} line(s))"
}

# The issue queue is local state: keep it out of git so queue moves create no
# commits. Only the exact root-anchored `/issues/` counts: a bare `issues/`
# would also ignore templates/issues/. Create the root .gitignore when absent,
# otherwise append `/issues/` unless that anchored line is already present.
# Never clobber.
ensure_root_gitignore() {
  local file="$TARGET_ABS/.gitignore"
  local line="/issues/"

  if [ -e "$file" ] && [ ! -f "$file" ]; then
    err "cannot update .gitignore: not a regular file: $file"
    exit 1
  fi

  if [ ! -e "$file" ]; then
    printf '%s\n' "$line" >"$file"
    note "created .gitignore with $line (local issue queue stays untracked)"
    return 0
  fi

  if grep -qxF -- "$line" "$file"; then
    return 0
  fi

  backup_file "$file" ".gitignore"

  if [ -s "$file" ] && [ "$(tail -c 1 "$file" | wc -l)" -eq 0 ]; then
    printf '\n' >>"$file"
  fi
  printf '%s\n' "$line" >>"$file"
  note "updated .gitignore (+$line) so the local issue queue stays untracked"
}

# Validate target JSON before anything is installed. Invalid files are backed
# up (preserving their mode) and the installer stops before other target writes.
PREFLIGHT_SCRIPT="$TMP_DIR/preflight.cjs"
cat >"$PREFLIGHT_SCRIPT" <<'NODE'
"use strict";

const fs = require("fs");
const path = require("path");

const configPath = process.argv[2];
const packagePath = process.argv[3];
const backupRoot = process.argv[4];

function isPlainObject(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function fail(message) {
  process.stderr.write("error: " + message + "\n");
  process.exit(1);
}

function backup(sourcePath, raw, rel) {
  const dest = path.join(backupRoot, rel);
  fs.mkdirSync(path.dirname(dest), { recursive: true, mode: 0o700 });
  try {
    fs.chmodSync(backupRoot, 0o700);
    fs.chmodSync(path.dirname(backupRoot), 0o700);
  } catch (_) {
    // Best effort: the backup itself is still usable.
  }
  fs.writeFileSync(dest, raw);
  try {
    fs.chmodSync(dest, fs.statSync(sourcePath).mode & 0o777);
  } catch (_) {
    // Best effort: keep the backup writable by the owner.
  }
  return dest;
}

function check(filePath, rel, allowEmpty) {
  if (filePath === "" || !fs.existsSync(filePath)) {
    return;
  }
  const raw = fs.readFileSync(filePath);
  const text = raw.toString("utf8").trim();
  if (text === "" && allowEmpty) {
    return;
  }
  let parsed;
  try {
    parsed = JSON.parse(text);
  } catch (error) {
    const dest = backup(filePath, raw, rel);
    fail("invalid JSON in " + filePath + " (backup: " + dest + ")");
  }
  if (!isPlainObject(parsed)) {
    const dest = backup(filePath, raw, rel);
    fail("invalid JSON in " + filePath + " (expected an object; backup: " + dest + ")");
  }
}

check(configPath, ".opencode/opencode.json", false);
check(packagePath, ".opencode/package.json", true);
NODE

PREFLIGHT_CONFIG=""
if [ "$MODE" = "full" ]; then
  PREFLIGHT_CONFIG="$TARGET_OC/opencode.json"
fi
"$MERGE_RUNNER" "$PREFLIGHT_SCRIPT" \
  "$PREFLIGHT_CONFIG" \
  "$TARGET_OC/package.json" \
  "$BACKUP_ROOT"

CONFIG_DECISIONS="$TMP_DIR/config-decisions.txt"
PACKAGE_DECISIONS="$TMP_DIR/package-decisions.txt"

if [ "$MODE" = "full" ]; then
  CONFIG_SCRIPT="$TMP_DIR/merge-config.cjs"
  cat >"$CONFIG_SCRIPT" <<'NODE'
"use strict";

const fs = require("fs");
const path = require("path");

const targetPath = process.argv[2];
const harnessPath = process.argv[3];
const backupRoot = process.argv[4];
const decisionsPath = process.argv[5];
const relTarget = ".opencode/opencode.json";
const CONSTITUTION = ".opencode/constitution.md";

const decisions = [];

function note(message) {
  decisions.push(message);
}

function warn(message) {
  process.stderr.write("warning: " + message + "\n");
}

function isPlainObject(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function clone(value) {
  return JSON.parse(JSON.stringify(value));
}

function fail(message) {
  process.stderr.write("error: " + message + "\n");
  process.exit(1);
}

function backup(raw) {
  const dest = path.join(backupRoot, relTarget);
  fs.mkdirSync(path.dirname(dest), { recursive: true, mode: 0o700 });
  try {
    fs.chmodSync(backupRoot, 0o700);
    fs.chmodSync(path.dirname(backupRoot), 0o700);
  } catch (_) {
    // Best effort: the backup itself is still usable.
  }
  fs.writeFileSync(dest, raw);
  try {
    fs.chmodSync(dest, fs.statSync(targetPath).mode & 0o777);
  } catch (_) {
    // Best effort: keep the backup writable by the owner.
  }
  return dest;
}

function finish() {
  if (decisions.length > 0) {
    fs.writeFileSync(decisionsPath, decisions.join("\n") + "\n");
  }
}

// Harness defaults fill gaps; the target always wins for existing values.
function mergeDefaults(defaults, current) {
  if (isPlainObject(defaults) && isPlainObject(current)) {
    const result = { ...current };
    for (const key of Object.keys(defaults)) {
      if (!Object.prototype.hasOwnProperty.call(result, key)) {
        result[key] = clone(defaults[key]);
      } else if (isPlainObject(defaults[key]) && isPlainObject(result[key])) {
        result[key] = mergeDefaults(defaults[key], result[key]);
      }
    }
    return result;
  }
  return current;
}

let harness;
try {
  harness = JSON.parse(fs.readFileSync(harnessPath, "utf8"));
} catch (error) {
  fail("cannot read harness config " + harnessPath + ": " + error.message);
}
if (!isPlainObject(harness)) {
  fail("harness config is not a JSON object: " + harnessPath);
}

if (!fs.existsSync(targetPath)) {
  fs.mkdirSync(path.dirname(targetPath), { recursive: true });
  fs.writeFileSync(targetPath, JSON.stringify(harness, null, 2) + "\n");
  note("default_agent: set to " + JSON.stringify(harness.default_agent || "orchestrator"));
  note(
    "subagent_depth: set to " +
      JSON.stringify(harness.subagent_depth === undefined ? 2 : harness.subagent_depth)
  );
  note('instructions: added "' + CONSTITUTION + '"');
  note("permission: copied harness block");
  finish();
  process.exit(0);
}

const raw = fs.readFileSync(targetPath, "utf8");
let target;
try {
  target = JSON.parse(raw);
} catch (error) {
  const dest = backup(raw);
  fail("invalid JSON in " + targetPath + " (backup: " + dest + ")");
}
if (!isPlainObject(target)) {
  const dest = backup(raw);
  fail("invalid JSON in " + targetPath + " (expected an object; backup: " + dest + ")");
}

const merged = mergeDefaults(harness, target);

if (Object.prototype.hasOwnProperty.call(target, "instructions")) {
  if (Array.isArray(target.instructions)) {
    const instructions = target.instructions.slice();
    if (instructions.indexOf(CONSTITUTION) === -1) {
      instructions.push(CONSTITUTION);
      note('instructions: added "' + CONSTITUTION + '"');
    } else {
      note('instructions: already includes "' + CONSTITUTION + '"');
    }
    merged.instructions = instructions;
  } else {
    warn("instructions in " + targetPath + " is not an array; leaving it unchanged");
    note("instructions: kept existing (not an array; skipped)");
    merged.instructions = target.instructions;
  }
} else {
  merged.instructions = Array.isArray(harness.instructions)
    ? clone(harness.instructions)
    : [CONSTITUTION];
  note('instructions: added "' + CONSTITUTION + '"');
}

if (Object.prototype.hasOwnProperty.call(target, "default_agent")) {
  if (target.default_agent === (harness.default_agent || "orchestrator")) {
    note("default_agent: kept " + JSON.stringify(target.default_agent));
  } else {
    note(
      "default_agent: kept " +
        JSON.stringify(target.default_agent) +
        ' (harness default is "orchestrator")'
    );
  }
} else {
  merged.default_agent = harness.default_agent || "orchestrator";
  note("default_agent: set to " + JSON.stringify(merged.default_agent));
}

if (Object.prototype.hasOwnProperty.call(target, "subagent_depth")) {
  const depth = target.subagent_depth;
  if (typeof depth === "number" && depth >= 2) {
    note("subagent_depth: kept " + JSON.stringify(depth));
  } else {
    warn(
      "subagent_depth in " +
        targetPath +
        " is " +
        JSON.stringify(depth) +
        "; issue orchestration needs 2 (opencode >= 1.18.2). Leaving it unchanged."
    );
    note("subagent_depth: kept existing (below 2; not overridden)");
    merged.subagent_depth = depth;
  }
} else {
  merged.subagent_depth =
    harness.subagent_depth === undefined ? 2 : clone(harness.subagent_depth);
  note("subagent_depth: set to " + JSON.stringify(merged.subagent_depth));
}

const harnessPermission = isPlainObject(harness.permission) ? harness.permission : {};

if (!Object.prototype.hasOwnProperty.call(target, "permission")) {
  if (isPlainObject(harness.permission)) {
    merged.permission = clone(harness.permission);
    note("permission: copied harness block");
  }
} else if (!isPlainObject(target.permission)) {
  warn("permission in " + targetPath + " is not an object; leaving it unchanged");
  note("permission: kept existing (not an object)");
  merged.permission = target.permission;
} else {
  // Base the result on the target permission object so mergeDefaults cannot
  // silently reintroduce a harness bash block when the target has none.
  const permission = { ...target.permission };
  const added = [];

  for (const key of Object.keys(harnessPermission)) {
    if (key === "bash") {
      continue;
    }
    if (!Object.prototype.hasOwnProperty.call(target.permission, key)) {
      permission[key] = clone(harnessPermission[key]);
      added.push(key);
    } else if (
      isPlainObject(harnessPermission[key]) &&
      isPlainObject(target.permission[key])
    ) {
      const nested = { ...target.permission[key] };
      for (const nestedKey of Object.keys(harnessPermission[key])) {
        if (!Object.prototype.hasOwnProperty.call(nested, nestedKey)) {
          nested[nestedKey] = clone(harnessPermission[key][nestedKey]);
          added.push(key + "." + nestedKey);
        }
      }
      permission[key] = nested;
    } else {
      permission[key] = target.permission[key];
    }
  }

  if (!Object.prototype.hasOwnProperty.call(target.permission, "bash")) {
    warn(
      "permission in " +
        targetPath +
        " has no bash policy; harness bash safety rules were not added (add a bash policy manually if desired)"
    );
    note("permission.bash: not added (target has no bash policy)");
  } else if (isPlainObject(target.permission.bash)) {
    const bash = { ...target.permission.bash };
    const harnessBash = isPlainObject(harnessPermission.bash)
      ? harnessPermission.bash
      : {};
    const star = bash["*"];

    // Never inject or relax "*": only extend a policy that explicitly allows
    // by default. Missing/deny/ask/non-string "*" values are left untouched.
    if (star === "allow") {
      let addedRules = 0;

      for (const rule of Object.keys(harnessBash)) {
        if (rule === "*") {
          continue;
        }
        if (!Object.prototype.hasOwnProperty.call(bash, rule)) {
          bash[rule] = clone(harnessBash[rule]);
          addedRules += 1;
        }
      }

      permission.bash = bash;
      if (addedRules > 0) {
        note("permission.bash: added " + addedRules + " missing rule(s)");
      } else {
        note("permission.bash: no missing rules");
      }
    } else {
      const shown = Object.prototype.hasOwnProperty.call(bash, "*")
        ? JSON.stringify(star)
        : "missing";
      warn(
        'permission.bash in ' +
          targetPath +
          ' has "*" ' +
          shown +
          '; harness bash rules were not added (only an explicit "*": "allow" policy is extended)'
      );
      note("permission.bash: kept existing rules (harness rules not added)");
    }
  } else {
    warn("permission.bash in " + targetPath + " is not an object; leaving it unchanged");
    note("permission.bash: kept existing (not an object)");
    permission.bash = target.permission.bash;
  }

  merged.permission = permission;
  if (added.length > 0) {
    note("permission: added " + added.join(", "));
  }
}

if (JSON.stringify(target) !== JSON.stringify(merged)) {
  const dest = backup(raw);
  fs.writeFileSync(targetPath, JSON.stringify(merged, null, 2) + "\n");
  note("config: merged into " + targetPath + " (backup: " + dest + ")");
} else {
  note("config: unchanged (existing formatting preserved)");
}

finish();
NODE

  "$MERGE_RUNNER" "$CONFIG_SCRIPT" \
    "$TARGET_OC/opencode.json" \
    "$HARNESS_ROOT/.opencode/opencode.json" \
    "$BACKUP_ROOT" \
    "$CONFIG_DECISIONS"
fi

WORKTREE_STATUS="not installed"

if [ "$MODE" = "full" ]; then
  install_managed_file "$HARNESS_ROOT/.opencode/constitution.md" ".opencode/constitution.md"
  for agent in "${AGENT_FILES[@]}"; do
    install_managed_file "$HARNESS_ROOT/.opencode/agents/$agent.md" ".opencode/agents/$agent.md"
  done
  for command in "${COMMAND_FILES[@]}"; do
    install_managed_file "$HARNESS_ROOT/.opencode/commands/$command.md" ".opencode/commands/$command.md"
  done

  install_if_absent "$HARNESS_ROOT/.opencode/worktree.jsonc" ".opencode/worktree.jsonc"
  WORKTREE_STATUS="$INSTALL_IF_ABSENT_STATUS"

  install_managed_file "$ISSUE_QUEUE_SRC" ".opencode/scripts/issue_queue.py"

  install_issue_file "$ISSUES_SRC/README.md" "issues/README.md"
  install_issue_file "$ISSUES_SRC/.gitignore" "issues/.gitignore"
  for state in "${ISSUE_STATES[@]}"; do
    install_issue_file "$ISSUES_SRC/$state/.gitkeep" "issues/$state/.gitkeep"
  done

  if [ "$ISSUES_INSTALLED" -gt 0 ] && [ "$ISSUES_KEPT" -gt 0 ]; then
    ISSUES_STATUS="installed $ISSUES_INSTALLED, kept $ISSUES_KEPT existing"
  elif [ "$ISSUES_INSTALLED" -gt 0 ]; then
    ISSUES_STATUS="installed ($ISSUES_INSTALLED file(s))"
  elif [ "$ISSUES_KEPT" -gt 0 ]; then
    ISSUES_STATUS="kept existing (project files win)"
  fi

  ensure_root_gitignore

  if git -C "$TARGET_ABS" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    tracked_issues="$(git -C "$TARGET_ABS" ls-files -- issues 2>/dev/null)" || tracked_issues=""
    if [ -n "$tracked_issues" ]; then
      warn "issues/ is still tracked by git; run 'git rm -r --cached issues' in $TARGET_ABS to stop tracking the local queue"
    fi
  fi
fi

# Fallback when a harness file unexpectedly disappears between preflight and
# the copy pass.
if [ ! -d "$SRC_DIR" ]; then
  err "plugin source directory not found: $SRC_DIR"
  exit 1
fi

while IFS= read -r -d '' source; do
  rel="${source#"$SRC_DIR"/}"
  install_managed_file "$source" ".opencode/plugin/$rel"
done < <(find "$SRC_DIR" -type f -print0)

ensure_opencode_gitignore

TARGET_PKG="$TARGET_OC/package.json"
PACKAGE_SCRIPT="$TMP_DIR/merge-package.cjs"
cat >"$PACKAGE_SCRIPT" <<'NODE'
"use strict";

const fs = require("fs");
const path = require("path");

const targetPath = process.argv[2];
const manifestPath = process.argv[3];
const backupRoot = process.argv[4];
const decisionsPath = process.argv[5];
const relTarget = ".opencode/package.json";
const wanted = ["@opencode-ai/plugin", "jsonc-parser", "zod"];

const decisions = [];

function isPlainObject(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function fail(message) {
  process.stderr.write("error: " + message + "\n");
  process.exit(1);
}

function backup(raw) {
  const dest = path.join(backupRoot, relTarget);
  fs.mkdirSync(path.dirname(dest), { recursive: true, mode: 0o700 });
  try {
    fs.chmodSync(backupRoot, 0o700);
    fs.chmodSync(path.dirname(backupRoot), 0o700);
  } catch (_) {
    // Best effort: the backup itself is still usable.
  }
  fs.writeFileSync(dest, raw);
  try {
    fs.chmodSync(dest, fs.statSync(targetPath).mode & 0o777);
  } catch (_) {
    // Best effort: keep the backup writable by the owner.
  }
  return dest;
}

let manifest;
try {
  manifest = JSON.parse(fs.readFileSync(manifestPath, "utf8"));
} catch (error) {
  fail("cannot read plugin manifest " + manifestPath + ": " + error.message);
}
if (!isPlainObject(manifest)) {
  fail("plugin manifest is not a JSON object: " + manifestPath);
}

const incoming = isPlainObject(manifest.dependencies) ? manifest.dependencies : {};
let raw = null;
let pkg = {};

if (fs.existsSync(targetPath)) {
  raw = fs.readFileSync(targetPath);
  const text = raw.toString("utf8").trim();
  if (text !== "") {
    let parsed;
    try {
      parsed = JSON.parse(text);
    } catch (error) {
      const dest = backup(raw);
      fail("invalid JSON in " + targetPath + " (backup: " + dest + ")");
    }
    if (!isPlainObject(parsed)) {
      const dest = backup(raw);
      fail("invalid JSON in " + targetPath + " (expected an object; backup: " + dest + ")");
    }
    pkg = parsed;
  }
}

const before = JSON.stringify(pkg);
const existingDeps = pkg.dependencies;
const deps = isPlainObject(existingDeps) ? { ...existingDeps } : {};
const added = [];

for (const name of wanted) {
  const spec = incoming[name];
  if (typeof spec !== "string" || spec === "") {
    continue;
  }
  const existing = deps[name];
  if (typeof existing === "string" && existing !== "") {
    if (existing !== spec) {
      process.stderr.write(
        'note: keeping existing dependency "' +
          name +
          '"@"' +
          existing +
          '" (plugin declares "' +
          spec +
          '")\n'
      );
    }
    continue;
  }
  deps[name] = spec;
  added.push(name);
}

pkg.dependencies = deps;
const after = JSON.stringify(pkg);

if (before !== after) {
  if (raw !== null) {
    backup(raw);
  }
  fs.writeFileSync(targetPath, JSON.stringify(pkg, null, 2) + "\n");
  decisions.push("package.json: added " + added.join(", "));
} else {
  decisions.push("package.json: unchanged");
}

fs.writeFileSync(decisionsPath, decisions.join("\n") + "\n");
NODE

"$MERGE_RUNNER" "$PACKAGE_SCRIPT" "$TARGET_PKG" "$MANIFEST" "$BACKUP_ROOT" "$PACKAGE_DECISIONS"

SANDBOX_STATUS="omitted (use --with-sandbox to install the demo)"
if [ "$MODE" = "full" ] && [ "$WITH_SANDBOX" -eq 1 ]; then
  SANDBOX_DEST="$TARGET_ABS/sandbox"
  if [ -e "$SANDBOX_DEST" ] && [ ! -d "$SANDBOX_DEST" ]; then
    err "cannot install sandbox/: destination exists and is not a directory: $SANDBOX_DEST"
    exit 1
  fi

  if [ -d "$SANDBOX_DEST" ]; then
    if [ "$FORCE" -ne 1 ]; then
      SANDBOX_STATUS="skipped existing sandbox/ (use --force to replace)"
      warn "sandbox/ already exists; skipping (use --force to back it up and replace it)"
    else
      # Always replace under --force so stale generated files (for example
      # __pycache__) never survive the refresh.
      backup_dir "$SANDBOX_DEST" "sandbox"
      rm -rf -- "$SANDBOX_DEST"
      mkdir -p "$SANDBOX_DEST"
      for file in "${SANDBOX_FILES[@]}"; do
        cp -- "$SANDBOX_SRC/$file" "$SANDBOX_DEST/$file"
      done
      SANDBOX_STATUS="replaced (backup)"
    fi
  else
    mkdir -p "$SANDBOX_DEST"
    for file in "${SANDBOX_FILES[@]}"; do
      cp -- "$SANDBOX_SRC/$file" "$SANDBOX_DEST/$file"
    done
    SANDBOX_STATUS="installed (9 files)"
  fi
fi

if ! (cd "$TARGET_OC" && "$INSTALLER" install); then
  err "$INSTALLER install failed in $TARGET_OC"
  note "files and configuration were installed; re-run '$INSTALLER install' in $TARGET_OC or re-run this installer"
  exit 1
fi

if ! command -v bun >/dev/null 2>&1; then
  warn "bun is not on PATH; opencode-worktree needs the Bun runtime (bun:sqlite) at execution time"
fi

print_decisions() {
  local file="$1"
  local line
  if [ -f "$file" ]; then
    while IFS= read -r line; do
      if [ -n "$line" ]; then
        printf '    %s\n' "$line"
      fi
    done <"$file"
  fi
}

printf '\n'
if [ "$MODE" = "full" ]; then
  printf 'Full opencode harness installed into %s\n' "$TARGET_ABS"
else
  printf 'opencode-worktree plugin installed into %s\n' "$TARGET_ABS"
fi

if [ "$MODE" = "full" ]; then
  printf '  constitution: .opencode/constitution.md\n'
  printf '  agents:       .opencode/agents (%s)\n' "$(IFS=', '; printf '%s' "${AGENT_FILES[*]}")"
  printf '  commands:     .opencode/commands (%s)\n' "$(IFS=', '; printf '%s' "${COMMAND_FILES[*]}")"
  printf '  config:       .opencode/opencode.json (existing keys win)\n'
  printf '  worktree cfg: .opencode/worktree.jsonc (%s)\n' "$WORKTREE_STATUS"
  printf '  queue:        .opencode/scripts/issue_queue.py (main checkout issues/, shared by worktrees)\n'
  printf '  issues:       issues/ (%s; local, git-ignored via root-anchored /issues/)\n' "$ISSUES_STATUS"
  printf '  sandbox:      %s\n' "$SANDBOX_STATUS"
fi
printf '  plugin:       .opencode/plugin\n'
printf '  deps:         @opencode-ai/plugin, jsonc-parser, zod (in .opencode/package.json)\n'
printf '  installer:    %s install (%s)\n' "$INSTALLER" "$TARGET_OC"
printf '  merge notes:\n'
print_decisions "$CONFIG_DECISIONS"
print_decisions "$PACKAGE_DECISIONS"
if [ -d "$BACKUP_ROOT" ]; then
  printf '  backups:      %s\n' "$BACKUP_ROOT"
else
  printf '  backups:      none needed\n'
fi
if ! command -v bun >/dev/null 2>&1; then
  printf '  runtime:      bun not on PATH (required at execution time for bun:sqlite)\n'
fi
printf '  restart opencode to load the config/agents/plugin (config is loaded once at startup)\n'
printf '  note: managed directories are updated in place; files removed from the harness are not deleted here\n'
