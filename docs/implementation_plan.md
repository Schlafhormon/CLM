# CLM Implementation Plan

This document describes the implementation plan for turning CLM from an
extracted research runner into a full container live migration orchestration
tool based on CRIU.

It also contains contextless implementation prompts. Each prompt is written so
it can be started in a separate fresh chat inside this repository.

## Product Goal

CLM should become a Python-based orchestration tool for live migration of
containers with CRIU. It should support individual containers and groups of
containers, multiple runtimes, different host environments, optional traffic
cutover, extensible monitoring, and operator-friendly reporting.

The tool should optimize for a safe and robust default path. Lower downtime
strategies should be available, but initially treated as advanced or
experimental modes until the implementation and validation are mature.

## Target Capabilities

- Runtimes: `runc`, Docker, containerd.
- Container scope: single containers and container groups.
- Environments: bare-metal hosts, VM hosts, and Kubernetes-like environments.
- Privilege model: rootful and rootless containers where the runtime and CRIU
  allow it.
- Migration strategies: stop-and-copy, pre-copy, post-copy.
- Strategy selection: manual strategy selection and automatic selection.
- CRIU support: broad CRIU feature support, including custom CRIU builds.
- CRIU incompatibility behavior: fail fast with actionable diagnostics.
- Host execution: SSH first, temporary host agent/helper later.
- Remote code distribution: do not require the full CLM repo on every host in
  the long term.
- Storage and transfer: shared storage and CLM-managed transfer paths.
- Traffic handling: optional, configurable, external-first.
- Monitoring: downtime and timeline by default, custom probes optional.
- Analysis: separate package or module family, optional reports, no research
  batch workflow in the core path.
- Cleanup: automatic cleanup for safe artifacts after successful migration;
  explicit command/flag for risky cleanup.
- Packaging: pip first, possible container image later.

## Non-Goals For The First Refactor

- Building native integrations for every load balancer or service mesh.
- Solving every CRIU limitation in CLM itself.
- Guaranteeing rootless migration across all runtime/storage/network
  combinations.
- Keeping research load simulation as a core feature.
- Preserving every current CLI flag forever.
- Designing a full multi-user platform or central control plane.

## Architecture Direction

The current implementation puts too much behavior in `clm/cli.py` and relies
on shell scripts in `scripts/`. The first architectural goal is to introduce
stable boundaries without breaking the current behavior immediately.

Recommended target layout:

```text
clm/
  cli/
    main.py
    commands/
      inspect.py
      preflight.py
      plan.py
      migrate.py
      status.py
      cleanup.py
      analyze.py
  core/
    config.py
    models.py
    errors.py
    events.py
    artifacts.py
    result.py
  orchestration/
    coordinator.py
    executor.py
    preflight.py
    plan.py
    session.py
  host/
    local.py
    ssh.py
    agent.py
    bootstrap.py
  runtimes/
    base.py
    runc.py
    docker.py
    containerd.py
  criu/
    binary.py
    features.py
    options.py
    images.py
    stats.py
  migration/
    strategies/
      base.py
      stop_and_copy.py
      precopy.py
      postcopy.py
    storage/
      base.py
      shared_fs.py
      rsync.py
      stream.py
    traffic/
      base.py
      external.py
      command.py
      vip.py
    cleanup.py
  monitoring/
    probes.py
    collector.py
    timeline.py
    downtime.py
  analysis/
    summary.py
    reports.py
  legacy/
    scripts/
```

This layout does not need to be created all at once. The first refactor should
move code behind interfaces while preserving current tests and behavior.

## Core Concepts

Introduce explicit models early. Avoid passing loosely structured dictionaries
through all orchestration layers.

Important models:

