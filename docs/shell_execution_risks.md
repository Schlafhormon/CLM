# Shell And SSH Execution Risks

This note tracks the current risk boundary after introducing the small
`clm.host` shell rendering layer.

## Reduced In Python

- Environment exports are rendered through `ShellScript` / `CommandBuilder`.
  Variable names are validated as shell identifiers, and values are quoted with
  shell-safe quoting, including spaces, quotes, and embedded newlines.
- `~/...` environment values are rendered as `${HOME}...` so legacy remote repo
  paths keep their old expansion behavior without using unquoted `~` strings.
- Remote SSH script execution is described by `RemoteScript` and executed as
  `ssh ... -- bash -l -s` with the script sent on stdin. This avoids nesting
  the full migration script inside a remote `bash -lc '<script>'` command
  argument.
- Command/result display uses centralized redaction for common secret forms
  such as `TOKEN=value`, `API_KEY='value with spaces'`, `--password value`, and
  secret-looking exported environment variables.
- Python-generated runc migration scripts and legacy compatibility helpers now
  share the same export/script rendering code. The old helper names
  `_escape_env_value`, `_export_lines`, and `build_remote_script` remain as
  wrappers for compatibility.

## Still Present In Legacy Scripts

- `scripts/migrate_precopy_vip_cutover.sh` and
  `scripts/migrate_postcopy_lazy_pages_vip_cutover.sh` still implement
  `run()` with `eval "$@"`. This remains a shell-injection risk if untrusted
  data reaches command strings inside those scripts.
- Command traffic hooks are still exported to the legacy scripts as shell
  command strings. Python validates hook configuration and renders argv hooks
  with `shlex.join`, but the legacy scripts execute the final string through
  `run "$cmd"`, which currently reaches `eval`.
- Several legacy script SSH calls still interpolate variables into remote shell
  strings. Some values are single-quoted with local helpers, but this is not a
  uniform abstraction inside the Bash code.
- VIP, iptables, conntrack, arping, CRIU, and runc operations still run from the
  legacy scripts with root-level side effects. This change reduces Python-side
  quoting and display risks; it does not redesign migration behavior or cleanup
  semantics.

The next reduction step should replace the legacy script `run()` helpers and
traffic hook execution with argv-oriented functions, but that is intentionally
outside this small compatibility-preserving change.

