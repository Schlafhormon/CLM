#!/usr/bin/env python3

import unittest
from copy import deepcopy

import clm.cli as cli
from clm.migration.storage import (
    CleanupPolicy,
    RsyncTransferBackend,
    SharedFilesystemBackend,
    artifact_paths_for,
    select_storage_backend,
    transfer_plan_for,
)
from clm.runtimes.runc import RuncBackend


class CleanupPolicyTests(unittest.TestCase):
    def test_safe_default_cleans_checkpoint_artifacts_only_after_success(self):
        policy = CleanupPolicy.from_config({})

        self.assertTrue(policy.allows_artifact_cleanup("shared", run_ok=True))
        self.assertTrue(policy.allows_artifact_cleanup("local", run_ok=True))
        self.assertFalse(policy.allows_artifact_cleanup("shared", run_ok=False))
        self.assertFalse(policy.allows_risky_action("destination_container_state"))
        self.assertFalse(policy.allows_risky_action("network_state"))

    def test_risky_cleanup_requires_explicit_opt_in(self):
        policy = CleanupPolicy.from_config(
            {
                "shared_images_policy": "always",
                "local_images_policy": "never",
                "explicit_risky_actions": ["destination_container_state"],
            }
        )

        self.assertTrue(policy.allows_artifact_cleanup("shared", run_ok=False))
        self.assertFalse(policy.allows_artifact_cleanup("local", run_ok=True))
        self.assertTrue(policy.allows_risky_action("destination_container_state"))
        self.assertFalse(policy.allows_risky_action("source_container_state"))

    def test_unknown_cleanup_policy_fails_closed(self):
        policy = CleanupPolicy(shared_images_policy="surprise", local_images_policy="success_only")

        self.assertFalse(policy.allows_artifact_cleanup("shared", run_ok=True))


class StorageBackendSelectionTests(unittest.TestCase):
    def test_default_storage_backend_is_shared_filesystem(self):
        cfg = deepcopy(cli.DEFAULTS)

        backend = select_storage_backend(cfg)
        transfer = transfer_plan_for(cfg, method="precopy", run_id="20260325_210000")

        self.assertIsInstance(backend, SharedFilesystemBackend)
        self.assertTrue(transfer.implemented)
        self.assertEqual(transfer.mode, "shared")
        self.assertEqual(transfer.source_root, "/mnt/criu")
        self.assertEqual(transfer.remote_root, "/mnt/criu")
        self.assertEqual(transfer.destination_root, "/var/lib/criu-local")
        self.assertEqual(transfer.precopy_image_mode, "shared")

    def test_local_copy_compatibility_stays_on_shared_backend(self):
        cfg = deepcopy(cli.DEFAULTS)
        cfg["precopy"]["image_mode"] = "local_copy"

        backend = select_storage_backend(cfg)
        transfer = transfer_plan_for(cfg, method="precopy", run_id="20260325_210001")

        self.assertIsInstance(backend, SharedFilesystemBackend)
        self.assertEqual(transfer.precopy_image_mode, "local_copy")
        self.assertFalse(transfer.restore_from_shared)

    def test_rsync_backend_is_selectable_but_not_executed_by_legacy_scripts(self):
        cfg = deepcopy(cli.DEFAULTS)
        cfg["storage"] = {"mode": "rsync", "source_root": "/srv/criu", "destination_root": "/var/tmp/clm"}

        backend = select_storage_backend(cfg)
        transfer = transfer_plan_for(cfg, method="precopy", run_id="20260325_210002")

        self.assertIsInstance(backend, RsyncTransferBackend)
        self.assertFalse(transfer.implemented)
        self.assertEqual(transfer.mode, "rsync")
        self.assertEqual(transfer.source_root, "/srv/criu")
        self.assertEqual(transfer.destination_root, "/var/tmp/clm")
        self.assertIn("legacy migration scripts do not execute it yet", transfer.warnings[0])

    def test_artifact_paths_use_configured_roots_instead_of_hardcoded_mnt_criu(self):
        cfg = deepcopy(cli.DEFAULTS)
        cfg["paths"]["share_root"] = "/srv/shared-criu"
        cfg["storage"] = {"destination_root": "/var/tmp/criu-cache"}
        cfg["container"]["name"] = "web"

        paths = artifact_paths_for(cfg, method="postcopy", run_id="20260325_210003")

        self.assertEqual(paths.checkpoint_name, "pcpost-20260325_210003")
        self.assertEqual(paths.shared_checkpoint_path, "/srv/shared-criu/runc/web/pcpost-20260325_210003")
        self.assertEqual(paths.destination_checkpoint_path, "/var/tmp/criu-cache/runc/web/pcpost-20260325_210003")

    def test_runc_legacy_script_uses_storage_transfer_plan_env(self):
        cfg = deepcopy(cli.DEFAULTS)
        cfg["paths"]["share_root"] = "/srv/shared-criu"
        cfg["paths"]["logs_root"] = "/srv/shared-criu/logs"
        cfg["storage"] = {"destination_root": "/var/tmp/criu-cache"}

        script = RuncBackend().build_legacy_migration_script(
            cfg,
            method="precopy",
            run_id="20260325_210004",
            events_log="/srv/shared-criu/logs/mon-20260325_210004-events.ndjson",
        )

        self.assertIn("export SRC_NFS_ROOT=/srv/shared-criu", script)
        self.assertIn("export REMOTE_NFS_ROOT=/srv/shared-criu", script)
        self.assertIn("export DST_LOCAL_ROOT=/var/tmp/criu-cache", script)

    def test_runc_migration_fails_fast_for_prepared_only_rsync_transfer(self):
        cfg = deepcopy(cli.DEFAULTS)
        cfg["storage"] = {"mode": "rsync"}

        result = RuncBackend().migrate(
            cfg,
            method="precopy",
            run_id="20260325_210005",
            events_log="/mnt/criu/logs/mon-20260325_210005-events.ndjson",
            migrate_log="/tmp/precopy.log",
        )

        self.assertEqual(result.status, "failed")
        self.assertEqual(result.artifacts["returncode"], 2)
        self.assertFalse(result.artifacts["transfer_implemented"])
        self.assertIn("legacy migration scripts do not execute it yet", result.errors[0])


if __name__ == "__main__":
    unittest.main()