- `HostRef`: host identity, SSH target, role, local/remote execution mode.
- `ContainerRef`: runtime, container identifier, namespace/project metadata.
- `ContainerGroupRef`: ordered or dependency-aware group of containers.
- `RuntimeRef`: runtime type, socket/API path, privilege mode.
- `CriuRef`: binary path, version, feature support, custom build metadata.
- `StoragePlan`: shared filesystem, rsync, stream, local copy, cleanup policy.
- `TrafficPlan`: external, command, VIP, later load balancer integrations.
- `ProbeSpec`: HTTP/TCP/command/custom probe definitions.
- `MigrationRequest`: user intent.
- `MigrationPlan`: dry-run executable plan without side effects.
- `MigrationSession`: runtime state for one migration execution.
- `MigrationResult`: status, timings, downtime, errors, artifacts.
- `PreflightResult`: structured checks, warnings, blockers.

## CLI Direction

The future CLI should be operator-oriented:

```bash
clm inspect --host host1 --runtime docker
clm preflight --config clm.yaml
clm plan --config clm.yaml
clm migrate --config clm.yaml
clm migrate --from host1 --to host2 --container app
clm status --migration <id>
clm cleanup --migration <id>
```

YAML should remain the canonical config source for non-trivial migrations.
Command-line arguments can override config values for quick one-off runs.

## Traffic Handling

Traffic handling is optional and should be represented as a plugin-like
backend. CLM should not assume VIP-based cutover in real environments.

Initial traffic backends:

- `external`: CLM performs migration and readiness verification, but traffic
  is controlled outside CLM.
- `command`: user-provided commands/hooks for prepare, switch, verify, and
  optional rollback.
- `vip`: the existing lab-oriented VIP/GARP/conntrack logic, isolated behind
  a backend interface.

Later traffic backends:

- HAProxy/NGINX/Envoy integrations.
- BGP/route announcement integrations.
- Kubernetes Service/EndpointSlice or ingress-oriented integrations.

If restore succeeds and traffic cutover fails, CLM should report the failure
clearly. It should not assume automatic traffic rollback unless a configured
traffic backend explicitly supports it.

## Migration Success Semantics

Default success condition:

- Container restore succeeded on the destination.
- Configured traffic handling succeeded, if enabled.

Optional success condition:

- Application readiness succeeded when an app probe is configured.

Failure behavior:

- Dump/transfer/restore failure should abort the migration.
- On abort before successful restore, CLM should try to keep or restore the
  original source container when configured.
- App readiness failure is only fatal if the user configured it as required.
- Traffic cutover failure after successful restore should be reported clearly;
  rollback is backend-specific and not assumed.

## Monitoring And Reporting

Core monitoring should focus on:

- downtime;
- ordered migration timeline;
- migration duration;
- per-phase timing;
- status and error messages;
- optional app probes.

The current rich analysis pipeline should move toward optional analysis
modules. Batch evaluation and research plots can be moved out of the core path.

Recommended default outputs:

- concise console summary;
- structured JSON result;
- event log;
- optional Markdown or HTML report;
- links/paths to raw artifacts.

## Phased Implementation Plan

### Phase 0: Stabilize The Extracted Repo

Goal: make the current extracted state explicit and stable.

Tasks:

- Keep tests green.
- Mark workload simulation and paper analysis as legacy.
- Keep `workload/` as a compatibility path until the legacy load CLI and tests
  can be moved safely; document `examples/flask-workload/` as the intended
  future example location.
- Add architecture docs.
- Add a high-level config schema draft.
- Add a compatibility policy for the current CLI.

### Phase 1: Split CLI From Core Logic

Goal: reduce `clm/cli.py` from a large behavior file into a command entry
point and orchestration calls.

Tasks:

- Create `clm/cli/` with `main.py` and command modules.
- Move config loading into `clm/core/config.py`.
- Move shared models into `clm/core/models.py`.
- Move command execution helpers into `clm/orchestration/executor.py` or
  `clm/host/`.
- Keep existing CLI behavior working through compatibility wrappers.
- Update tests to target new modules where appropriate.

### Phase 2: Introduce Host Execution Abstractions

Goal: prepare for "repo not required on every host".

Tasks:

