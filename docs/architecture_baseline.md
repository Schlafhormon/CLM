# Architektur-Baseline

Stand: 2026-07-08

Diese Baseline beschreibt den aktuellen Ist-Zustand des CLM-Repositories. Sie ist
als Orientierung fuer die naechste Zerlegung des aktuellen Forschungs-Runners in
ein produktives CLM-Core gedacht.

## Aktueller Nachtrag 2026-07-08

Seit der ersten Baseline wurden mehrere Schichten angelegt, aber nicht alle
Legacy-Pfade entfernt:

- `clm/core/` enthaelt typed Config- und Modellhelfer. Diese Module duerfen
  keine Runtime-, Monitoring- oder direkten CLI-Legacy-Module importieren. Die
  bekannte Uebergangsstelle ist `legacy_defaults()`, das die historische
  `clm.cli`-Facade nutzt, solange die Defaults noch im Legacy-Runner liegen.
- `clm/runtimes/` enthaelt Backend-Interfaces und Skeletons fuer `runc`,
  `docker` und `containerd`. Nur `runc` kann aktuell Migration ausfuehren;
  Docker/containerd muessen in `clm run` vor Baseline-Cleanup, Source-Reset,
  Monitor, Load und Migration scheitern.
- `clm/migration/storage/`, `clm/migration/traffic/` und
  `clm/migration/strategies/` kapseln Teile der frueheren CLI-Logik. Die
  implementierte Migration delegiert aber weiterhin an runc/CRIU-Bash-Skripte.
- `clm/host/` ist die neue Host-Execution-Grenze. Die alten Patch-Punkte in
  `clm.cli` bleiben als Kompatibilitaetsadapter bestehen.
- `clm/monitoring/` und `clm/analysis/` trennen Core-Modelle und
  operatornahe Summary von Legacy-Monitoring, Forschungsmetriken und Plots.

Diese Grenzen werden durch fokussierte Architektur-/Contract-Tests abgesichert:
Core-Importgrenzen, `clm run`-Capability-Gates, Traffic-Mode-Script-Env,
Bash-`TRAFFIC_MODE`-Branches und die Groesse der `clm.cli`-Facade.

## Kurzfazit

CLM ist aktuell ein funktionsfaehiger, aber weiterhin stark runc- und
Labor-spezifischer Runner fuer CRIU-basierte Container-Live-Migration. Die
Kernfunktionalitaet wurde teilweise aufgeteilt:

- `clm/cli/legacy_run.py` orchestriert noch den bestehenden Forschungs-Run:
  Config, Preflight, Remote-Kommandos, Monitoring, synthetische Last, Migration,
  Cleanup, Batch-Artefakte und Analyse-Aufruf.
- `clm/cli/__init__.py` ist eine kleine Kompatibilitaets-Facade fuer historische
  `clm.cli`-Imports und Test-Patch-Punkte.
- `scripts/` enthaelt weiterhin den eigentlichen runc/CRIU-Migrationsablauf als
  Bash. Die neuen `traffic.mode`-Branches verhindern VIP-Operationen in
  `external` und `command`, aber die VIP-Funktionen bleiben im Skript.
- `tools/monitor/monitor.py` bleibt Laufzeit-Monitor und CLI-kompatibler
  Analyzer-Wrapper; Analysefunktionen sind nach `clm.monitoring.analysis`
  gespiegelt.
- `clm/analysis_pipeline.py` bleibt als schwere Forschungs-/Auswertungspipeline
  import-kompatibel; `clm.analysis.summary` ist der core-naehere Einstieg.

Das produktive CLM-Core sollte daraus die stabilen Operator-Pfade behalten:
Konfiguration, Preflight, Migrationsplan, Runtime-Backend, Remote-Ausfuehrung,
Artefaktmodell, Monitoring und kompakte Diagnose. Forschungs-Workloads,
Paper-Plots und laborspezifische Skriptannahmen sollten aus dem Core heraus
verschoben oder als optionale Add-ons gekapselt werden.

## Aktuelle Modul- und Dateistruktur

