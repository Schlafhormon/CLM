# CLM

CLM is intended to become a practical Python orchestration tool for live
migration of containers with CRIU. The long-term goal is to migrate containers
running different kinds of applications across hosts with a simple operator
workflow, strong preflight checks, useful monitoring, and clear migration
artifacts.

The current codebase was extracted from a container live migration research
repository. It already contains working CRIU/runc migration orchestration,
monitoring, and analysis code, but it still carries assumptions from that
research environment. This repository is where CLM should evolve into a
standalone tool.

## Vision

CLM should provide a clean orchestration layer around CRIU:

- Support container live migration for multiple runtimes, not only `runc`.
  Docker, containerd, and Podman support are explicit future targets.
- Avoid requiring the full CLM repository to be checked out on every host.
  Source and destination hosts should eventually need only a small deployed
  helper, generated scripts, or a packaged runtime component.
- Keep CRIU as the migration engine while making the orchestration around it
  easier, safer, and faster.
- Improve pre-copy and post-copy migration paths, especially for containers
  under active load.
- Provide reliable preflight validation before touching a running container.
- Provide clear operational monitoring and diagnostics without forcing a
  research-style measurement campaign.
- Keep analysis useful, but simplify it toward operator-facing summaries,
  timelines, and troubleshooting output.
- Remove built-in workload simulation code from the core tool. Test workloads
  belong in examples or integration tests, not in the orchestration path.

CRIU itself may need upstream contributions or a dedicated fork for deeper
improvements. CLM should be designed so such CRIU-level work can be integrated
without coupling the whole project to one patched CRIU build.

## Current Status

CLM currently works as an extracted research tool:

- The implemented migration backend targets `runc`.
- The same repository path is expected to exist on monitor, source, and
  destination hosts.
- Pre-copy orchestration supports final dump, restore, VIP cutover, and
  cleanup.
- Post-copy orchestration supports CRIU lazy pages, destination readiness
  checks, optional source forwarding, warmup, VIP cutover, and cleanup.
- Monitoring records HTTP, L4 TCP, counters, info endpoints, streams,
  downloads, uploads, and latency-related data.
- Batch execution stores run metadata, status files, event logs, config
  snapshots, and per-run summaries.
- Analysis can generate metrics, summary statistics, downtime segments, and
  plots.
- Research load profiles and the Flask workload are still present as legacy
  artifacts and should be moved out of the core path over time.

## Direction

Near-term development should move CLM from "research runner" to "migration
orchestrator":

- Introduce runtime backends for `runc`, Docker, containerd, and later Podman.
- Split host orchestration, CRIU operations, network cutover, monitoring, and
  analysis into smaller modules with stable interfaces.
- Replace remote "repo must exist" assumptions with deployable host-side
  helpers or generated command bundles.
- Make preflight checks structured, machine-readable, and actionable.
- Reduce the default CLI to the common operator workflow: inspect, preflight,
  migrate, monitor, summarize.
- Move research workloads, synthetic load generation, and paper-oriented plots
  to examples, integration tests, or a separate research add-on.
- Keep raw artifact capture available for debugging, but make the normal
  result concise.
- Add dry-run plans for migrations and remote commands.
- Add integration tests around generated migration plans and backend behavior.

## Repository Layout

```text
clm/                         Python package and CLI implementation
clm.py                       Compatibility entry point
config/env.example.yaml      Host, path, VIP, migration, monitor, and load config
config/analysis.yaml         Default analysis and plot configuration
config/analysis_paper.yaml   Extended comparison plot configuration from research use
scripts/                     runc bundle, migration, cleanup, hostinfo, forensics scripts
tools/monitor/monitor.py     Runtime monitor and single-run analyzer
tools/analyze.py             Standalone batch analysis wrapper
tools/plots.py               Standalone plot wrapper
workload/flask_app/app.py    Legacy research workload, to be moved out later
tests/                       Unit tests for orchestration, batching, analysis, monitor logic
docs/                        Operational documentation copied from the research repo
```

Generated data is intentionally not part of this repository. Keep measurement
outputs under the configured `runs_root`, normally `/mnt/criu/runs`, or in
local ignored directories.

## Requirements

The current implementation runs against Linux hosts. Source and destination
hosts currently need:

- `runc`
- `criu`
- passwordless `sudo`
- key-based SSH access from the monitoring host
- shared storage, normally mounted at `/mnt/criu`
- tools such as `bash`, `curl`, `jq`, `rsync`, `iptables`, `conntrack`, and
  `arping`

The monitoring host needs:

- Python 3.9 or newer
- `wrk` only for the legacy `wrk1`, `wrk2`, and `wrk3` load profiles
- access to source and destination hosts over SSH

These requirements are expected to change as CLM gains packaged host helpers
and runtime backends beyond `runc`.

