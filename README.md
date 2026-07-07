# CLM

CLM is a Python-based orchestration tool for container live migration with
CRIU and runc. It coordinates source, destination, and monitoring hosts,
executes pre-copy and post-copy migrations, records client-visible behavior,
and analyzes the resulting run artifacts.

This repository is the standalone continuation of the CLM tool. It was split
out of the broader `ContainerLiveMigration` research repository so CLM can
evolve as an operational CRIU orchestration project without carrying paper
results, historical archives, or local measurement data.

## Current Scope

- Pre-copy migration orchestration with final dump, restore, VIP cutover, and
  cleanup.
- Post-copy migration orchestration with CRIU lazy pages, destination
  readiness checks, optional source forwarding, warmup, VIP cutover, and
  cleanup.
- External monitoring for HTTP, L4 TCP, counters, info endpoints, streams,
  downloads, uploads, and workload latency.
- Repeatable batches with run metadata, status files, event logs, config
  snapshots, and per-run summaries.
- Batch analysis and plot generation for downtime, latency, transfer, stream,
  download, and upload metrics.
- A small Flask workload used to exercise migrated services.

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
workload/flask_app/app.py    Test workload used by the migration scripts
tests/                       Unit tests for orchestration, batching, analysis, monitor logic
docs/                        Operational documentation copied from the research repo
```

Generated data is intentionally not part of this repository. Keep measurement
outputs under the configured `runs_root`, normally `/mnt/criu/runs`, or in
local ignored directories.

## Requirements

The orchestration runs against Linux hosts. Source and destination hosts need:

- `runc`
- `criu`
- passwordless `sudo`
- key-based SSH access from the monitoring host
- shared storage, normally mounted at `/mnt/criu`
- tools such as `bash`, `curl`, `jq`, `rsync`, `iptables`, `conntrack`, and
  `arping`

The monitoring host needs:

- Python 3.9 or newer
- `wrk` for the `wrk1`, `wrk2`, and `wrk3` load profiles
- access to source and destination hosts over SSH

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
- `vip`: service VIP, CIDR, port, and host interfaces
- `container`: runc container name, image, bundle path, and Gunicorn sizing
- `migration`, `precopy`, `postcopy`: method-specific runtime settings
- `monitor`: probe intervals, timeouts, burst behavior, and target families
- `load`: workload profiles

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

Run a post-copy batch:

```bash
clm run --env config/env.yaml --method postcopy --repeats 10
```

Run selected load profiles:

```bash
clm run --env config/env.yaml --method precopy --load idle --repeats 5
clm run --env config/env.yaml --method postcopy --load wrk2,download --repeats 5
clm run --env config/env.yaml --method postcopy --load stream --load upload
```

Supported profiles are `idle`, `cpu`, `wrk1`, `wrk2`, `wrk3`, `download`,
`upload`, and `stream`. `heavy` is kept as a compatibility alias for `cpu`.

Useful run switches:

```bash
clm run --env config/env.yaml --method precopy --repeats 10 --analyse
clm run --env config/env.yaml --method precopy --no-monitor
clm run --env config/env.yaml --method precopy --no-migrate
clm run --env config/env.yaml --method postcopy --no-cleanup
```

## Analysis

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
- replacing script-string assembly with typed command builders where possible;
- adding structured preflight result objects and machine-readable diagnostics;
- adding packaging metadata for optional analysis dependencies;
- adding integration tests around dry-run plans and generated remote scripts;
- defining stable extension points for new migration strategies and monitors.

## Documentation

Start with [docs/README.md](docs/README.md). The docs describe pre-copy and
post-copy workflows, shared storage, measurement hygiene, workload scenarios,
downtime segments, and metric semantics.

## License

Code and scripts are licensed under the MIT License. Documentation copied from
the research repository is licensed under CC BY 4.0; see
[LICENSE-DOCS](LICENSE-DOCS). This standalone CLM repo does not include the
measurement datasets and generated paper plots from the research repository.