```text
clm/
  __init__.py
  batching.py
  cli/
    __init__.py
    __main__.py
    main.py
    commands/
    legacy_*.py
  core/
  host/
  runtimes/
  migration/
    storage/
    strategies/
    traffic/
  monitoring/
  analysis/
  analysis_pipeline.py
clm.py
config/
  env.example.yaml
  analysis.yaml
  analysis_paper.yaml
scripts/
  build_runc_bundle_from_docker_image.sh
  patch_runc_bundle_for_criu.sh
  restore_runc_bundle_baseline.sh
  migrate_precopy_vip_cutover.sh
  migrate_postcopy_lazy_pages_vip_cutover.sh
  collect_hostinfo_*.sh
  collect_downtime_forensics_monitor.sh
tools/
  analyze.py
  plots.py
  monitor/monitor.py
tests/
  test_batching.py
  test_analysis_pipeline.py
  test_cli_load_profiles.py
  test_cli_preflight_repo_sync.py
  test_cli_progress.py
  test_cli_run_migration.py
  test_monitor_downtime_semantics.py
workload/flask_app/
docs/
```

### `clm/cli/legacy_run.py` und `clm/cli/__init__.py`

Verantwortlichkeiten:

- CLI mit Subcommands `preflight`, `run`, `analyse`/`analyze` und `plots`.
- Default-Konfiguration und `env.yaml`-Loading mit Deep-Merge.
- Host-/Pfad-/VIP-/Postcopy-/Load-Konfiguration.
- Lokale und remote Ausfuehrung ueber `subprocess`, `bash -lc` und `ssh`.
- Terminal-Progress und Streaming von Remote-Output.
- Preflight: Repo-Sync, SSH, NFS, Tooling, sudo, Ports und `criu check --all`.
- Monitor-Command-Aufbau fuer `tools/monitor/monitor.py`.
- Synthetische Lastprofile: `cpu`, `wrk`, `wrk1..3`, `download`, `upload`,
  `stream`.
- Batch-Run-Orchestrierung inklusive Run-Verzeichnissen, Statusdateien,
  Config-Snapshots, Event-Logs, Cleanup und optionaler Auto-Analyse.
- runc-spezifisches Reset/Cleanup von Source/Destination.
- Start der eigentlichen Migration durch Remote-Ausfuehrung der Bash-Skripte.
- Single-Run-Analyse durch Aufruf des Monitor-Analyzers.

Bewertung:

- `legacy_run.py` ist derzeit der zentrale Integrationspunkt und enthaelt
  mehrere unterschiedliche Domaenen in einer Datei.
- `clm/cli/__init__.py` ist bewusst nur eine kleine Facade, die historische
  `clm.cli`-Imports und Patch-Punkte stabil haelt.
- Viele Schnittstellen sind implizit: Shell-Env-Variablen, Dateipfade,
  Eventnamen, Summary-Felder und Lognamen.
- Die Tests stabilisieren einzelne Helfer und Script-Env-Generierung, aber kein
  klar abgegrenztes internes Orchestrierungsmodell.

### `clm/batching.py`

Verantwortlichkeiten:

- Batch-ID-Erzeugung und Batch-Verzeichnislayout unter `<runs_root>/batches`.
- Batch-Selectoren `last`, `last:N` und explizite Batch-Pfade.
- Manifest-Aufloesung fuer mehrere Batches.
- JSON-Helfer, Git-Commit-Best-Effort und Host-Metadaten.
- Legacy-Kompatibilitaetslink von altem Run-Pfad auf neue Batch-Struktur.

Bewertung:

- Relativ klar abgegrenzt und fuer ein Core brauchbar.
- `discover_run_dirs` ist in `clm/analysis_pipeline.py` teilweise dupliziert.
- Legacy-Link ist sinnvoll als Uebergangsschicht, sollte aber langfristig klar
  markiert bleiben.

### `clm/analysis_pipeline.py`

Verantwortlichkeiten:

