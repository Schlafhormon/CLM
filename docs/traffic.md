# Traffic Configuration

CLM treats traffic cutover as an optional backend. The default model is not
VIP-specific; the old `vip:` section is still accepted for compatibility with
the existing runc lab scripts.

## Modes

- `external`: CLM does not switch traffic. Use this when a load balancer,
  service mesh, route controller, or operator changes traffic outside CLM. A
  `verify` hook can still be configured. The Python `clm run` baseline and
  cleanup path will not add/delete VIP addresses, flush VIP conntrack state, or
  send gratuitous ARP in this mode.
- `none`: alias for `external`.
- `command`: CLM runs configured command hooks for `prepare`, `switch`,
  `verify`, and optional `rollback`. Hooks are the only traffic handoff action;
  CLM does not perform VIP IP manipulation for this mode.
- `vip`: compatibility adapter for the existing VIP/GARP/conntrack logic used
  by the current runc scripts.

For `external` and `command`, CLM still performs the configured migration and
destination readiness/health checks. Default monitoring tracks source and
destination probes only. VIP probes and VIP burst events are enabled by the
`vip` backend or by explicit monitor/load configuration.

In the current Python `RuncBackend`, `traffic.mode=external` and
`traffic.mode=command` export `TRAFFIC_MODE` and optional command-hook
variables to the legacy migration script, but they must not export `VIP_*`
environment variables. The Bash scripts still contain VIP helper functions for
the `vip` branch; their `external` and `command` `TRAFFIC_MODE` cases must not
execute `ip addr`, `conntrack`, or `arping`.

Legacy synthetic load profiles are still lab-oriented. When `traffic.mode` is
`external`, `command`, or `none`, CLM rejects `load.target: vip` before run
side effects. Use `src`, `dst`, `all`, explicit probes, or traffic/load tooling
outside CLM for non-VIP setups.

## Examples

External traffic:

```yaml
traffic:
  mode: external
  hooks:
    verify: ["curl", "-fsS", "http://service.example/health"]
```

Command traffic:

```yaml
traffic:
  mode: command
  hooks:
    prepare: ["lbctl", "drain", "source"]
    switch: ["lbctl", "activate", "dest"]
    verify: ["curl", "-fsS", "http://service.example/health"]
    rollback: ["lbctl", "activate", "source"]
```

Hook commands should be argv lists. Shell strings are rejected unless the hook
sets `allow_shell: true` explicitly:

```yaml
traffic:
  mode: command
  hooks:
    switch:
      command: "lbctl activate dest && lbctl wait dest"
      allow_shell: true
```

VIP compatibility:

```yaml
vip:
  addr: 192.168.13.50
  cidr: /24
  port: 8080
  if_source: enp1s0
  if_dest: enp1s0

traffic:
  mode: vip
```

If `traffic:` is absent and `vip:` exists, CLM selects `vip` for backwards
compatibility. New configurations should set `traffic.mode` explicitly.
