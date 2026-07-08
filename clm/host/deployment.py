"""Temporary host artifact deployment for script-based execution."""

from __future__ import annotations

import base64
import re
import shlex
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence


RunRemote = Callable[..., Any]

DEPLOYMENT_MODE_ARTIFACT = "artifact_deploy"
DEPLOYMENT_MODE_LEGACY_REPO = "legacy_repo"
_MODE_ALIASES = {
    "artifact": DEPLOYMENT_MODE_ARTIFACT,
    "artifacts": DEPLOYMENT_MODE_ARTIFACT,
    "deploy": DEPLOYMENT_MODE_ARTIFACT,
    "artifact_deploy": DEPLOYMENT_MODE_ARTIFACT,
    "host_artifact": DEPLOYMENT_MODE_ARTIFACT,
    "host_artifacts": DEPLOYMENT_MODE_ARTIFACT,
    "legacy": DEPLOYMENT_MODE_LEGACY_REPO,
    "legacy_repo": DEPLOYMENT_MODE_LEGACY_REPO,
    "repo": DEPLOYMENT_MODE_LEGACY_REPO,
}

_SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9_.-]+")
DEFAULT_REMOTE_TEMP_ROOT = "/tmp"


@dataclass(frozen=True)
class HostDeploymentConfig:
    """Resolved host deployment settings."""

    mode: str = DEPLOYMENT_MODE_ARTIFACT
    remote_temp_root: str = DEFAULT_REMOTE_TEMP_ROOT
    cleanup_temp_on_success: bool = True
    scripts_root: Path = field(default_factory=lambda: _repo_root() / "scripts")

    @classmethod
    def from_config(cls, config: dict[str, Any] | None) -> "HostDeploymentConfig":
        cfg = config or {}
        execution = dict(cfg.get("execution") or {})
        deployment = dict(cfg.get("deployment") or {})
        mode = normalize_deployment_mode(
            execution.get("deployment_mode")
            or execution.get("mode")
            or deployment.get("mode")
            or DEPLOYMENT_MODE_ARTIFACT
        )
        temp_root = (
            execution.get("remote_temp_root")
            or deployment.get("remote_temp_root")
            or deployment.get("temp_root")
            or DEFAULT_REMOTE_TEMP_ROOT
        )
        cleanup = execution.get("cleanup_temp_on_success", deployment.get("cleanup_temp_on_success", True))
        scripts_root = execution.get("scripts_root") or deployment.get("scripts_root")
        return cls(
            mode=mode,
            remote_temp_root=_normalize_remote_root(str(temp_root)),
            cleanup_temp_on_success=_as_bool(cleanup),
            scripts_root=Path(scripts_root).expanduser() if scripts_root else _repo_root() / "scripts",
        )


@dataclass(frozen=True)
class DeployedHostArtifacts:
    """Remote script deployment created for one host operation."""

    host: str
    workdir: str
    repo_path: str
    files: tuple[str, ...]
    temp_root: str
    cleanup_temp_on_success: bool
    _run_remote: RunRemote = field(repr=False, compare=False)

    def cleanup_after_success(self) -> dict[str, Any]:
        """Remove only the generated temporary workdir after successful use."""

        if not self.cleanup_temp_on_success:
            return {"attempted": False, "ok": None, "reason": "disabled", "path": self.workdir}
        script = _safe_temp_cleanup_script(self.workdir, self.temp_root)
        result = self._run_remote(self.host, script, check=False, capture=True)
        return {
            "attempted": True,
            "ok": result.returncode == 0,
            "returncode": result.returncode,
            "path": self.workdir,
        }


def normalize_deployment_mode(value: str | None) -> str:
    """Normalize execution/deployment mode config values."""

    key = str(value or DEPLOYMENT_MODE_ARTIFACT).strip().lower().replace("-", "_")
    mode = _MODE_ALIASES.get(key)
    if mode is None:
        raise ValueError(f"Unsupported deployment mode: {value}")
    return mode


def deployment_config_for(config: dict[str, Any] | None) -> HostDeploymentConfig:
    return HostDeploymentConfig.from_config(config)


def deployment_mode_for(config: dict[str, Any] | None) -> str:
    return deployment_config_for(config).mode


def migration_script_names(method: str) -> tuple[str, str]:
    """Return the minimal script set needed for a runc migration method."""

    if method == "precopy":
        return ("migrate_precopy.sh", "migrate_precopy_vip_cutover.sh")
    if method == "postcopy":
        return ("migrate_postcopy_lazy_pages.sh", "migrate_postcopy_lazy_pages_vip_cutover.sh")
    raise ValueError(f"unsupported migration method for script deployment: {method}")


def baseline_reset_script_names() -> tuple[str, str]:
    return ("restore_runc_bundle_baseline.sh", "patch_runc_bundle_for_criu.sh")


def validate_local_scripts(config: dict[str, Any] | None, names: Iterable[str]) -> tuple[bool, str]:
    """Check that controller-side script artifacts are available."""

    deploy_cfg = deployment_config_for(config)
    missing: list[str] = []
    for name in names:
        try:
            _local_script_path(deploy_cfg.scripts_root, name)
        except FileNotFoundError:
            missing.append(name)
    if missing:
        return False, "missing: " + ", ".join(missing)
    return True, str(deploy_cfg.scripts_root)