- Analysis-Config-Loading inklusive `extends` und Extra-Plot-Definitionen.
- Run-Discovery und Summary-Ingest.
- Flattening von Summary-Feldern zu `metrics.csv`.
- Ableitung von Metriken und Exclude-Regeln.
- Downtime-Segment-Rekonstruktion und Normalisierung.
- Statistik mit Mean/Median/CI und Bootstrap-Helfern.
- Umfangreiche Plot-Erzeugung: Box, Histogramm, Scatter, Violin, Median-CI,
  Downtime-Segmentplots und Probe-State-Timelines.
- Combined-Analysis ueber mehrere Batch-Targets.

Bewertung:

- Funktional wertvoll, aber klar analyse-/forschungsgetrieben.
- Enthaelt Logik, die teilweise auch in `tools/monitor/monitor.py` vorkommt,
  insbesondere Downtime-Breakdown-Phasen.
- Fuer ein Produkt-Core sollte nur ein schlanker Ingest-/Summary-Teil bleiben;
  Statistik und Paper-/Plot-Funktionen sollten optional sein.

### `tools/monitor/monitor.py`

Verantwortlichkeiten:

- Multi-Target-Monitoring fuer HTTP, L4/TCP, Info, Counter, Stream, Download
  und Upload.
- Rotierende Logwriter fuer CSV/NDJSON.
- Burst-Sampling anhand von Event-Log-Triggern.
- Legacy Single-URL-Modus.
- Analysemodus fuer einen Run: CSV/NDJSON lesen, Event-Zeiten in Monitor-Clock
  umrechnen, Downtime-Metriken berechnen, Latenzen/Transfers/Streams
  aggregieren und JSON-Summary ausgeben.

Bewertung:

- Monitor und Analyzer sind in einer grossen Datei gekoppelt.
- Die Datei enthaelt produktnahe Funktionen (Probe-Sampling, rotierende Logs)
  und forschungsnahe Auswertung (Downtime-Semantik, Segment-Breakdown) zugleich.
- Die Eventnamen und Summary-Felder sind eine zentrale interne API, aber nicht
  separat versioniert.

### `scripts/`

Verantwortlichkeiten:

- `build_runc_bundle_from_docker_image.sh`: Docker-Image in OCI/runc-Bundle
  exportieren, `config.json` patchen und runc-Container starten.
- `patch_runc_bundle_for_criu.sh`: Bundle fuer CRIU/runc-Migration vorbereiten,
  u.a. Gunicorn-Args, `/var/tmp` und tmpfs-Mount.
- `restore_runc_bundle_baseline.sh`: Bundle-Konfiguration aus Baseline/Backup
  wiederherstellen.
- `migrate_precopy_vip_cutover.sh`: runc/CRIU Pre-Copy mit optionalen
  Pre-Dumps, finalem Checkpoint, Image-Transfer, Restore auf Destination,
  VIP-Cutover, GARP, conntrack und Health-Wait.
- `migrate_postcopy_lazy_pages_vip_cutover.sh`: runc/CRIU Post-Copy mit
  Lazy-Pages/Page-Server, Image-Kopie, Destination-Restore, optionalem
  Source-Forwarding, Readiness-Gate, Warmup, VIP-Cutover und Cleanup.
- `collect_hostinfo_*.sh` und `collect_downtime_forensics_monitor.sh`:
  Forensik-/Messkampagnen-Helfer.

Bewertung:

- Die produktiv wirksame Migration steckt aktuell hauptsaechlich in Bash.
- Skripte sind stark an runc, CRIU CLI, NFS, iptables, conntrack, arping,
  konkrete Pfade und konkrete Rollen `source`/`dest` gekoppelt.
- Python uebergibt Verhalten ueber Env-Variablen; eine getypte Plan- oder
  Backend-Schnittstelle fehlt.

### `config/`

Verantwortlichkeiten:

- `env.example.yaml`: Host-, Pfad-, VIP-, Runtime-, Migration-, Precopy-,
  Postcopy-, Monitor-, Cleanup- und Lastprofil-Konfiguration.
- `analysis.yaml`: Default-Metriken, abgeleitete Metriken, Exclude-Regeln,
  Statistik und Plotdefinitionen.
- `analysis_paper.yaml`: Paper-spezifische Zusatzplots ueber `extends:
  analysis.yaml`.

Bewertung:

