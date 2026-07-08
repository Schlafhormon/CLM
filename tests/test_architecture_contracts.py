import ast
import re
from copy import deepcopy
from pathlib import Path

from clm import cli
from clm.runtimes.runc import RuncBackend


REPO_ROOT = Path(__file__).resolve().parents[1]
CORE_DIR = REPO_ROOT / "clm" / "core"
MIGRATION_SCRIPTS = (
    REPO_ROOT / "scripts" / "migrate_precopy_vip_cutover.sh",
    REPO_ROOT / "scripts" / "migrate_postcopy_lazy_pages_vip_cutover.sh",
)


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


def test_core_modules_do_not_import_runtime_monitoring_or_cli_legacy_modules():
    forbidden_prefixes = (
        "clm.runtimes",
        "clm.monitoring",
        "clm.cli",
    )
    violations = []

    for path in sorted(CORE_DIR.glob("*.py")):
        for module in sorted(_imported_modules(path)):
            if module.startswith(forbidden_prefixes):
                violations.append(f"{path.relative_to(REPO_ROOT)} imports {module}")

    assert violations == []


def test_runc_backend_external_and_command_modes_do_not_export_vip_environment():
    cases = {
        "external": {"mode": "external"},
        "command": {
            "mode": "command",
            "hooks": {
                "prepare": ["lbctl", "drain", "source"],
                "switch": ["lbctl", "activate", "dest"],
                "verify": ["curl", "-fsS", "http://service.example/health"],
            },
        },
    }

    for mode, traffic in cases.items():
        cfg = deepcopy(cli.DEFAULTS)
        cfg["traffic"] = traffic
        script = RuncBackend().build_legacy_migration_script(
            cfg,
            method="precopy",
            run_id=f"contract-{mode}",
            events_log="/tmp/clm/events.ndjson",
        )

        assert f"export TRAFFIC_MODE={mode}" in script
        assert not re.search(r"^export VIP_", script, flags=re.MULTILINE)
        assert "VIP_ADDR=" not in script
        assert "VIP_IF_SRC=" not in script
        assert "VIP_IF_DST=" not in script


def _traffic_mode_branch(script: str, function_name: str, branch_pattern: str) -> str:
    function_start = script.index(f"{function_name}()")
    case_start = script.index('case "$TRAFFIC_MODE" in', function_start)
    branch = re.search(
        rf"(?ms)^[ \t]*{branch_pattern}\)\r?\n(?P<body>.*?)[ \t]*;;",
        script[case_start:],
    )
    assert branch is not None, f"{function_name}: missing TRAFFIC_MODE branch {branch_pattern}"
    return branch.group("body")


def test_migration_scripts_keep_external_and_command_traffic_branches_non_vip():
    forbidden = ("ip addr", "conntrack", "arping")

    for path in MIGRATION_SCRIPTS:
        script = path.read_text(encoding="utf-8")
        assert 'TRAFFIC_MODE="${TRAFFIC_MODE:-vip}"' in script

        branches = [
            _traffic_mode_branch(script, "traffic_prepare", "external"),
            _traffic_mode_branch(script, "traffic_prepare", "command"),
            _traffic_mode_branch(script, "traffic_switch", "external"),
            _traffic_mode_branch(script, "traffic_switch", "command"),
            _traffic_mode_branch(script, "traffic_verify", r"external\|command"),
        ]
        for body in branches:
            for token in forbidden:
                assert token not in body, f"{path.relative_to(REPO_ROOT)} non-vip branch contains {token}"


def test_migration_scripts_do_not_eval_internal_runtime_commands():
    forbidden_patterns = (
        r"\beval\b",
        r"\brun\s*\(\)",
        r"\brun\s+['\"]",
    )

    for path in MIGRATION_SCRIPTS:
        script = path.read_text(encoding="utf-8")
        for pattern in forbidden_patterns:
            assert not re.search(pattern, script), f"{path.relative_to(REPO_ROOT)} contains forbidden {pattern}"

        assert "run_cmd()" in script
        assert "run_ssh()" in script
        assert "run_operator_shell_hook()" in script
        assert "run_operator_shell_hook \"$action\" \"$cmd\"" in script


def test_migration_scripts_limit_bash_lc_to_operator_traffic_hook_boundary():
    for path in MIGRATION_SCRIPTS:
        script = path.read_text(encoding="utf-8")
        hook_body = _bash_function_body(script, "run_operator_shell_hook")
        assert 'bash -lc "$command"' in hook_body

        script_without_hook = script.replace(hook_body, "")
        assert "bash -lc" not in script_without_hook, (
            f"{path.relative_to(REPO_ROOT)} uses bash -lc outside run_operator_shell_hook"
        )


def test_cli_package_facade_stays_small_compatibility_layer():
    path = REPO_ROOT / "clm" / "cli" / "__init__.py"
    text = path.read_text(encoding="utf-8")
    lines = [line for line in text.splitlines() if line.strip()]

    assert len(lines) <= 70
    assert "from . import legacy_run as _legacy" in text
    assert "def run_cli(" not in text
    assert "DEFAULTS =" not in text


def test_legacy_defaults_are_owned_by_core_not_legacy_runner():
    legacy_text = (REPO_ROOT / "clm" / "cli" / "legacy_run.py").read_text(encoding="utf-8")
    defaults_text = (REPO_ROOT / "clm" / "core" / "defaults.py").read_text(encoding="utf-8")

    assert "from clm.core.defaults import DEFAULTS" in legacy_text
    assert "DEFAULTS =" not in legacy_text
    assert "DEFAULTS:" in defaults_text


def _bash_function_body(script: str, function_name: str) -> str:
    match = re.search(rf"(?ms)^{re.escape(function_name)}\(\)\s*\{{(?P<body>.*?)^}}", script)
    assert match is not None, f"missing bash function {function_name}"
    return match.group("body")
