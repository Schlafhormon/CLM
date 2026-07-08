# Traffic Configuration

CLM treats traffic cutover as an optional backend. The default model is not
VIP-specific; the old `vip:` section is still accepted for compatibility with
the existing runc lab scripts.

## Modes

- `external`: CLM does not switch traffic. Use this when a load balancer,
  service mesh, route controller, or operator changes traffic outside CLM. A
  `verify` hook can still be configured.
- `none`: alias for `external`.
- `command`: CLM runs configured command hooks for `prepare`, `switch`,
  `verify`, and optional `rollback`.
- `vip`: compatibility adapter for the existing VIP/GARP/conntrack logic used
  by the current runc scripts.

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