- Add `HostExecutor` interface.
- Implement `LocalExecutor`.
- Implement `SshExecutor`.
- Add command result objects with stdout, stderr, exit code, duration, and
  sanitized command metadata.
- Add remote working directory handling.
- Add dry-run rendering for remote commands.
- Keep existing script invocation working through a legacy adapter.

### Phase 3: Introduce Runtime Backend Interfaces

Goal: make `runc` the first backend instead of the whole product model.

Tasks:

- Add `RuntimeBackend` interface.
- Implement `RuncBackend` using current behavior.
- Add placeholder interfaces for Docker and containerd with preflight-only
  checks first.
- Add runtime inspection result models.
- Move runc-specific bundle/checkpoint/restore behavior behind the backend.
- Add tests for backend selection and fail-fast unsupported operations.

### Phase 4: Introduce Migration Strategies

Goal: separate strategy logic from runtime and CLI.

Tasks:

- Add `MigrationStrategy` interface.
- Implement stop-and-copy, pre-copy, and post-copy strategy skeletons.
- Wire existing runc shell-script behavior through strategy adapters first.
- Add automatic strategy selection with conservative defaults.
- Add manual strategy override.
- Add migration plan generation for dry runs.

### Phase 5: Storage And Transfer Backends

Goal: make shared storage optional.

Tasks:

- Add `StorageBackend` or `TransferBackend` interface.
- Implement shared filesystem mode using current `/mnt/criu` assumptions.
- Implement rsync transfer mode.
- Add plan-time validation of available storage/transfer modes.
- Add cleanup policy models and cleanup commands.
- Make cleanup safe by default after successful migration.

### Phase 6: Traffic Backends

Goal: remove VIP as a core assumption.

Tasks:

- Add `TrafficBackend` interface.
- Implement `ExternalTrafficBackend`.
- Implement `CommandTrafficBackend`.
- Move current VIP logic into `VipTrafficBackend`.
- Add traffic preflight and verify semantics.
- Add explicit behavior for restore success with traffic failure.

### Phase 7: Monitoring And Probe Refactor

Goal: make monitoring useful for operators and extensible for apps.

Tasks:

- Define probe config model.
- Support HTTP, TCP, and command probes.
- Make downtime and timeline core outputs.
- Keep heavier stream/download/upload monitoring as legacy or optional.
- Add custom probe result handling.
- Add JSON event stream as stable output.

### Phase 8: Analysis Package Split

Goal: remove research batch analysis from the core migration path.

Tasks:

- Keep concise migration summaries in `clm`.
- Move advanced plots and batch analysis into optional modules or separate
  package namespace.
- Remove workload-specific assumptions from default analysis.
- Add optional report generation.
- Keep raw artifact parsing available for troubleshooting.
- Treat `clm.analysis.summary` as the core-facing API for duration, downtime,
  status, errors, and artifact paths.
- Treat batch evaluation, summary statistics, paper views, and plot generation
  as advanced optional analysis features, not as required CLM core behavior.

### Phase 9: Packaging And Deployment

Goal: make CLM installable and usable outside the development checkout.

Tasks:

- Ensure pip installation works cleanly.
- Define optional extras such as `analysis`, `plots`, `docker`, `containerd`.
- Create a minimal temporary host helper deployment flow.
- Add version/preflight validation between controller and helper.
- Evaluate container image packaging for controller-only usage.

## Implementation Prompts

Each prompt below is intended for a fresh, contextless chat started in this
repository.

### Prompt 1: Architecture Baseline And Module Map