## Installation

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -e .
cp config/env.example.yaml config/env.yaml
```

Edit `config/env.yaml` for your lab:

- `repo_path`: path to this CLM checkout on all hosts, default `~/CLM`
- `hosts`: monitor, source, and destination SSH names and IPs
- `paths`: shared CRIU root, run root, and log root
- `traffic`: traffic backend, normally `external`, `command`, or legacy `vip`
- `vip`: legacy service VIP, CIDR, port, and host interfaces
- `container`: runc container name, image, bundle path, and Gunicorn sizing
- `migration`, `precopy`, `postcopy`: method-specific runtime settings
- `monitor`: probe intervals, timeouts, burst behavior, and target families
- `load`: legacy/example research workload profiles; omit `--load` for normal
  migrations

## Preflight

```bash
clm preflight --env config/env.yaml
```

For config parsing only:

```bash
clm preflight --env config/env.yaml --dry-run
```

Preflight checks local tooling, host reachability, shared paths, remote repo
state, and common runtime prerequisites.

## Running Migrations

Run one pre-copy migration:

```bash
clm run --env config/env.yaml --method precopy --repeats 1
```

This is the recommended path for ordinary migrations: no `--load` flag, no
synthetic workload generator, and only the configured migration plus monitoring
path.

Run a post-copy batch:

```bash
clm run --env config/env.yaml --method postcopy --repeats 10
```

Run selected legacy load profiles:

```bash
clm run --env config/env.yaml --method precopy --load idle --repeats 5
clm run --env config/env.yaml --method postcopy --load wrk2,download --repeats 5
clm run --env config/env.yaml --method postcopy --load stream --load upload
```

Supported legacy profiles are `idle`, `cpu`, `wrk1`, `wrk2`, `wrk3`,
`download`, `upload`, and `stream`. `heavy` is kept as a compatibility alias
for `cpu`. These profiles came from the research setup, depend on the Flask
example workload in `workload/flask_app/`, and are not intended to remain part
of the core orchestrator. New operator workflows should use app probes and
external traffic/load generation instead of CLM-managed synthetic profiles.
When `traffic.mode` is `external`, `command`, or `none`, CLM fails fast if a
legacy synthetic load profile resolves to `load.target: vip`.

Useful run switches:

```bash
clm run --env config/env.yaml --method precopy --repeats 10 --analyse
clm run --env config/env.yaml --method precopy --no-monitor
clm run --env config/env.yaml --method precopy --no-migrate
clm run --env config/env.yaml --method postcopy --no-cleanup
```

## Traffic Cutover

Traffic handling is configured under `traffic:`. Use `external` when traffic is
managed outside CLM, `command` for operator-provided hooks, or `vip` for the
existing lab-oriented VIP/GARP/conntrack behavior. See
[docs/traffic.md](docs/traffic.md) for examples and compatibility notes.

## Analysis

Analysis is currently batch-oriented and still reflects the research origin of
the tool. The target direction is a simpler operator-facing analysis layer:
summaries, downtime timelines, warnings, and links to raw artifacts when deeper
debugging is needed.

For the operator-facing success contract, including how to distinguish
successful, partially successful, and failed migrations from `status.json`,
`summary.json`, and `MigrationResult`, see
[docs/migration_success.md](docs/migration_success.md).

Analyze the newest batch:

```bash
clm analyse --env config/env.yaml --batch last
```

Analyze and generate plots:

```bash
clm analyse --env config/env.yaml --batch last --with-plots
```

Combine multiple recent batches:

```bash
clm analyse --env config/env.yaml --batch last:4 --combine-batches --with-plots
```

Generate plots from existing metrics:

```bash
clm plots --env config/env.yaml --batch last:4 --combine-batches
```

Standalone wrappers are still available:

```bash
python3 tools/analyze.py --batch last --config config/analysis.yaml
python3 tools/plots.py --batch last --config config/analysis.yaml
```

## Development

Run tests from the repository root:

```bash
python -m pytest
```

The current codebase is intentionally close to the extracted research tool.
Near-term hardening work should focus on:

- separating host orchestration, CRIU operations, network cutover, monitoring,
  and analysis into smaller modules;
- defining runtime backend interfaces for `runc`, Docker, containerd, and
  Podman;
- replacing script-string assembly with typed command builders where possible;
- removing the requirement that the whole repo exists on every target host;
- adding structured preflight result objects and machine-readable diagnostics;
- adding packaging metadata for optional analysis dependencies;
- adding integration tests around dry-run plans and generated remote scripts;
- defining stable extension points for migration strategies, runtime backends,
  network cutover modes, and monitors;
- moving synthetic load generation out of the core package.

## Documentation

Start with [docs/README.md](docs/README.md). The docs describe pre-copy and
post-copy workflows, shared storage, measurement hygiene, workload scenarios,
downtime segments, metric semantics, and the migration success contract.

## License

Code and scripts are licensed under the MIT License. Documentation copied from
the research repository is licensed under CC BY 4.0; see
[LICENSE-DOCS](LICENSE-DOCS). This standalone CLM repo does not include the
measurement datasets and generated paper plots from the research repository.