- `env.example.yaml` mischt Core-Operator-Konfiguration mit Forschungs-Load und
  runc-spezifischem Bundle/Gunicorn-Setup.
- `analysis.yaml` ist sehr umfangreich und eher Forschungs-/Auswertungskonfig
  als Core-Konfiguration.
- `analysis_paper.yaml` ist klar Legacy/Forschung.

### `tools/analyze.py` und `tools/plots.py`

Verantwortlichkeiten:

- Standalone-Wrapper fuer Batch-Analyse und Plot-Erzeugung.
- Duplizieren Teile der Zielaufloesung aus dem CLI-Legacy-Pfad.

Bewertung:

- Als Kompatibilitaetswrapper brauchbar.
- Langfristig sollten sie entweder CLI-Aliase des Core bleiben oder in ein
  optionales Analysis-Paket verschoben werden.

### `tests/`

Aktuelle Testschwerpunkte:

- Batch-Layout, Batch-Selectoren und Manifest-Aufloesung.
- Analysis-Pipeline: Config-Merge, Metriken, Excludes, Downtime-Segmente,
  Combined-Analysis und Plotfunktionen.
- CLI: Load-Profile, Progress-Ausgabe, Repo-Sync-Helfer, Migration-Env,
  Cleanup-Skip und Postcopy-Guardrails.
- Monitor-Downtime-Semantik: Segmentauswahl, HTTP/L4-Zaehler, Precopy- und
  Postcopy-Breakdowns, Analyzer-Summary.

Luecken:

- Keine echten Runtime-Backend-Interfaces.
- Keine Integrationstests fuer komplette Remote-Plans ohne reales Labor.
- Keine Contract-Tests fuer Eventschema und Summaryschema als versionierte API.
- Wenig Absicherung fuer Shell-Quoting, idempotente Remote-Cleanup-Pfade und
  Failure-Recovery ueber Prozessgrenzen hinweg.

## Runtime-spezifische runc-Anteile

Folgende Teile sind direkt runc-spezifisch und sollten spaeter hinter einem
Runtime-Backend liegen:

- `scripts/build_runc_bundle_from_docker_image.sh`
  - nutzt Docker nur zum Exportieren, erzeugt danach ein OCI/runc-Bundle;
  - ruft `runc spec`, `runc run`, `runc delete` auf;
  - patcht `config.json` direkt.
- `scripts/patch_runc_bundle_for_criu.sh` und
  `scripts/restore_runc_bundle_baseline.sh`
  - kennen runc-Bundle-Struktur und `config.json`;
  - setzen pro Workload Gunicorn-Startbefehle.
- `scripts/migrate_precopy_vip_cutover.sh`
  - ruft `runc checkpoint` und `runc restore`;
  - erwartet runc-Bundle auf Source und Destination;
  - legt CRIU-Images unter `<share_root>/runc/<name>/<checkpoint>` bzw.
    `/var/lib/criu-local/runc/<name>/<checkpoint>` ab.
- `scripts/migrate_postcopy_lazy_pages_vip_cutover.sh`
  - ruft `runc checkpoint --lazy-pages --page-server`;
  - startet `criu lazy-pages` auf dem Ziel;
  - restored per `runc restore --lazy-pages`.
- `clm/cli/legacy_run.py`
  - setzt `MODE=runc`, `RUNC_BUNDLE_SRC`, `RUNC_BUNDLE_DST`, `RUNC_ROOT`-
    Annahmen und runc-spezifische Checkpoint-Namen;
  - `reset_source`, `cleanup_dest`, `cleanup_source` rufen direkt `sudo runc`
    auf;
  - `preflight` prueft explizit `runc` und `criu`;
  - Cleanup-Pfade enthalten fest `/runc/`.
- `config/env.example.yaml`
  - `container.bundle`, `container.gunicorn`, `precopy.image_mode` und
    mehrere Pfade sind runc/laborbezogen.

Nicht direkt runc-spezifisch, aber runtime-nah:

- VIP-Cutover, iptables-DNAT, conntrack, arping und Host-Netzwerkannahmen.
  Diese sollten nicht im Runtime-Backend selbst verschwinden, sondern in eine
  separate Network-Cutover-Schicht.