```text
Du bist im CLM Repo. Analysiere die aktuelle Codebasis ausfuehrlich, besonders `clm/cli.py`, `clm/analysis_pipeline.py`, `tools/monitor/monitor.py`, `scripts/`, `config/` und `tests/`.

Ziel: Erstelle eine Architektur-Baseline als Markdown-Datei unter `docs/architecture_baseline.md`.

Die Datei soll enthalten:
- aktuelle Modul-/Dateistruktur und Verantwortlichkeiten;
- welche Teile Runtime-spezifisch fuer runc sind;
- welche Teile Forschungs-/Legacy-Anteile sind;
- welche Teile fuer ein produktives CLM-Core bleiben sollten;
- konkrete Risiken im aktuellen Aufbau;
- eine vorgeschlagene Zielstruktur mit Begruendung.

Nimm keine grossen Codeaenderungen vor. Nur Dokumentation. Fuehre am Ende `git status --short` aus und fasse die geaenderten Dateien zusammen.
```

### Prompt 2: Core Models And Config Draft

```text
Du bist im CLM Repo. Lies `docs/implementation_plan.md`, `README.md`, `clm/cli.py`, `config/env.example.yaml` und die Tests.

Ziel: Fuehre erste Core-Modelle und einen Config-Draft ein, ohne das bestehende CLI-Verhalten zu brechen.

Aufgaben:
- Lege `clm/core/` an.
- Erstelle `clm/core/models.py` mit Dataclasses fuer HostRef, ContainerRef, ContainerGroupRef, RuntimeRef, CriuRef, StoragePlan, TrafficPlan, ProbeSpec, MigrationRequest, MigrationPlan, MigrationResult und PreflightResult.
- Erstelle `clm/core/config.py` mit Hilfsfunktionen, die die bestehende YAML-Struktur weiterhin laden koennen, aber intern erste Core-Modelle ableiten.
- Ergaenze fokussierte Unit-Tests fuer die neuen Modelle und Config-Hilfen.
- Aendere bestehendes Verhalten nur minimal und nur wenn Tests es erfordern.

Verifikation:
- Fuehre `python -m pytest` aus.
- Gib eine knappe Zusammenfassung der neuen Dateien, offenen Modellluecken und Testergebnisse.
```

### Prompt 3: Split CLI Entry Point

```text
Du bist im CLM Repo. Lies `docs/implementation_plan.md`, `clm/cli.py` und alle CLI-bezogenen Tests.

Ziel: Beginne die Zerlegung von `clm/cli.py`, ohne die bestehende CLI zu brechen.

Aufgaben:
- Lege `clm/cli/` mit `main.py` und `commands/` an.
- Verschiebe zuerst nur Argumentparser-Aufbau und Command-Dispatch in die neue Struktur.
- Lasse die bestehenden Implementierungsfunktionen vorerst in `clm/cli.py` oder importiere sie als Legacy-Funktionen, wenn das risikoaermer ist.
- Sorge dafuer, dass `pyproject.toml` weiterhin `clm = "clm.cli:main"` oder eine kompatible Alternative nutzt.
- Erhalte `python clm.py ...` als Kompatibilitaetsweg.
- Passe Tests nur an, wenn sie direkt den neuen Aufbau pruefen sollten.

Verifikation:
- Fuehre `python -m pytest` aus.
- Fuehre `python -m clm.cli --help` nur aus, falls die Paketstruktur das zulaesst; sonst erklaere kurz warum nicht.
- Fasse die Struktur, Kompatibilitaetsentscheidungen und Testergebnisse zusammen.
```

### Prompt 4: Host Executor Abstraction

```text
Du bist im CLM Repo. Lies `docs/implementation_plan.md`, `clm/cli.py`, besonders `run_local`, `run_shell_local`, `run_remote`, `_run_local_streamed` und `_run_remote_streamed`, sowie die Tests.

Ziel: Fuehre eine Host-Ausfuehrungsabstraktion ein, als Grundlage dafuer, dass spaeter nicht mehr das ganze Repo auf allen Hosts liegen muss.

Aufgaben:
- Lege `clm/host/` an.
- Definiere `CommandResult`, `HostExecutor`, `LocalExecutor` und `SshExecutor`.
- Unterstuetze capture/non-capture, exit code, stdout, stderr, Dauer und eine sichere String-Darstellung fuer Logs.
- Implementiere keine destruktiven Remote-Aenderungen.
- Ersetze bestehende CLI-Helfer nur schrittweise oder fuege Adapter hinzu, damit vorhandene Tests stabil bleiben.
- Ergaenze Unit-Tests fuer LocalExecutor und fuer SshExecutor-Command-Aufbau ohne echte SSH-Verbindung.

Verifikation:
- Fuehre `python -m pytest` aus.
- Dokumentiere, welche alten Funktionen noch Legacy sind.
```