def deploy_scripts(
    host: str,
    config: dict[str, Any] | None,
    *,
    script_names: Sequence[str],
    run_id: str,
    run_remote: RunRemote,
) -> DeployedHostArtifacts:
    """Copy selected scripts to a new remote temp workdir."""

    deploy_cfg = deployment_config_for(config)
    workdir = _create_remote_workdir(host, deploy_cfg.remote_temp_root, run_id=run_id, run_remote=run_remote)
    scripts_dir = _posix_join(workdir, "scripts")
    deployed: list[str] = []
    for name in script_names:
        local_path = _local_script_path(deploy_cfg.scripts_root, name)
        remote_path = _posix_join(scripts_dir, local_path.name)
        run_remote(host, _copy_file_script(remote_path, local_path.read_bytes()), check=True)
        deployed.append(f"scripts/{local_path.name}")
    return DeployedHostArtifacts(
        host=host,
        workdir=workdir,
        repo_path=workdir,
        files=tuple(deployed),
        temp_root=deploy_cfg.remote_temp_root,
        cleanup_temp_on_success=deploy_cfg.cleanup_temp_on_success,
        _run_remote=run_remote,
    )


def preflight_tempdir_script(config: dict[str, Any] | None) -> str:
    """Render a side-effect-limited remote tempdir check for deploy mode."""

    deploy_cfg = deployment_config_for(config)
    root = shlex.quote(deploy_cfg.remote_temp_root)
    return (
        "set -euo pipefail\n"
        f"root={root}\n"
        "mkdir -p \"$root\"\n"
        "dir=$(mktemp -d \"$root/clm-preflight.XXXXXX\")\n"
        f"{_safe_temp_cleanup_body()}\n"
        "safe_cleanup \"$dir\" \"$root\"\n"
    )


def _create_remote_workdir(host: str, temp_root: str, *, run_id: str, run_remote: RunRemote) -> str:
    safe_run_id = _safe_name(run_id) or "run"
    script = (
        "set -euo pipefail\n"
        f"root={shlex.quote(temp_root)}\n"
        "mkdir -p \"$root\"\n"
        f"mktemp -d \"$root/clm-{safe_run_id}.XXXXXX\"\n"
    )
    result = run_remote(host, script, check=True, capture=True)
    workdir = _last_nonempty_line(result.stdout or "")
    if not _is_safe_temp_child(workdir, temp_root):
        raise RuntimeError(f"remote tempdir is outside expected temp root: {workdir!r}")
    return workdir


def _copy_file_script(remote_path: str, data: bytes) -> str:
    encoded = base64.b64encode(data).decode("ascii")
    return (
        "set -euo pipefail\n"
        f"file={shlex.quote(remote_path)}\n"
        "mkdir -p \"$(dirname \"$file\")\"\n"
        "base64 -d > \"$file\" <<'CLM_ARTIFACT'\n"
        f"{encoded}\n"
        "CLM_ARTIFACT\n"
        "chmod 700 \"$file\"\n"
    )


def _safe_temp_cleanup_script(workdir: str, temp_root: str) -> str:
    return (
        "set -euo pipefail\n"
        f"dir={shlex.quote(workdir)}\n"
        f"root={shlex.quote(temp_root)}\n"
        f"{_safe_temp_cleanup_body()}\n"
        "safe_cleanup \"$dir\" \"$root\"\n"
    )


def _safe_temp_cleanup_body() -> str:
    return (
        "safe_cleanup() {\n"
        "  local dir=\"$1\" root=\"$2\" parent base\n"
        "  [ -n \"$dir\" ] && [ -n \"$root\" ] && [ \"$dir\" != / ]\n"
        "  parent=$(dirname \"$dir\")\n"
        "  base=$(basename \"$dir\")\n"
        "  [ \"$parent\" = \"$root\" ]\n"
        "  case \"$base\" in clm-*) rm -rf -- \"$dir\" ;; *) exit 64 ;; esac\n"
        "}\n"
    )


def _local_script_path(scripts_root: Path, name: str) -> Path:
    root = scripts_root.expanduser().resolve()
    candidate = (root / name).resolve()
    if root not in candidate.parents:
        raise FileNotFoundError(name)
    if not candidate.is_file():
        raise FileNotFoundError(name)
    return candidate


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _normalize_remote_root(value: str) -> str:
    text = str(value or DEFAULT_REMOTE_TEMP_ROOT).strip().rstrip("/")
    return text or DEFAULT_REMOTE_TEMP_ROOT


def _safe_name(value: str) -> str:
    return _SAFE_NAME_RE.sub("-", str(value or "")).strip("-._")


def _posix_join(*parts: str) -> str:
    clean = [str(part).strip("/") for part in parts if str(part).strip("/")]
    if not clean:
        return "/"
    prefix = "/" if str(parts[0]).startswith("/") else ""
    return prefix + "/".join(clean)


def _last_nonempty_line(text: str) -> str:
    for line in reversed(str(text or "").splitlines()):
        stripped = line.strip()
        if stripped:
            return stripped
    return ""


def _is_safe_temp_child(path: str, root: str) -> bool:
    root_norm = _normalize_remote_root(root)
    text = str(path or "").strip().rstrip("/")
    if not text.startswith(root_norm + "/"):
        return False
    name = text.rsplit("/", 1)[-1]
    return bool(name.startswith("clm-")) and name not in ("clm-", ".", "..")


def _as_bool(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)

