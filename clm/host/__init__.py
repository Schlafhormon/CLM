"""Host command execution primitives."""

from clm.host.deployment import (
    DEPLOYMENT_MODE_ARTIFACT,
    DEPLOYMENT_MODE_LEGACY_REPO,
    DeployedHostArtifacts,
    HostDeploymentConfig,
    baseline_reset_script_names,
    deploy_scripts,
    deployment_config_for,
    deployment_mode_for,
    migration_script_names,
    normalize_deployment_mode,
    preflight_tempdir_script,
    validate_local_scripts,
)
from clm.host.executor import CommandResult, HostExecutor, LocalExecutor, ProcessHandle, SshExecutor
from clm.host.shell import CommandBuilder, RemoteScript, ShellScript, render_env_exports, shell_quote

__all__ = [
    "CommandResult",
    "CommandBuilder",
    "DEPLOYMENT_MODE_ARTIFACT",
    "DEPLOYMENT_MODE_LEGACY_REPO",
    "DeployedHostArtifacts",
    "HostExecutor",
    "HostDeploymentConfig",
    "LocalExecutor",
    "ProcessHandle",
    "RemoteScript",
    "SshExecutor",
    "ShellScript",
    "baseline_reset_script_names",
    "deploy_scripts",
    "deployment_config_for",
    "deployment_mode_for",
    "migration_script_names",
    "normalize_deployment_mode",
    "preflight_tempdir_script",
    "render_env_exports",
    "shell_quote",
    "validate_local_scripts",
]
