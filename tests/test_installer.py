"""Integration tests for the harness installer footprint (stdlib unittest).

The installer is run for real against throwaway target directories. The only
stubbed external command is the dependency installer (``bun``/``npm``): it logs
its invocation and exits 0 so no network or package install is attempted.
``node`` is required for the config/package merge; ``bash`` is required to run
the installer.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "plugin" / "opencode-worktree" / "install.sh"
HARNESS_CONFIG = ROOT / ".opencode" / "opencode.json"
BASH = shutil.which("bash")
NODE = shutil.which("node")
OPENCODE = shutil.which("opencode")

AGENTS = ("orchestrator", "lead", "planner", "coder", "reviewer", "researcher")
COMMANDS = ("issues", "feature", "ship", "status")
STATES = ("todo", "inprogress", "review", "completed")
LEGACY_AGENTS_MARKER = (
    "> Project-specific facts and conventions for agents working in this repository."
)


@unittest.skipUnless(BASH and NODE, "bash and node are required to run the installer")
class InstallerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.target = self.base / "target"
        self.target.mkdir()
        self.bin = self.base / "bin"
        self.bin.mkdir()
        self.log = self.base / "installer-calls.log"
        for name in ("bun", "npm"):
            stub = self.bin / name
            stub.write_text(
                "#!/usr/bin/env bash\n"
                'printf \'%s %s\\n\' "$(basename "$0")" "$*" >> "$STUB_LOG"\n'
                "exit 0\n",
                encoding="utf-8",
            )
            stub.chmod(0o755)

    # Helpers -------------------------------------------------------------

    def run_install(
        self, *args: str, target: Path | None = None, extra_env: dict[str, str] | None = None
    ) -> subprocess.CompletedProcess[str]:
        env = dict(os.environ)
        env["PATH"] = str(self.bin) + os.pathsep + env.get("PATH", "")
        env["STUB_LOG"] = str(self.log)
        if extra_env:
            env.update(extra_env)
        return subprocess.run(
            [BASH, str(INSTALLER), *args, str(target or self.target)],
            cwd=str(target or self.target),
            capture_output=True,
            text=True,
            timeout=120,
            env=env,
        )

    def read_config(self, target: Path | None = None) -> dict:
        path = (target or self.target) / ".opencode" / "opencode.json"
        return json.loads(path.read_text(encoding="utf-8"))

    def assert_inside_opencode_runtime(self, target: Path) -> None:
        oc = target / ".opencode"
        self.assertTrue((oc / "opencode.json").is_file())
        self.assertTrue((oc / "constitution.md").is_file())
        self.assertTrue((oc / "worktree.jsonc").is_file())
        self.assertTrue((oc / "scripts" / "issue_queue.py").is_file())
        self.assertTrue((oc / "plugin" / "worktree.ts").is_file())
        self.assertTrue((oc / "plugin" / "kdco-primitives" / "index.ts").is_file())
        pkg = json.loads((oc / "package.json").read_text(encoding="utf-8"))
        for dep in ("@opencode-ai/plugin", "jsonc-parser", "zod"):
            self.assertIn(dep, pkg["dependencies"])
        for agent in AGENTS:
            self.assertTrue((oc / "agents" / f"{agent}.md").is_file(), agent)
        for command in COMMANDS:
            self.assertTrue((oc / "commands" / f"{command}.md").is_file(), command)

    def assert_queue_scaffolding(self, target: Path) -> None:
        issues = target / "issues"
        self.assertTrue((issues / "README.md").is_file())
        self.assertTrue((issues / ".gitignore").is_file())
        for state in STATES:
            self.assertTrue((issues / state / ".gitkeep").is_file(), state)
        gitignore = (target / ".gitignore").read_text(encoding="utf-8").splitlines()
        self.assertIn("/issues/", gitignore)

    def assert_no_trimmed_paths(self, target: Path) -> None:
        self.assertFalse((target / "opencode.json").exists())
        self.assertFalse((target / "opencode.jsonc").exists())
        self.assertFalse((target / "scripts").exists())
        self.assertFalse((target / "docs").exists())
        self.assertFalse((target / "AGENTS.md").exists())

    def backup_entries(self, target: Path) -> list[Path]:
        root = target / ".opencode" / ".install-backups"
        if not root.is_dir():
            return []
        return sorted(path for path in root.iterdir() if path.is_dir())

    # Default footprint ---------------------------------------------------

    def test_default_full_install_footprint(self):
        result = self.run_install()
        self.assertEqual(result.returncode, 0, result.stderr)

        self.assert_inside_opencode_runtime(self.target)
        self.assert_queue_scaffolding(self.target)
        self.assert_no_trimmed_paths(self.target)
        self.assertFalse((self.target / "sandbox").exists())

        config = self.read_config()
        harness = json.loads(HARNESS_CONFIG.read_text(encoding="utf-8"))
        self.assertEqual(config, harness)
        self.assertEqual(config["default_agent"], "orchestrator")
        self.assertEqual(config["subagent_depth"], 2)
        self.assertEqual(config["instructions"], [".opencode/constitution.md"])
        self.assertEqual(config["permission"]["bash"]["*"], "allow")
        self.assertEqual(config["permission"]["bash"]["git push*"], "ask")

        oc_gitignore = (self.target / ".opencode" / ".gitignore").read_text(
            encoding="utf-8"
        )
        for line in oc_gitignore.splitlines():
            self.assertNotEqual(line.strip(), "opencode.json")
        self.assertTrue(self.log.is_file())
        self.assertIn("install", self.log.read_text(encoding="utf-8"))

    def test_installed_queue_runs_from_the_project_root(self):
        result = self.run_install()
        self.assertEqual(result.returncode, 0, result.stderr)

        status = subprocess.run(
            [
                "python3",
                str(self.target / ".opencode" / "scripts" / "issue_queue.py"),
                "status",
            ],
            cwd=str(self.target),
            capture_output=True,
            text=True,
            timeout=30,
            env=self._queue_env(),
        )
        self.assertEqual(status.returncode, 0, status.stderr)
        for state in STATES:
            self.assertIn(f"{state}: 0", status.stdout)

    @unittest.skipUnless(OPENCODE, "opencode is not installed")
    def test_opencode_debug_config_loads_harness_defaults(self):
        result = self.run_install()
        self.assertEqual(result.returncode, 0, result.stderr)

        home = self.base / "home"
        home.mkdir()
        env = dict(os.environ)
        env["HOME"] = str(home)
        env["XDG_CONFIG_HOME"] = str(home / ".config")
        debug = subprocess.run(
            [OPENCODE, "debug", "config"],
            cwd=str(self.target),
            capture_output=True,
            text=True,
            timeout=60,
            env=env,
        )
        if debug.returncode != 0 and self._debug_config_unsupported(debug.stderr):
            self.skipTest(
                "opencode debug config is not supported by this build: "
                + (debug.stderr.strip() or debug.stdout.strip())[:200]
            )
        self.assertEqual(
            debug.returncode,
            0,
            "opencode debug config failed in the temporary target\n"
            f"stdout:\n{debug.stdout}\nstderr:\n{debug.stderr}",
        )
        text = debug.stdout
        start = text.find("{")
        self.assertGreaterEqual(
            start,
            0,
            "opencode debug config did not emit JSON\n"
            f"stdout:\n{debug.stdout}\nstderr:\n{debug.stderr}",
        )
        try:
            config = json.loads(text[start:])
        except json.JSONDecodeError as error:
            self.fail(
                f"could not parse opencode debug config JSON: {error}\n"
                f"stdout:\n{debug.stdout}\nstderr:\n{debug.stderr}"
            )
        self.assertEqual(config.get("default_agent"), "orchestrator")
        self.assertEqual(config.get("subagent_depth"), 2)
        self.assertIn(".opencode/constitution.md", config.get("instructions", []))

    # Modes ---------------------------------------------------------------

    def test_with_sandbox_adds_only_sandbox(self):
        result = self.run_install("--with-sandbox")
        self.assertEqual(result.returncode, 0, result.stderr)

        sandbox = self.target / "sandbox"
        self.assertTrue((sandbox / "main.py").is_file())
        self.assertTrue((sandbox / "AGENTS.md").is_file())
        self.assertTrue((sandbox / "test_main.py").is_file())
        self.assert_inside_opencode_runtime(self.target)
        self.assert_queue_scaffolding(self.target)
        self.assert_no_trimmed_paths(self.target)

    def test_plugin_only_does_not_install_the_harness(self):
        result = self.run_install("--plugin-only")
        self.assertEqual(result.returncode, 0, result.stderr)

        oc = self.target / ".opencode"
        self.assertTrue((oc / "plugin" / "worktree.ts").is_file())
        self.assertTrue((oc / "package.json").is_file())
        self.assertTrue((oc / ".gitignore").is_file())
        for relative in (
            "opencode.json",
            "constitution.md",
            "agents",
            "commands",
            "scripts",
            "worktree.jsonc",
        ):
            self.assertFalse((oc / relative).exists(), relative)
        self.assertFalse((self.target / "issues").exists())
        self.assertFalse((self.target / ".gitignore").exists())
        self.assert_no_trimmed_paths(self.target)

    # Config merge --------------------------------------------------------

    def test_preserves_existing_target_config_values(self):
        oc = self.target / ".opencode"
        oc.mkdir()
        existing = {
            "default_agent": "build",
            "subagent_depth": 3,
            "instructions": ["custom.md"],
            "custom": {"keep": True},
            "permission": {
                "bash": {"*": "ask", "git push*": "deny"},
                "webfetch": "deny",
            },
        }
        (oc / "opencode.json").write_text(json.dumps(existing), encoding="utf-8")

        result = self.run_install()
        self.assertEqual(result.returncode, 0, result.stderr)

        config = self.read_config()
        self.assertEqual(config["default_agent"], "build")
        self.assertEqual(config["subagent_depth"], 3)
        self.assertEqual(config["custom"], {"keep": True})
        self.assertEqual(config["instructions"], ["custom.md", ".opencode/constitution.md"])
        self.assertEqual(config["permission"]["bash"], {"*": "ask", "git push*": "deny"})
        self.assertEqual(config["permission"]["webfetch"], "deny")
        self.assertIn("permission.bash", result.stderr)
        self.assertIn('"*" "ask"', result.stderr)
        backups = self.backup_entries(self.target)
        self.assertEqual(len(backups), 1)
        self.assertTrue((backups[0] / ".opencode" / "opencode.json").is_file())

    def test_installer_avoids_nonportable_end_of_options(self):
        installer = INSTALLER.read_text(encoding="utf-8")
        for pattern in (
            "mkdir -p --",
            "chmod 0700 --",
            "cp -p --",
            "cp -a --",
            'cp -- "',
            "rm -rf --",
            "dirname --",
            "readlink -f --",
        ):
            with self.subTest(pattern=pattern):
                self.assertNotIn(pattern, installer)

    def test_backup_survives_chmod_without_end_of_options(self):
        real_chmod = shutil.which("chmod")
        self.assertIsNotNone(real_chmod)
        stub = self.bin / "chmod"
        stub.write_text(
            "#!/usr/bin/env bash\n"
            'for arg in "$@"; do\n'
            '  if [ "$arg" = "--" ]; then\n'
            '    echo "chmod: --; no such file or directory" >&2\n'
            "    exit 1\n"
            "  fi\n"
            "done\n"
            f'exec "{real_chmod}" "$@"\n',
            encoding="utf-8",
        )
        stub.chmod(0o755)

        oc = self.target / ".opencode"
        oc.mkdir()
        (oc / "opencode.json").write_text(
            json.dumps({"custom": {"keep": True}}), encoding="utf-8"
        )

        result = self.run_install()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("chmod: --", result.stderr)
        self.assertEqual(self.read_config()["custom"], {"keep": True})
        backups = self.backup_entries(self.target)
        self.assertEqual(len(backups), 1)
        self.assertTrue((backups[0] / ".opencode" / "opencode.json").is_file())

    def test_bash_allow_policy_gains_missing_harness_rules(self):
        oc = self.target / ".opencode"
        oc.mkdir()
        existing = {
            "instructions": [".opencode/constitution.md"],
            "permission": {"bash": {"*": "allow", "rm -rf*": "allow"}},
        }
        (oc / "opencode.json").write_text(json.dumps(existing), encoding="utf-8")

        result = self.run_install()
        self.assertEqual(result.returncode, 0, result.stderr)

        config = self.read_config()
        bash = config["permission"]["bash"]
        self.assertEqual(bash["*"], "allow")
        self.assertEqual(bash["rm -rf*"], "allow")  # target value wins
        self.assertEqual(bash["git push*"], "ask")
        self.assertEqual(bash["git clean -f*"], "ask")
        self.assertIn("permission.bash: added", result.stdout)
        self.assertEqual(config["instructions"], [".opencode/constitution.md"])

    def test_root_config_is_warned_about_and_not_modified(self):
        root_config = self.target / "opencode.json"
        original = '{\n  "default_agent": "build",\n  "custom": 1\n}\n'
        root_config.write_text(original, encoding="utf-8")

        result = self.run_install()
        self.assertEqual(result.returncode, 0, result.stderr)

        self.assertIn("root opencode.json", result.stderr)
        self.assertIn("wins on conflicting keys", result.stderr)
        self.assertEqual(root_config.read_text(encoding="utf-8"), original)
        config = self.read_config()
        self.assertEqual(config["default_agent"], "orchestrator")
        self.assertEqual(config["subagent_depth"], 2)

    def test_root_opencode_jsonc_is_warned_about_and_not_modified(self):
        root_config = self.target / "opencode.jsonc"
        original = '{ // root\n  "custom": 1\n}\n'
        root_config.write_text(original, encoding="utf-8")

        result = self.run_install()
        self.assertEqual(result.returncode, 0, result.stderr)

        self.assertIn("root opencode.jsonc", result.stderr)
        self.assertEqual(root_config.read_text(encoding="utf-8"), original)
        self.assertTrue((self.target / ".opencode" / "opencode.json").is_file())

    def test_target_opencode_jsonc_is_rejected_before_writes(self):
        oc = self.target / ".opencode"
        oc.mkdir()
        (oc / "opencode.jsonc").write_text('{\n  "default_agent": "build"\n}\n', encoding="utf-8")

        result = self.run_install()
        self.assertEqual(result.returncode, 1, result.stderr)

        self.assertIn(".opencode/opencode.jsonc", result.stderr)
        self.assertIn("--plugin-only", result.stderr)
        self.assertFalse((oc / "opencode.json").exists())
        self.assertFalse((self.target / "issues").exists())
        self.assertFalse((self.target / ".gitignore").exists())
        self.assertFalse((oc / "agents").exists())
        self.assertEqual(self.log.read_text(encoding="utf-8") if self.log.exists() else "", "")

    def test_invalid_target_config_stops_before_other_writes(self):
        oc = self.target / ".opencode"
        oc.mkdir()
        (oc / "opencode.json").write_text("{not json", encoding="utf-8")

        result = self.run_install()
        self.assertEqual(result.returncode, 1, result.stderr)

        self.assertIn("invalid JSON", result.stderr)
        self.assertFalse((oc / "agents").exists())
        self.assertFalse((oc / "constitution.md").exists())
        self.assertFalse((self.target / "issues").exists())
        backups = self.backup_entries(self.target)
        self.assertEqual(len(backups), 1)
        self.assertTrue((backups[0] / ".opencode" / "opencode.json").is_file())

    # Idempotency ---------------------------------------------------------

    def test_second_run_is_idempotent_and_makes_no_backups(self):
        first = self.run_install()
        self.assertEqual(first.returncode, 0, first.stderr)
        config_after_first = (self.target / ".opencode" / "opencode.json").read_bytes()
        self.assertEqual(self.backup_entries(self.target), [])

        second = self.run_install()
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(
            (self.target / ".opencode" / "opencode.json").read_bytes(),
            config_after_first,
        )
        self.assertEqual(self.backup_entries(self.target), [])
        self.assertEqual(
            len((self.target / ".gitignore").read_text(encoding="utf-8").splitlines()),
            1,
        )

    # Legacy files --------------------------------------------------------

    def test_legacy_files_only_warn_and_are_never_modified(self):
        legacy_script = self.target / "scripts" / "issue_queue.py"
        legacy_script.parent.mkdir()
        legacy_script.write_text("# old queue\n", encoding="utf-8")
        legacy_docs = self.target / "docs" / "validation.md"
        legacy_docs.parent.mkdir()
        legacy_docs.write_text("# old docs\n", encoding="utf-8")
        legacy_agents = self.target / "AGENTS.md"
        legacy_agents.write_text(
            "# Workspace Notes\n\n" + LEGACY_AGENTS_MARKER + "\n", encoding="utf-8"
        )

        result = self.run_install()
        self.assertEqual(result.returncode, 0, result.stderr)

        self.assertIn("legacy root scripts/issue_queue.py", result.stderr)
        self.assertIn("legacy harness docs/validation.md", result.stderr)
        self.assertIn("looks harness-installed", result.stderr)
        self.assertEqual(legacy_script.read_text(encoding="utf-8"), "# old queue\n")
        self.assertEqual(legacy_docs.read_text(encoding="utf-8"), "# old docs\n")
        self.assertEqual(
            legacy_agents.read_text(encoding="utf-8"),
            "# Workspace Notes\n\n" + LEGACY_AGENTS_MARKER + "\n",
        )
        self.assertTrue(
            (self.target / ".opencode" / "scripts" / "issue_queue.py").is_file()
        )

    # Bad destinations ----------------------------------------------------

    def test_bad_destination_types_fail_before_writes(self):
        cases = (
            (
                "scripts-as-file",
                lambda target: self._make_file(target / ".opencode" / "scripts"),
                "exists but is not a directory",
            ),
            (
                "config-as-directory",
                lambda target: (target / ".opencode" / "opencode.json").mkdir(parents=True),
                "exists but is not a regular file",
            ),
        )
        for name, create, message in cases:
            with self.subTest(case=name):
                target = self.base / name
                target.mkdir()
                (target / ".opencode").mkdir()
                create(target)

                result = self.run_install(target=target)
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertIn(message, result.stderr)
                self.assertFalse((target / ".opencode" / "agents").exists())
                self.assertFalse((target / "issues").exists())
                self.assertFalse((target / ".gitignore").exists())

    # Utilities -----------------------------------------------------------

    @staticmethod
    def _debug_config_unsupported(stderr: str) -> bool:
        """Return True only when stderr shows the subcommand is genuinely absent."""
        lowered = stderr.lower()
        markers = (
            "unknown command",
            "unknown subcommand",
            "unsupported command",
            "unrecognized command",
            "unrecognised command",
            "not a valid command",
        )
        return any(marker in lowered for marker in markers)

    def _make_file(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("not a directory\n", encoding="utf-8")

    def _queue_env(self) -> dict[str, str]:
        # Keep the queue off any enclosing repository: the target is a real
        # project root, so the non-git fallback is <project>/issues.
        env = dict(os.environ)
        env["PATH"] = str(self.bin) + os.pathsep + env.get("PATH", "")
        return env


if __name__ == "__main__":
    unittest.main()