### Prompt 5: Runtime Backend Interface And Runc Backend

```text
Du bist im CLM Repo. Lies `docs/implementation_plan.md`, `clm/cli.py`, `scripts/migrate_precopy_vip_cutover.sh`, `scripts/migrate_postcopy_lazy_pages_vip_cutover.sh`, `scripts/build_runc_bundle_from_docker_image.sh` und die Tests.

Ziel: Fuehre Runtime-Backend-Grenzen ein, mit runc als erstem Backend.

Aufgaben:
- Lege `clm/runtimes/` an.
- Definiere `RuntimeBackend` in `base.py`.
- Implementiere `RuncBackend` als Adapter um das aktuelle Verhalten, ohne die Migration komplett neu zu schreiben.
- Erstelle DockerBackend und ContainerdBackend als explizite Platzhalter mit Preflight-/Inspect-Skeleton und fail-fast fuer nicht implementierte Migration.
- Baue Backend-Auswahl aus Config oder RuntimeRef.
- Ergaenze Tests fuer Backend-Auswahl, runc Default und fail-fast bei nicht implementierten Backends.

Verifikation:
- Fuehre `python -m pytest` aus.
- Fasse zusammen, welche runc-Logik noch in Legacy-Skripten steckt.
```

### Prompt 6: Migration Strategy Interface

```text
Du bist im CLM Repo. Lies `docs/implementation_plan.md`, `clm/cli.py`, `clm/core/models.py` falls vorhanden, und die Migrationstests.

Ziel: Fuehre eine Strategy-Schicht fuer stop-and-copy, pre-copy und post-copy ein.

Aufgaben:
- Lege `clm/migration/strategies/` an.
- Definiere `MigrationStrategy` mit `plan`, `preflight` und `run`.
- Implementiere Skeletons fuer StopAndCopyStrategy, PreCopyStrategy und PostCopyStrategy.
- Verdrahte bestehende pre-copy/post-copy Ausfuehrung als LegacyAdapterStrategy, falls eine direkte Migration zu riskant ist.
- Implementiere konservative automatische Strategieauswahl: sicherer Default, minimal-downtime nur bei expliziter Auswahl oder experimentellem Flag.
- Ergaenze Dry-run/Plan-Objekte, wenn Core-Modelle vorhanden sind.
- Ergaenze Tests fuer manuelle und automatische Strategieauswahl.

Verifikation:
- Fuehre `python -m pytest` aus.
- Beschreibe, welche Teile noch nicht produktiv implementiert sind.
```

### Prompt 7: Traffic Backend Refactor

```text
Du bist im CLM Repo. Lies `docs/implementation_plan.md`, `clm/cli.py`, VIP-bezogene Stellen in `scripts/`, `config/env.example.yaml` und die Tests.

Ziel: Kapsele Traffic-Umschaltung als Backend und entferne VIP als Kernannahme.

Aufgaben:
- Lege `clm/migration/traffic/` an.
- Definiere `TrafficBackend` mit `preflight`, `prepare`, `switch`, `verify` und optional `rollback`.
- Implementiere `ExternalTrafficBackend`: keine Umschaltung, nur optional verify.
- Implementiere `CommandTrafficBackend`: Hooks fuer prepare/switch/verify/rollback, aber mit sicherer Config und klaren Logs.
- Implementiere `VipTrafficBackend` als Adapter fuer bestehende VIP-Logik.
- Fuehre eine neue Config-Sektion `traffic:` ein, halte aber alte `vip:` Config kompatibel.
- Ergaenze Tests fuer external, command und VIP-Kompatibilitaet.

Verifikation:
- Fuehre `python -m pytest` aus.
- Dokumentiere kurz die neue Traffic-Config in README oder `docs/traffic.md`.
```