- CRIU-Metriken und Eventnamen. Sie sollten von Runtime-Backends befuellt
  werden, aber als Core-Schema separat definiert sein.

## Forschungs- und Legacy-Anteile

Diese Teile tragen klar den Forschungs-/Messkampagnenkontext:

- Synthetische Lastprofile in `clm/cli/legacy_run.py` und
  `config/env.example.yaml`:
  `cpu`, `wrk`, `wrk1..3`, `download`, `upload`, `stream`.
- `workload/flask_app/app.py` als spezieller Test-Workload mit Endpunkten fuer
  Health, Counter, Stream, Download, Upload und CPU-Last.
- `tools/monitor/monitor.py` Target-Familien fuer Counter/Info/Stream/Download/
  Upload, soweit sie nur Forschungs-Workloads bedienen.
- `config/analysis_paper.yaml` und viele Plotdefinitionen in
  `config/analysis.yaml`.
- Umfangreiche wissenschaftliche Statistik, CI/Bootstrap und Paper-Views in
  `clm/analysis_pipeline.py`.
- Forensik-Skripte unter `scripts/collect_*`.
- Legacy-Kompatibilitaet:
  - `clm.py` als alter Entrypoint;
  - `tools/analyze.py` und `tools/plots.py` als Standalone-Wrapper;
  - `create_legacy_run_link` fuer alte Run-Pfade;
  - Legacy-Metriknamen wie `http_downtime_ms`, `l4_downtime_ms` neben VIP- und
    client-visible-Metriken.

Diese Anteile sind nicht wertlos. Sie sollten aber nicht den produktiven
Core-Pfad formen. Besser waere ein Bereich `examples/`, `research/`,
`tools/research/` oder ein optionales Analysis-Extra.

## Was im produktiven CLM-Core bleiben sollte

Core-wuerdig:

- Config-Loading mit klar versioniertem Schema und Validierung.
- Hostmodell: Monitor/Controller, Source, Destination, Rollen, SSH-Zugang,
  Pfade, Runtime-Konfiguration.
- Preflight als strukturierte Checks mit maschinenlesbarem Ergebnis.
- Migrations-Orchestrierung als Plan:
  - vorbereiten;
  - checkpointen;
  - transferieren/sichtbar machen;
  - restoren;
  - Netzwerk-Cutover;
  - Health/Readiness pruefen;
  - Cleanup;
  - Artefakte schreiben.
- Runtime-Backend-Interface, zunaechst mit `runc`-Implementierung.
- CRIU-Operationen als abstrahierte Engine-Schicht oder Backend-Faehigkeit.
- Network-Cutover-Komponente fuer VIP, GARP, conntrack und optionale NAT/Bridge-
  Pfade.
- Remote-Ausfuehrung mit klaren Command-Objekten, Logging und Fehlersemantik.
- Artefaktmodell:
  - Batch;
  - Run;
  - Events;
  - Monitor-Logs;
  - Summary;
  - Cleanup-Report;
  - Config-Snapshot.
- Minimaler Monitor fuer HTTP/L4 und optionale Rohlog-Erfassung.
- Kompakte Run-Summary mit Downtime, Phasen, Warnungen und Links zu Rohdaten.
- Tests fuer Schema, Plan-Erzeugung, Backend-Kontrakte und Failure-Cases.

Optional, aber nicht Core:

- synthetische Lastgeneratoren;
- Paper-Analyse;
- umfangreiche Plotting-Pipeline;
- Workload-spezifische Endpunkte;
- Forensik-Skripte.

## Konkrete Risiken im aktuellen Aufbau

1. **Hohe Kopplung in `clm/cli/legacy_run.py`**

   CLI, Domainlogik, Remote-Ausfuehrung, Runtime-Details, Loadgeneratoren und
   Analyse-Aufrufe sind vermischt. Jede Erweiterung auf Docker/containerd/Podman
   wuerde aktuell viele Stellen beruehren.

2. **Shell-Env als wichtigste interne API**

   Migrationen werden ueber zusammengesetzte Bash-Skripte und Env-Variablen
   gesteuert. Das erschwert Validierung, Dry-Run-Ausgabe, statische Tests,
   Fehlerklassifikation und sichere Erweiterungen.

