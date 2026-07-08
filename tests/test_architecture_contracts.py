import ast
import re
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from clm import cli
from clm.core.models import PreflightResult, TrafficPlan
from clm.migration.traffic.command import CommandTrafficBackend
from clm.migration.traffic.external import ExternalTrafficBackend
from clm.runtimes.runc import RuncBackend


REPO_ROOT = Path(__file__).resolve().parents[1]
CORE_DIR = REPO_ROOT / "clm" / "core"
RUNTIMES_DIR = REPO_ROOT / "clm" / "runtimes"
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


def _python_files(root: Path) -> list[Path]:
    return sorted(path for path in root.rglob("*.py") if "__pycache__" not in path.parts)


def _parsed_module(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _has_true_assignment(tree: ast.AST, name: str) -> bool:
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(target, ast.Name) and target.id == name for target in node.targets):
            continue
        if isinstance(node.value, ast.Constant) and node.value.value is True:
            return True
    return False


def test_core_modules_do_not_import_runtime_monitoring_analysis_or_cli_legacy_modules():
    forbidden_prefixes = (
        "clm.runtimes",
        "clm.monitoring",
        "clm.analysis",
        "clm.analysis_pipeline",
        "clm.cli",
    )
    violations = []

    for path in _python_files(CORE_DIR):
        for module in sorted(_imported_modules(path)):
            if module.startswith(forbidden_prefixes):
                violations.append(f"{path.relative_to(REPO_ROOT)} imports {module}")

    assert violations == []


def test_runtime_backends_do_not_import_cli_outside_marked_legacy_adapters():
    violations = []

    for path in _python_files(RUNTIMES_DIR):
        tree = _parsed_module(path)
        is_legacy_adapter = _has_true_assignment(tree, "LEGACY_ADAPTER_BOUNDARY")
        for module in sorted(_imported_modules(path)):
            if module == "clm.cli" or module.startswith("clm.cli."):
                if not is_legacy_adapter:
                    violations.append(f"{path.relative_to(REPO_ROOT)} imports {module}")

    assert violations == []


def test_external_and_command_traffic_backends_do_not_export_vip_environment():
    backends = (
        ExternalTrafficBackend(
            TrafficPlan(
                mode="external",
                hooks={"verify": ["curl", "-fsS", "http://service.example/health"]},
            )
        ),
        CommandTrafficBackend(
            TrafficPlan(
                mode="command",
                hooks={
                    "prepare": ["lbctl", "drain", "source"],
                    "switch": ["lbctl", "activate", "dest"],
                    "verify": ["curl", "-fsS", "http://service.example/health"],
                },
            )
        ),
    )

    for backend in backends:
        env = backend.script_env({})
        assert env["TRAFFIC_MODE"] == backend.mode
        assert not any(name.startswith("VIP_") for name in env)


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


def test_no_load_run_only_starts_synthetic_load_inside_load_modes_guard():
    tree = _parsed_module(REPO_ROOT / "clm" / "cli" / "legacy_run.py")
    parents = {}
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            parents[child] = parent

    start_load_calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "start_load"
    ]
    assert start_load_calls, "expected run path to contain the legacy start_load call"

    for call in start_load_calls:
        node = call
        guarded_by_load_modes = False
        while node in parents:
            node = parents[node]
            if isinstance(node, ast.FunctionDef):
                break
            if isinstance(node, ast.If):
                names = {name.id for name in ast.walk(node.test) if isinstance(name, ast.Name)}
                if "load_modes" in names:
                    guarded_by_load_modes = True
                    break
        assert guarded_by_load_modes


def test_preflight_and_run_use_same_run_capability_gate_for_executable_methods():
    blocked = PreflightResult(
        checks=({"name": "contract gate", "ok": False, "detail": "blocked by test"},),
        blockers=("blocked by test",),
    )
    cfg = deepcopy(cli.DEFAULTS)

    with patch("clm.cli.validate_run_capabilities", return_value=blocked) as gate:
        assert cli.preflight(cfg, dry_run=False, method="precopy") == 1
        assert gate.call_args.args == (cfg, "precopy")

    with patch("clm.cli.validate_run_capabilities", return_value=blocked) as gate:
        assert cli.run_cli(
            cfg,
            method="precopy",
            repeats=1,
            load_flags=None,
            no_monitor=True,
            no_migrate=True,
            no_cleanup=True,
            auto_analyse=False,
            env_path="config/env.yaml",
            cli_argv=["run", "--method", "precopy"],
        ) == 1
        assert gate.call_args.args == (cfg, "precopy")


def test_packaging_includes_all_clm_subpackages():
    try:
        import tomllib
    except ModuleNotFoundError:  # pragma: no cover - Python < 3.11 fallback
        import tomli as tomllib
    from setuptools import find_packages

    config = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    find_config = config["tool"]["setuptools"]["packages"]["find"]
    include = find_config.get("include") or ["*"]
    exclude = find_config.get("exclude") or ()
    discovered = set(find_packages(where=str(REPO_ROOT), include=include, exclude=exclude))
    expected = {
        ".".join(init.parent.relative_to(REPO_ROOT).parts)
        for init in (REPO_ROOT / "clm").rglob("__init__.py")
        if "__pycache__" not in init.parts
    }

    assert expected - discovered == set()


def _bash_function_body(script: str, function_name: str) -> str:
    match = re.search(rf"(?ms)^{re.escape(function_name)}\(\)\s*\{{(?P<body>.*?)^}}", script)
    assert match is not None, f"missing bash function {function_name}"
    return match.group("body")