### Prompt 8: Storage And Cleanup Abstraction

```text
Du bist im CLM Repo. Lies `docs/implementation_plan.md`, `clm/cli.py`, cleanup-bezogene Funktionen, `scripts/`, `config/env.example.yaml` und Tests.

Ziel: Erstelle eine klare Storage-/Transfer- und Cleanup-Abstraktion.

Aufgaben:
- Lege `clm/migration/storage/` an.
- Definiere Storage/Transfer-Backends fuer shared filesystem und rsync.
- Modellieren CleanupPolicy mit safe default: erfolgreiche Migration bereinigt sichere Artefakte, riskante Cleanup-Aktionen nur explizit.
- Kapsle aktuelle shared `/mnt/criu` Annahmen.
- Ergaenze Tests fuer CleanupPolicy und Backend-Auswahl.
- Brich bestehende CLI nicht.

Verifikation:
- Fuehre `python -m pytest` aus.
- Fasse zusammen, welche Transferwege real implementiert und welche nur vorbereitet sind.
```

### Prompt 9: Monitoring And Probe Model

```text
Du bist im CLM Repo. Lies `docs/implementation_plan.md`, `tools/monitor/monitor.py`, `clm/cli.py`, `config/env.example.yaml` und monitorbezogene Tests.

Ziel: Definiere ein schlankes, operator-orientiertes Monitoring- und Probe-Modell.

Aufgaben:
- Lege `clm/monitoring/` an.
- Definiere ProbeSpec fuer HTTP, TCP und command probes.
- Trenne Core-Monitoring fuer downtime/timeline von Legacy-Forschungsmonitoring fuer stream/download/upload.
- Fuehre stabile Event- und Result-Strukturen fuer Probe-Ergebnisse ein.
- Bestehenden Monitor erstmal nicht komplett neu schreiben; stattdessen Adapter oder Parser einziehen.
- Ergaenze Tests fuer ProbeSpec-Parsing und required/optional App-Readiness.

Verifikation:
- Fuehre `python -m pytest` aus.
- Dokumentiere, welche Monitoring-Funktionen Core sind und welche Legacy/optional werden sollen.
```

### Prompt 10: Analysis Split Plan And First Extraction

```text
Du bist im CLM Repo. Lies `docs/implementation_plan.md`, `clm/analysis_pipeline.py`, `tools/analyze.py`, `tools/plots.py`, `config/analysis.yaml`, `config/analysis_paper.yaml` und die Analysis-Tests.

Ziel: Bereite die Trennung von Core-Summary und optionaler Analyse vor.

Aufgaben:
- Lege `clm/analysis/` an.
- Verschiebe oder wrappe `analysis_pipeline.py` so, dass bestehende Imports weiter funktionieren.
- Definiere ein kleines Core-Summary-Modul fuer Dauer, Downtime, Status, Fehler und Artefaktpfade.
- Markiere Batch-/Plot-orientierte Funktionen als advanced/optional, ohne sie zu loeschen.
- Aktualisiere Doku, dass Batchauswertung perspektivisch aus dem Core raus soll.
- Ergaenze Tests fuer Core-Summary-Funktionen.

Verifikation:
- Fuehre `python -m pytest` aus.
- Fasse Kompatibilitaet und offene Split-Schritte zusammen.
```

### Prompt 11: New CLI Config Schema Draft