3. **Repo-muss-auf-allen-Hosts-existieren**

   Preflight verlangt synchronen Git-Head auf Monitor, Source und Destination.
   Das ist fuer Forschungsreproduzierbarkeit nuetzlich, aber fuer ein Produkt
   ein Deployment-Risiko und ein Bedienungsproblem.

4. **runc ist nicht isoliert**

   runc-Annahmen stecken in Dateipfaden, Env-Namen, Skripten, Cleanup,
   Preflight und Config. Ein zweiter Runtime-Backend waere ohne Refactor schwer
   sauber einzufuehren.

5. **Netzwerk-Cutover ist mit Runtime-Migration vermischt**

   VIP, iptables, conntrack, ARP, bridge/host-Modus und Postcopy-Forwarding sind
   ueber CLI und Skripte verteilt. Dadurch ist schwer erkennbar, welche Schritte
   runtime-neutral und welche runtime-spezifisch sind.

6. **Monitor und Analyzer sind gekoppelt**

   `tools/monitor/monitor.py` schreibt Live-Proben und berechnet zugleich
   komplexe Downtime-Semantik. Das macht den Monitor schwer austauschbar und
   erschwert eine stabile Summary-API.

7. **Doppelte Downtime-Logik**

   Downtime-Breakdown-Phasen existieren sowohl im Monitor-Analyzer als auch in
   der Analysis-Pipeline. Abweichungen koennen zu widerspruechlichen Ergebnissen
   fuehren.

8. **Forschungsmetriken dominieren die Analyse**

   Operator-relevante Diagnose ist zwischen sehr vielen Metriken, Plots und
   Paper-Konfigurationen versteckt. Das Risiko ist Bedienfehler und unklare
   Standardausgabe.

9. **Laborspezifische Defaults**

   IPs, Interfaces, User, `/mnt/criu`, `/var/lib/criu-local`, `testweb`,
   Gunicorn und konkrete Hostnamen sind tief in Defaults und Skripten sichtbar.
   Das erschwert Wiederverwendung in anderen Umgebungen.

10. **Unklare Schema-Versionierung**

    Eventnamen, Summary-Felder, Metrics-CSV-Spalten und Downtime-Segmente sind
    faktisch APIs, aber nicht als versionierte Schemas dokumentiert oder
    validiert.

11. **Privilegierte destruktive Operationen**

    Remote-Cleanup nutzt `sudo rm -rf`, `runc delete -f`, `ip addr del`,
    `conntrack -D` und `fuser -k`. Ohne Plan-/Scope-Validierung ist das fuer
    produktive Nutzung riskant.

12. **Testluecken bei Remote-Integration**

    Unit-Tests decken viel Berechnungslogik ab, aber keine End-to-End-
    Planvalidierung, kein Deployment von Host-Helpers und keine simulierte
    Remote-Execution mit strukturierten Fehlern.

## Vorgeschlagene Zielstruktur

Eine konservative Zielstruktur sollte die vorhandene Funktionalitaet nicht
wegwerfen, sondern klare Schichten einfuehren.

```text
clm/
  cli/
  config/
    schema.py
    loader.py
    defaults.py
  core/
    models.py
    plan.py
    events.py
    artifacts.py
    errors.py
  execution/
    local.py
    ssh.py
    command.py
  preflight/
    checks.py
    result.py
  runtime/
    base.py
    runc.py
  criu/
    options.py
    images.py
  network/
    vip.py
    nat.py
    cutover.py
  monitor/
    probes.py
    writer.py
    runner.py
    summarize.py
  analysis/
    ingest.py
    downtime.py
    stats.py
    plots.py
  batching.py
scripts/
  runc/
    build_bundle_from_docker_image.sh
    migrate_precopy.sh
    migrate_postcopy_lazy_pages.sh
research/
  workloads/
  analysis_configs/
  forensics/
tools/
  analyze.py
  plots.py
```

### Begruendung der Zielstruktur