```text
Du bist im CLM Repo. Lies `docs/implementation_plan.md`, `config/env.example.yaml`, README und alle neuen Core-/Traffic-/Runtime-Modelle, falls vorhanden.

Ziel: Entwerfe eine neue v1 Config-Datei fuer das zukuenftige CLM, ohne die alte Config zu entfernen.

Aufgaben:
- Erstelle `config/clm.example.yaml`.
- Die Config soll source/destination, runtime, container oder container_group, criu, strategy, storage, traffic, probes, cleanup und output abbilden.
- Beruecksichtige rootful/rootless, custom CRIU binary/build, external traffic, command traffic und shared/rsync storage.
- Ergaenze `docs/configuration.md` mit Erklaerung der wichtigsten Felder.
- Implementiere nur leichte Parser-/Validierungshelfer, wenn passende Core-Modelle schon existieren. Ansonsten nur Doku und Beispiel.

Verifikation:
- Falls Code geaendert wurde: `python -m pytest`.
- Fasse offene Schemaentscheidungen zusammen.
```

### Prompt 12: Remove Research Load From Core Path

```text
Du bist im CLM Repo. Lies `docs/implementation_plan.md`, README, `workload/`, load-bezogene Stellen in `clm/cli.py`, `config/env.example.yaml` und Tests.

Ziel: Bereite die Entfernung der Forschungslastsimulation aus dem Core vor, ohne bestehende Kompatibilitaet hart zu brechen.

Aufgaben:
- Markiere `workload/` und synthetische load profiles als legacy/example.
- Verschiebe nichts riskant, wenn dadurch viele Tests brechen; beginne mit klarer Doku und Config-Kompatibilitaet.
- Falls sinnvoll, lege `examples/flask-workload/` an und plane die spaetere Verschiebung.
- Sorge dafuer, dass normale Migration ohne Load-Profil der empfohlene Pfad ist.
- Aktualisiere README und docs.
- Ergaenze Tests, falls sich Parsing/Default-Verhalten aendert.

Verifikation:
- Fuehre `python -m pytest` aus.
- Fasse zusammen, was noch im Core haengt.
```

### Review Prompt

```text
Du bist im CLM Repo. Fuehre ein strenges Architektur- und Code-Review der aktuellen Aenderungen durch.

Ziel: Pruefe, ob die Umsetzung zum Ziel passt, CLM zu einem vollwertigen CRIU-basierten Container-Live-Migrationstool weiterzuentwickeln.

Pruefe besonders:
- Ist `clm/cli.py` kleiner geworden oder gibt es einen realistischen Weg dahin?
- Sind Core-Modelle klar und nicht zu stark an runc/Forschung gekoppelt?
- Sind Runtime, Strategy, Storage, Traffic, Host Execution, Monitoring und Analysis sauber getrennt?
- Bleibt bestehendes Verhalten kompatibel?
- Sind VIP und Forschungslastsimulation nicht mehr Kernannahmen?
- Gibt es fail-fast Verhalten fuer nicht unterstuetzte Runtime-/CRIU-Kombinationen?
- Sind Tests aussagekraeftig und ausreichend?
- Gibt es riskante Remote-/Shell-Ausfuehrung ohne saubere Abstraktion?
- Gibt es Doku fuer neue Config, Traffic-Modi und Migrationserfolg?

Arbeite im Review-Stil:
- Findings zuerst, nach Schwere sortiert.
- Mit Datei- und Zeilenreferenzen.
- Kleine, eindeutig sichere Fixes direkt umsetzen.
- Keine grossen oder riskanten Fixes direkt umsetzen. Dazu zaehlen
  Architekturentscheidungen, API-/Config-Aenderungen, Remote-Ausfuehrungslogik,
  Migrationsverhalten, Cleanup-Verhalten, Security-/Secret-Handling,
  Runtime-Backend-Semantik und alles, was bestehende Nutzer-Workflows brechen
  koennte. Solche Punkte als Findings mit konkreter Fix-Empfehlung melden.
- Wenn du kleine Fixes umgesetzt hast, danach erneut gezielt pruefen und die
  geaenderten Dateien separat im Ergebnis nennen.
- Fuehre `python -m pytest` aus, wenn praktikabel.
- Schliesse mit einer priorisierten Fix-Liste fuer alle nicht direkt
  behobenen Findings.
```