- Die neue CLI-Schicht sollte nur Argumente parsen, Config laden, Plan erzeugen
  und Services aufrufen. Die CLI sollte keine Runtime- oder Bash-Details
  kennen; `legacy_run.py` bleibt bis dahin die Kompatibilitaetsschicht.
- `clm/config/` kapselt Defaults, Schema-Versionen, Validierung und Migration
  alter Configs. Das reduziert implizite Annahmen in `DEFAULTS`.
- `clm/core/` definiert stabile Datenmodelle fuer Runs, Plans, Events,
  Artefakte und Fehler. Das macht Summary/Event/Metrics-Vertraege testbar.
- `clm/execution/` trennt lokales Ausfuehren, SSH-Ausfuehrung, Streaming,
  Quoting und Command-Logging von der Migrationslogik.
- `clm/preflight/` liefert strukturierte Checks statt nur Textausgabe. Die CLI
  kann daraus Text rendern, Tests koennen JSON/Objekte pruefen.
- `clm/runtime/base.py` definiert ein Backend-Interface, z.B. `prepare`,
  `checkpoint`, `restore`, `cleanup`, `state`, `supports_postcopy`.
- `clm/runtime/runc.py` wird die erste Implementierung und kann anfangs noch
  vorhandene Skripte verwenden. Spaeter koennen Docker/containerd/Podman
  daneben entstehen.
- `clm/criu/` enthaelt CRIU-nahe Optionen und Image-Pfadlogik, soweit diese
  nicht komplett vom Runtime-Backend verborgen werden sollte.
- `clm/network/` trennt VIP/NAT/GARP/conntrack vom Runtime-Backend. Das ist
  wichtig, weil Netzwerk-Cutover runtime-neutral sein kann, aber nicht
  migrationsneutral ist.
- `clm/monitor/` trennt Probing, Logwriting, Runner-Steuerung und Summary-
  Berechnung. Der aktuelle Monitor kann schrittweise dorthin zerlegt werden.
- `clm/analysis/` bleibt optionaler als heute: Ingest und Downtime-Semantik
  koennen Core-nahe bleiben; Statistik/Plots sollten als Extra installierbar
  sein.
- `research/` nimmt Workloads, Paper-Konfigurationen, Forensik und
  Messkampagnenlogik auf. Dadurch bleibt der Wert der Forschungsartefakte
  erhalten, ohne den Operator-Pfad zu belasten.

## Migrationspfad fuer die Codebasis

Empfohlene Reihenfolge ohne grossen Big-Bang-Refactor:

1. Event- und Summary-Schema dokumentieren und mit Tests fixieren.
2. Interne Modelle fuer `RunContext`, `MigrationPlan` und `HostConfig`
   einfuehren, ohne Verhalten zu aendern.
3. Remote-Ausfuehrung und Command-Streaming in `clm/execution/` auslagern.
4. runc-spezifische Pfade und Script-Env in `clm/runtime/runc.py` kapseln.
5. VIP/NAT/conntrack/GARP-Kommandos in `clm/network/` isolieren.
6. Monitor-Anteil in Probe-Runner und Analyzer/Summarizer trennen.
7. `analysis_pipeline.py` in Ingest, Downtime, Stats und Plots zerlegen.
8. Research-Workloads und Paper-Configs verschieben, CLI-Kompatibilitaet bei
   Bedarf ueber Deprecated-Wrapper erhalten.

## Baseline fuer "CLM-Core"

Als produktives Core-Minimum sollte CLM mittelfristig Folgendes liefern:

- `clm preflight`: strukturierte, klare Pruefung ohne Seiteneffekte ausser
  expliziten Schreibtests.
- `clm migrate` oder weiterhin `clm run`: ein einzelner, nachvollziehbarer
  Migrationsplan mit Dry-Run und Artefakten.
- `clm summarize`: kompakte Auswertung eines Runs mit Downtime, Phasen,
  Fehlern, Warnungen und Links zu Rohlogs.
- `runc` als erstes Backend, aber nicht als Architekturannahme.
- Keine synthetischen Forschungsloads im Standardpfad.
- Keine Paper-Plots im Core-Default.
- Klare Versionierung fuer Config, Events, Summary und Run-Artefakte.
