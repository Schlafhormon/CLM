#!/usr/bin/env python3

# Migration monitoring runtime.

import argparse, json, os, signal, sys, time, threading, socket, ssl, http.client
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse
from typing import Optional, Tuple

from clm.monitoring import analysis as _monitor_analysis

# Compatibility: private analyzer helpers historically lived in this script.
for _name in dir(_monitor_analysis):
    if not _name.startswith("__"):
        globals()[_name] = getattr(_monitor_analysis, _name)


stop = False
def handle_sigint(sig, frame):
    # Request a clean shutdown.
    global stop
    stop = True


def now_ms() -> int:
    # Get current ms.
    return int(time.time() * 1000)

def iso_ts() -> str:
    # Format ISO timestamp.
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()) + f".{int((time.time()%1)*1000):03d}Z"


def paced_sleep(next_deadline: float, interval_ms: int) -> float:
    # Pace sleep.
    interval_s = max(0.001, float(interval_ms) / 1000.0)
    candidate = float(next_deadline) + interval_s
    now = time.perf_counter()
    delay = candidate - now
    if delay > 0:
        time.sleep(delay)
        return candidate

    return now


class BurstController:
    # Control burst sampling.

    def __init__(self, events_path: Optional[str], window_ms: int, trigger_events: Optional[list]):
        self.events_path = events_path
        self.window_ms = max(0, int(window_ms or 0))
        self.trigger_events = set(trigger_events or [])
        self._active_until_ms = 0
        self._lock = threading.Lock()
        self._thread = None

    def start(self) -> None:
        if not self.events_path or self.window_ms <= 0 or not self.trigger_events:
            return
        self._thread = threading.Thread(target=self._tail_worker, daemon=True)
        self._thread.start()

    def activate(self) -> None:
        until = now_ms() + self.window_ms
        with self._lock:
            if until > self._active_until_ms:
                self._active_until_ms = until

    def is_active(self) -> bool:
        with self._lock:
            return now_ms() <= self._active_until_ms

    def interval_ms(self, *, base_ms: int, burst_ms: Optional[int]) -> int:
        if burst_ms is None:
            return int(base_ms)
        if self.is_active():
            return max(1, int(burst_ms))
        return int(base_ms)

    def _tail_worker(self) -> None:
        pos = 0
        while not stop:
            try:
                if not os.path.exists(self.events_path):
                    time.sleep(0.05)
                    continue
                size = os.path.getsize(self.events_path)
                if size < pos:
                    pos = 0
                with open(self.events_path, encoding="utf-8") as fp:
                    fp.seek(pos)
                    for line in fp:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            ev = json.loads(line)
                        except Exception:
                            continue
                        name = str((ev or {}).get("event") or "")
                        if name in self.trigger_events:
                            self.activate()
                    pos = fp.tell()
            except Exception:
                pass
            time.sleep(0.05)


class RotatingWriter:
    def __init__(self, base: str, rotate_mb: int, fmt: str):
        # Initialize burst sampling.
        self.base = base
        self.rotate_bytes = int(rotate_mb * 1024 * 1024)
        self.fmt = fmt
        self.idx = 0
        self.lock = threading.Lock()
        self.closed = False
        os.makedirs(os.path.dirname(base), exist_ok=True)
        self._open_new()

    def _open_new(self):
        if self.idx == 0:
            self.cur = self.base
        else:
            root, ext = os.path.splitext(self.base)
            self.cur = f"{root}-part{self.idx}{ext}"

        self.fp = open(self.cur, "a", buffering=1, encoding="utf-8")

        try:
            latest = os.path.join(os.path.dirname(self.base), f"latest.{self.fmt}")
            if os.path.islink(latest) or os.path.exists(latest):
                try:
                    os.remove(latest)
                except Exception:
                    pass
            os.symlink(os.path.basename(self.cur), latest)
        except Exception:
            pass

    def write(self, row):
        # Write one record.
        line = row if isinstance(row, str) else json.dumps(row, ensure_ascii=False)
        with self.lock:
            if self.closed or self.fp.closed:
                return False
            self.fp.write(line + "\n")
            if self.fp.tell() >= self.rotate_bytes:
                try:
                    self.fp.close()
                except Exception:
                    pass
                self.idx += 1
                self._open_new()
        return True

    def close(self):
        # Close the writer.
        with self.lock:
            self.closed = True
            try:
                self.fp.close()
            except Exception:
                pass


def join_worker_threads(threads, timeout_s: float = 5.0) -> None:
    # Join worker threads.
    deadline = time.monotonic() + max(0.0, timeout_s)
    for th in threads:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        try:
            if th.is_alive():
                th.join(timeout=max(0.05, remaining))
        except Exception:
            pass


def resolve_addr(host: str, port: int, timeout_s: float) -> Tuple[Tuple, float]:
    # Resolve address.
    t0 = time.perf_counter()
    infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    dns_ms = (time.perf_counter() - t0) * 1000.0
    af, socktype, proto, canonname, sa = infos[0]
    return (af, socktype, proto, sa), dns_ms

def measure_http_detailed(url: str, timeout_ms: int, extra_headers: Optional[dict]=None):
    # Measure HTTP detailed.

    parsed = urlparse(url)
    scheme = parsed.scheme or "http"
    host = parsed.hostname
    port = parsed.port or (443 if scheme == "https" else 80)
    path = parsed.path or "/"
    if parsed.query:
        path += "?" + parsed.query

    headers = {
        "Host": host,
        "Connection": "close",
        "User-Agent": "criu-monitor/1.0",
        "Accept": "*/*",
    }
    if extra_headers:
        headers.update(extra_headers)

    sock = None
    ssl_sock = None
    dns_ms = tcp_ms = tls_ms = ttfb_ms = headers_ms = 0.0
    total_bytes = 0
    status = "ERR"
    err = ""
    try:
        conn_timeout = timeout_ms / 1000.0
        addrinfo, dns_ms = resolve_addr(host, port, conn_timeout)
        af, socktype, proto, sa = addrinfo


        t0 = time.perf_counter()
        sock = socket.socket(af, socktype, proto)
        sock.settimeout(conn_timeout)
        sock.connect(sa)
        tcp_ms = (time.perf_counter() - t0) * 1000.0


        if scheme == "https":
            t1 = time.perf_counter()
            ctx = ssl.create_default_context()
            ssl_sock = ctx.wrap_socket(sock, server_hostname=host)
            tls_ms = (time.perf_counter() - t1) * 1000.0
            s = ssl_sock
        else:
            s = sock


        req_lines = [f"GET {path} HTTP/1.1"]
        for k, v in headers.items():
            req_lines.append(f"{k}: {v}")
        req_lines.append("")
        req_lines.append("")
        req = "\r\n".join(req_lines).encode("utf-8")

        t_send = time.perf_counter()
        s.sendall(req)


        first = s.recv(1)
        if not first:
            raise IOError("no first byte from server")
        ttfb_ms = (time.perf_counter() - t_send) * 1000.0


        buf = bytearray(first)
        while b"\r\n\r\n" not in buf:
            chunk = s.recv(4096)
            if not chunk:
                break
            buf.extend(chunk)
        headers_ms = (time.perf_counter() - t_send) * 1000.0


        head, _, rest = buf.partition(b"\r\n\r\n")
        total_bytes = len(buf)
        try:
            status_line = head.split(b"\r\n", 1)[0].decode("iso-8859-1")
            parts = status_line.split()
            if len(parts) >= 2 and parts[1].isdigit():
                status = int(parts[1])
            else:
                status = "ERR"
        except Exception as pe:
            status = "ERR"
            err = f"parse-status: {pe}"


        while True:
            chunk = s.recv(65536)
            if not chunk:
                break
            total_bytes += len(chunk)

        rt_ms = (time.perf_counter() - t_send) * 1000.0
        return {
            "status": status,
            "rt_ms": rt_ms,
            "ttfb_ms": ttfb_ms,
            "headers_ms": headers_ms,
            "dns_ms": dns_ms,
            "tcp_ms": tcp_ms,
            "tls_ms": tls_ms,
            "bytes": total_bytes,
            "err": err,
            "scheme": scheme, "host": host, "port": port, "path": path,
        }
    except Exception as e:


        rt_ms = (time.perf_counter() - (t_send if 't_send' in locals() else time.perf_counter())) * 1000.0
        return {
            "status": "ERR",
            "rt_ms": rt_ms,
            "ttfb_ms": ttfb_ms,
            "headers_ms": headers_ms,
            "dns_ms": dns_ms,
            "tcp_ms": tcp_ms,
            "tls_ms": tls_ms,
            "bytes": total_bytes,
            "err": str(e),
            "scheme": scheme, "host": host, "port": port, "path": path,
        }
    finally:
        try:
            if ssl_sock: ssl_sock.close()
        except Exception:
            pass
        try:
            if sock: sock.close()
        except Exception:
            pass


def tcp_connect_once(host: str, port: int, timeout_ms: int) -> bool:
    # Check TCP connect once.
    try:
        with socket.create_connection((host, port), timeout=timeout_ms/1000.0):
            return True
    except Exception:
        return False


def _merge_url_query(url: str, updates: dict) -> str:
    # Merge URL query.
    parsed = urlparse(url)
    pairs = dict(parse_qsl(parsed.query, keep_blank_values=True))
    for k, v in (updates or {}).items():
        if v is None:
            continue
        pairs[str(k)] = str(v)
    query = urlencode(pairs)
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, query, parsed.fragment))


def _http_connection(parsed, timeout_ms: int):
    # Create an HTTP connection.
    timeout_s = max(0.1, timeout_ms / 1000.0)
    if parsed.scheme == "https":
        ctx = ssl.create_default_context()
        return http.client.HTTPSConnection(parsed.hostname, parsed.port or 443, timeout=timeout_s, context=ctx)
    return http.client.HTTPConnection(parsed.hostname, parsed.port or 80, timeout=timeout_s)


def _target_path(parsed) -> str:
    # Build the request path.
    path = parsed.path or "/"
    if parsed.query:
        path += "?" + parsed.query
    return path


def http_worker(
    name: str,
    url: str,
    interval_ms: int,
    timeout_ms: int,
    writer: RotatingWriter,
    fmt: str,
    tags: dict,
    burst_controller: Optional[BurstController] = None,
    burst_interval_ms: Optional[int] = None,
):
    # Poll an HTTP target.
    seq = 0
    next_deadline = time.perf_counter()
    while not stop:
        seq += 1
        t_wall = iso_ts()
        t_epoch_start = now_ms()
        r = measure_http_detailed(url, timeout_ms)
        t_epoch_end = now_ms()
        if fmt == "csv":

            err = str(r["err"]).replace(",", ";")
            line = (
                f"{t_wall},{t_epoch_start},{name},{r['status']},{r['rt_ms']:.2f},{r['ttfb_ms']:.2f},"
                f"{r['headers_ms']:.2f},{r['dns_ms']:.2f},{r['tcp_ms']:.2f},{r['tls_ms']:.2f},"
                f"{r['bytes']},{err},{t_epoch_start},{t_epoch_end}"
            )
            writer.write(line)
        else:
            row = {
                "ts": t_wall,
                "ts_ms": t_epoch_start,
                "name": name,
                "seq": seq,
                "t_start_ms": t_epoch_start,
                "t_end_ms": t_epoch_end,
                **r,
                **({"tags": tags} if tags else {}),
            }
            writer.write(row)
        effective_interval_ms = (
            burst_controller.interval_ms(base_ms=interval_ms, burst_ms=burst_interval_ms)
            if burst_controller
            else int(interval_ms)
        )
        next_deadline = paced_sleep(next_deadline, effective_interval_ms)

def l4_worker(
    name: str,
    host: str,
    port: int,
    interval_ms: int,
    timeout_ms: int,
    writer: RotatingWriter,
    burst_controller: Optional[BurstController] = None,
    burst_interval_ms: Optional[int] = None,
):
    # Poll an L4 target.
    next_deadline = time.perf_counter()
    while not stop:
        t_wall = iso_ts()
        t_epoch_start = now_ms()
        ok = tcp_connect_once(host, port, timeout_ms)
        t_epoch_end = now_ms()

        line = f"{t_wall},{t_epoch_start},{name},{host},{port},{'up' if ok else 'down'},{t_epoch_start},{t_epoch_end}"
        writer.write(line)
        effective_interval_ms = (
            burst_controller.interval_ms(base_ms=interval_ms, burst_ms=burst_interval_ms)
            if burst_controller
            else int(interval_ms)
        )
        next_deadline = paced_sleep(next_deadline, effective_interval_ms)

def info_worker(name: str, url: str, interval_ms: int, timeout_ms: int, writer: RotatingWriter, tags: dict):

    next_deadline = time.perf_counter()
    while not stop:
        t_wall = iso_ts()
        t_epoch = now_ms()
        r = measure_http_detailed(url, timeout_ms)
        row = {"ts": t_wall, "ts_ms": t_epoch, "name": name, "ok": (isinstance(r["status"], int) and r["status"]==200)}

        try:
            parsed = urlparse(url)
            path = parsed.path or "/"
            if parsed.query: path += "?" + parsed.query

            conn = (ssl.create_default_context() and http.client.HTTPSConnection(parsed.hostname, parsed.port or 443, timeout=timeout_ms/1000.0, context=ssl.create_default_context())) if (parsed.scheme=="https") else http.client.HTTPConnection(parsed.hostname, parsed.port or 80, timeout=timeout_ms/1000.0)
            conn.request("GET", path, headers={"Connection":"close", "Accept":"application/json"})
            resp = conn.getresponse()
            body = resp.read()
            if resp.status == 200:
                try:
                    j = json.loads(body.decode("utf-8"))
                    row.update({"info": j})
                except Exception as je:
                    row.update({"parse_err": str(je)})
            else:
                row.update({"status": resp.status})
        except Exception as e:
            row.update({"err": str(e)})
        finally:
            try:
                conn.close()
            except Exception:
                pass
        if tags: row["tags"] = tags
        writer.write(row)
        next_deadline = paced_sleep(next_deadline, interval_ms)

def counter_worker(name: str, url: str, interval_ms: int, timeout_ms: int, writer: RotatingWriter, fmt: str):
    # Poll the counter endpoint.
    last = None
    next_deadline = time.perf_counter()
    while not stop:
        t_wall = iso_ts()
        t_epoch = now_ms()

        val = None
        status = "ERR"
        err = ""
        try:
            parsed = urlparse(url)
            path = parsed.path or "/"
            if parsed.query: path += "?" + parsed.query
            conn = (ssl.create_default_context() and http.client.HTTPSConnection(parsed.hostname, parsed.port or 443, timeout=timeout_ms/1000.0, context=ssl.create_default_context())) if (parsed.scheme=="https") else http.client.HTTPConnection(parsed.hostname, parsed.port or 80, timeout=timeout_ms/1000.0)
            conn.request("GET", path, headers={"Connection":"close", "Accept":"application/json"})
            resp = conn.getresponse()
            body = resp.read()
            status = resp.status
            if resp.status == 200:
                j = json.loads(body.decode("utf-8"))
                val = j.get("counter")
            else:
                err = f"HTTP {resp.status}"
        except Exception as e:
            err = str(e)
        finally:
            try:
                conn.close()
            except Exception:
                pass

        delta = (None if (last is None or val is None) else (val - last))
        last = val if val is not None else last

        if fmt == "csv":

            writer.write(f"{t_wall},{t_epoch},{name},{status},{val if val is not None else ''},{'' if delta is None else delta},{err.replace(',',';')}")
        else:
            writer.write({"ts": t_wall, "ts_ms": t_epoch, "name": name, "status": status, "counter": val, "delta": delta, "err": err})
        next_deadline = paced_sleep(next_deadline, interval_ms)

def stream_worker(
    name: str,
    url: str,
    interval_ms_param: int,
    limit_param: Optional[int],
    payload_kb_param: int,
    writer: RotatingWriter,
    timeout_ms: int = 10000,
    progress_interval_ms: int = 1000,
):
    # Monitor an NDJSON stream.
    progress_every = max(100, int(progress_interval_ms))
    while not stop:
        req_url = _merge_url_query(
            url,
            {
                "interval_ms": interval_ms_param,
                "limit": limit_param,
                "payload_kb": max(0, payload_kb_param),
                "format": "ndjson",
            },
        )
        parsed = urlparse(req_url)
        path = _target_path(parsed)
        conn = None
        bytes_total = 0
        t_start = now_ms()
        last_progress_ts = t_start
        last_progress_bytes = 0
        err = ""

        writer.write(
            {
                "type": "stream_start",
                "ts": iso_ts(),
                "ts_ms": t_start,
                "name": name,
                "url": req_url,
                "payload_kb": max(0, payload_kb_param),
            }
        )
        try:
            conn = _http_connection(parsed, timeout_ms=timeout_ms)
            conn.request("GET", path, headers={"Connection": "close", "Accept": "text/plain"})
            resp = conn.getresponse()
            if resp.status >= 400:
                raise IOError(f"HTTP {resp.status}")

            buf = bytearray()
            while not stop:
                chunk = resp.read(4096)
                if not chunk:
                    break
                bytes_total += len(chunk)
                buf.extend(chunk)

                while True:
                    pos = buf.find(b"\n")
                    if pos < 0:
                        break
                    line = bytes(buf[:pos])
                    del buf[: pos + 1]
                    t_epoch = now_ms()
                    t_wall = iso_ts()
                    if not line:
                        continue
                    try:
                        j = json.loads(line.decode("utf-8"))
                        writer.write(
                            {
                                "type": "stream_line",
                                "ts": t_wall,
                                "ts_ms": t_epoch,
                                "name": name,
                                "server_ts": j.get("ts"),
                                "i": j.get("i"),
                                "payload_len": j.get("payload_len"),
                            }
                        )
                    except Exception:
                        writer.write(
                            {
                                "type": "stream_raw",
                                "ts": t_wall,
                                "ts_ms": t_epoch,
                                "name": name,
                                "line": line.decode("utf-8", "replace"),
                            }
                        )

                if len(buf) > 2 * 1024 * 1024:

                    writer.write(
                        {
                            "type": "stream_raw",
                            "ts": iso_ts(),
                            "ts_ms": now_ms(),
                            "name": name,
                            "line": bytes(buf[:4096]).decode("utf-8", "replace"),
                            "truncated": True,
                        }
                    )
                    buf.clear()

                now_t = now_ms()
                if now_t - last_progress_ts >= progress_every:
                    dt = max(1, now_t - last_progress_ts)
                    inst_bytes = max(0, bytes_total - last_progress_bytes)
                    writer.write(
                        {
                            "type": "stream_progress",
                            "ts": iso_ts(),
                            "ts_ms": now_t,
                            "name": name,
                            "bytes_total": bytes_total,
                            "dt_ms": dt,
                            "inst_bps": round((inst_bytes * 1000.0) / dt, 3),
                        }
                    )
                    last_progress_ts = now_t
                    last_progress_bytes = bytes_total
        except Exception as e:
            err = str(e)
        finally:
            try:
                if conn:
                    conn.close()
            except Exception:
                pass
            duration = now_ms() - t_start
            writer.write(
                {
                    "type": "stream_disconnect",
                    "ts": iso_ts(),
                    "ts_ms": now_ms(),
                    "name": name,
                    "duration_ms": duration,
                    "bytes": bytes_total,
                    "err": err,
                }
            )
        if stop:
            break
        time.sleep(0.5)


def raw_stream_worker(
    name: str,
    url: str,
    interval_ms_param: int,
    limit_param: Optional[int],
    payload_kb_param: int,
    read_chunk_kb: int,
    timeout_ms: int,
    progress_interval_ms: int,
    writer: RotatingWriter,
):
    # Monitor a raw byte stream.
    read_chunk = max(1, int(read_chunk_kb)) * 1024
    progress_every = max(100, int(progress_interval_ms))
    while not stop:
        req_url = _merge_url_query(
            url,
            {
                "interval_ms": interval_ms_param,
                "limit": limit_param,
                "payload_kb": max(0, payload_kb_param),
                "format": "raw",
            },
        )
        parsed = urlparse(req_url)
        path = _target_path(parsed)
        conn = None
        bytes_total = 0
        t_start = now_ms()
        last_progress_ts = t_start
        last_progress_bytes = 0
        err = ""
        writer.write({"type": "stream_start", "ts": iso_ts(), "ts_ms": t_start, "name": name, "url": req_url, "mode": "raw"})
        try:
            conn = _http_connection(parsed, timeout_ms=timeout_ms)
            conn.request("GET", path, headers={"Connection": "close", "Accept": "application/octet-stream"})
            resp = conn.getresponse()
            if resp.status >= 400:
                raise IOError(f"HTTP {resp.status}")

            while not stop:
                chunk = resp.read(read_chunk)
                if not chunk:
                    break
                bytes_total += len(chunk)
                now_t = now_ms()
                if now_t - last_progress_ts >= progress_every:
                    dt = max(1, now_t - last_progress_ts)
                    inst_bytes = max(0, bytes_total - last_progress_bytes)
                    writer.write(
                        {
                            "type": "stream_progress",
                            "ts": iso_ts(),
                            "ts_ms": now_t,
                            "name": name,
                            "mode": "raw",
                            "bytes_total": bytes_total,
                            "dt_ms": dt,
                            "inst_bps": round((inst_bytes * 1000.0) / dt, 3),
                        }
                    )
                    last_progress_ts = now_t
                    last_progress_bytes = bytes_total
        except Exception as e:
            err = str(e)
        finally:
            try:
                if conn:
                    conn.close()
            except Exception:
                pass
            duration = now_ms() - t_start
            writer.write(
                {
                    "type": "stream_disconnect",
                    "ts": iso_ts(),
                    "ts_ms": now_ms(),
                    "name": name,
                    "mode": "raw",
                    "duration_ms": duration,
                    "bytes": bytes_total,
                    "err": err,
                }
            )
        if stop:
            break
        time.sleep(0.5)


def download_worker(
    name: str,
    url: str,
    bytes_total: int,
    chunk_kb: int,
    sleep_ms: int,
    pattern: str,
    meta: int,
    interval_ms: int,
    timeout_ms: int,
    writer: RotatingWriter,
):
    # Monitor download progress.
    read_chunk = max(1, int(chunk_kb)) * 1024
    progress_every = max(100, int(interval_ms))
    while not stop:
        req_url = _merge_url_query(
            url,
            {
                "bytes": max(0, int(bytes_total)),
                "chunk_kb": max(1, int(chunk_kb)),
                "sleep_ms": max(0, int(sleep_ms)),
                "pattern": pattern,
                "meta": int(bool(meta)),
            },
        )
        parsed = urlparse(req_url)
        path = _target_path(parsed)
        conn = None
        status = None
        got = 0
        err = ""
        t_start = now_ms()
        last_progress_ts = t_start
        last_progress_bytes = 0
        writer.write(
            {
                "type": "download_start",
                "ts": iso_ts(),
                "ts_ms": t_start,
                "name": name,
                "url": req_url,
                "bytes_planned": max(0, int(bytes_total)),
            }
        )
        try:
            conn = _http_connection(parsed, timeout_ms=timeout_ms)
            conn.request("GET", path, headers={"Connection": "close", "Accept": "application/octet-stream"})
            resp = conn.getresponse()
            status = resp.status
            if resp.status >= 400:
                raise IOError(f"HTTP {resp.status}")

            while not stop:
                chunk = resp.read(read_chunk)
                if not chunk:
                    break
                got += len(chunk)
                now_t = now_ms()
                if now_t - last_progress_ts >= progress_every:
                    dt = max(1, now_t - last_progress_ts)
                    inst_bytes = max(0, got - last_progress_bytes)
                    writer.write(
                        {
                            "type": "download_progress",
                            "ts": iso_ts(),
                            "ts_ms": now_t,
                            "name": name,
                            "bytes_total": got,
                            "dt_ms": dt,
                            "inst_bps": round((inst_bytes * 1000.0) / dt, 3),
                        }
                    )
                    last_progress_ts = now_t
                    last_progress_bytes = got

            if stop:
                raise IOError("stopped")
            total_ms = now_ms() - t_start
            planned = max(0, int(bytes_total))
            if not stop and planned > 0 and got < planned:
                raise IOError(f"incomplete body: planned={planned} got={got}")
            avg_bps = round((got * 1000.0) / total_ms, 3) if total_ms > 0 else None
            writer.write(
                {
                    "type": "download_done",
                    "ts": iso_ts(),
                    "ts_ms": now_ms(),
                    "name": name,
                    "bytes_total": got,
                    "total_ms": total_ms,
                    "avg_bps": avg_bps,
                    "http_status": status,
                }
            )
        except Exception as e:
            err = str(e)
            duration = now_ms() - t_start
            writer.write(
                {
                    "type": "download_disconnect",
                    "ts": iso_ts(),
                    "ts_ms": now_ms(),
                    "name": name,
                    "bytes_total": got,
                    "duration_ms": duration,
                    "http_status": status,
                    "err": err,
                }
            )
        finally:
            try:
                if conn:
                    conn.close()
            except Exception:
                pass
        if stop:
            break
        time.sleep(0.5)


def upload_worker(
    name: str,
    url: str,
    bytes_total: int,
    chunk_kb: int,
    sink: str,
    sleep_ms: int,
    id_prefix: str,
    interval_ms: int,
    timeout_ms: int,
    writer: RotatingWriter,
):
    # Monitor upload progress.
    upload_bytes = max(0, int(bytes_total))
    send_chunk_size = max(1, int(chunk_kb)) * 1024
    send_chunk = b"\x00" * send_chunk_size
    progress_every = max(100, int(interval_ms))
    seq = 0
    while not stop:
        seq += 1
        req_id = f"{id_prefix}-{name}-{seq}"
        req_url = _merge_url_query(
            url,
            {
                "sink": sink,
                "chunk_kb": max(1, int(chunk_kb)),
                "sleep_ms": max(0, int(sleep_ms)),
                "id": req_id,
            },
        )
        parsed = urlparse(req_url)
        path = _target_path(parsed)
        conn = None
        sent = 0
        status = None
        server_rt_ms = None
        err = ""
        t_start = now_ms()
        last_progress_ts = t_start
        last_progress_bytes = 0
        writer.write(
            {
                "type": "upload_start",
                "ts": iso_ts(),
                "ts_ms": t_start,
                "name": name,
                "url": req_url,
                "bytes_planned": upload_bytes,
            }
        )
        try:
            conn = _http_connection(parsed, timeout_ms=timeout_ms)
            conn.putrequest("POST", path)
            conn.putheader("Connection", "close")
            conn.putheader("Content-Type", "application/octet-stream")
            conn.putheader("Content-Length", str(upload_bytes))
            conn.endheaders()

            while sent < upload_bytes and not stop:
                remaining = upload_bytes - sent
                to_send = min(send_chunk_size, remaining)
                conn.send(send_chunk[:to_send])
                sent += to_send
                now_t = now_ms()
                if now_t - last_progress_ts >= progress_every:
                    dt = max(1, now_t - last_progress_ts)
                    inst_bytes = max(0, sent - last_progress_bytes)
                    writer.write(
                        {
                            "type": "upload_progress",
                            "ts": iso_ts(),
                            "ts_ms": now_t,
                            "name": name,
                            "bytes_sent": sent,
                            "dt_ms": dt,
                            "inst_bps": round((inst_bytes * 1000.0) / dt, 3),
                        }
                    )
                    last_progress_ts = now_t
                    last_progress_bytes = sent

            if stop:
                raise IOError("stopped")
            if sent < upload_bytes:
                raise IOError(f"incomplete send: planned={upload_bytes} sent={sent}")

            resp = conn.getresponse()
            status = resp.status
            body = resp.read()
            try:
                parsed_body = json.loads(body.decode("utf-8"))
                if isinstance(parsed_body, dict):
                    server_rt_ms = parsed_body.get("rt_ms")
            except Exception:
                pass
            if status >= 400:
                raise IOError(f"HTTP {status}")

            total_ms = now_ms() - t_start
            avg_bps = round((sent * 1000.0) / total_ms, 3) if total_ms > 0 else None
            writer.write(
                {
                    "type": "upload_done",
                    "ts": iso_ts(),
                    "ts_ms": now_ms(),
                    "name": name,
                    "bytes_sent": sent,
                    "total_ms": total_ms,
                    "avg_bps": avg_bps,
                    "http_status": status,
                    "server_rt_ms": server_rt_ms,
                }
            )
        except Exception as e:
            err = str(e)
            duration = now_ms() - t_start
            writer.write(
                {
                    "type": "upload_disconnect",
                    "ts": iso_ts(),
                    "ts_ms": now_ms(),
                    "name": name,
                    "bytes_sent": sent,
                    "duration_ms": duration,
                    "http_status": status,
                    "err": err,
                }
            )
        finally:
            try:
                if conn:
                    conn.close()
            except Exception:
                pass
        if stop:
            break
        time.sleep(0.5)


def parse_kv_flag(items):
    # Parse key-value flag.
    d = {}
    for it in items or []:
        if "=" in it:
            k, v = it.split("=", 1)
            d[k] = v
    return d

def main():
    # Run the monitor CLI.
    signal.signal(signal.SIGINT, handle_sigint)
    signal.signal(signal.SIGTERM, handle_sigint)
    ap = argparse.ArgumentParser(description="CRIU migration multi-monitor")

    ap.add_argument("--url", help="(compat) single HTTP URL to poll")
    ap.add_argument("--interval-ms", type=int, default=250)
    ap.add_argument("--timeout-ms", type=int, default=2000)
    ap.add_argument("--format", choices=["csv","ndjson"], default="csv")
    ap.add_argument("--outfile", help="(compat) output file (single job)")


    ap.add_argument("--base-out", help="Base output path (directory/file prefix) for multi logs, e.g. /mnt/criu/logs/mon", default=None)
    ap.add_argument("--http-target", action="append", help="name=url  (repeatable)")
    ap.add_argument("--http-interval-ms", type=int, default=None)
    ap.add_argument("--http-timeout-ms", type=int, default=None)

    ap.add_argument("--l4-target", action="append", help="name=host:port  (repeatable)")
    ap.add_argument("--l4-interval-ms", type=int, default=250)
    ap.add_argument("--l4-timeout-ms", type=int, default=1000)

    ap.add_argument("--info-target", action="append", help="name=url_to_info  (repeatable)")
    ap.add_argument("--info-interval-ms", type=int, default=1000)

    ap.add_argument("--counter-target", action="append", help="name=url_to_counter  (repeatable)")
    ap.add_argument("--counter-interval-ms", type=int, default=1000)

    ap.add_argument("--stream-target", action="append", help="name=url_to_stream  (repeatable)")
    ap.add_argument("--stream-interval-ms", type=int, default=500)
    ap.add_argument("--stream-limit", type=int, default=None)
    ap.add_argument("--stream-format", choices=["ndjson", "raw"], default="ndjson")
    ap.add_argument("--stream-payload-kb", type=int, default=0)
    ap.add_argument("--stream-timeout-ms", type=int, default=10000)
    ap.add_argument("--stream-read-chunk-kb", type=int, default=64)
    ap.add_argument("--stream-progress-interval-ms", type=int, default=500)

    ap.add_argument("--download-target", action="append", help="name=url_to_download  (repeatable)")
    ap.add_argument("--download-bytes", type=int, default=10 * 1024 * 1024)
    ap.add_argument("--download-chunk-kb", type=int, default=64)
    ap.add_argument("--download-sleep-ms", type=int, default=0)
    ap.add_argument("--download-pattern", choices=["zero", "repeat", "random"], default="zero")
    ap.add_argument("--download-meta", type=int, choices=[0, 1], default=0)
    ap.add_argument("--download-interval-ms", type=int, default=500)
    ap.add_argument("--download-timeout-ms", type=int, default=10000)

    ap.add_argument("--upload-target", action="append", help="name=url_to_upload  (repeatable)")
    ap.add_argument("--upload-bytes", type=int, default=10 * 1024 * 1024)
    ap.add_argument("--upload-chunk-kb", type=int, default=64)
    ap.add_argument("--upload-sleep-ms", type=int, default=0)
    ap.add_argument("--upload-sink", choices=["discard", "file"], default="discard")
    ap.add_argument("--upload-id-prefix", default="monitor")
    ap.add_argument("--upload-interval-ms", type=int, default=500)
    ap.add_argument("--upload-timeout-ms", type=int, default=10000)

    ap.add_argument("--rotate-size-mb", type=int, default=50)
    ap.add_argument("--tag", action="append", help="key=value tags included in NDJSON rows", default=[])

    ap.add_argument("--analyze", action="store_true", help="Analyse-Modus: wertet Logs unter --base-out aus und gibt Kennzahlen aus")
    ap.add_argument("--events", help="Pfad zur Events-NDJSON aus dem Migrationsskript")
    ap.add_argument("--events-tail", help="Events-Datei, die im Lauf fuer Burst-Trigger getailt wird")
    ap.add_argument("--burst-window-ms", type=int, default=0, help="Burst-Fensterdauer in ms nach Trigger-Event")
    ap.add_argument("--burst-trigger-event", action="append", default=["vip_cutover_start"], help="Eventname, der Burst aktiviert (repeatable)")
    ap.add_argument("--burst-http-interval-ms", type=int, default=None, help="HTTP-Intervall im Burst-Fenster")
    ap.add_argument("--burst-l4-interval-ms", type=int, default=None, help="L4-Intervall im Burst-Fenster")

    args = ap.parse_args()
    tags = parse_kv_flag(args.tag)


    if args.analyze:
        if not args.base_out:
            print("ERROR: --base-out ist für --analyze erforderlich", file=sys.stderr)
            sys.exit(2)
        events_path = args.events or f"{args.base_out}-events.ndjson"
        rc = analyze_run(args.base_out, events_path=events_path)
        sys.exit(rc)

    burst_ctl = BurstController(
        events_path=args.events_tail,
        window_ms=args.burst_window_ms,
        trigger_events=args.burst_trigger_event,
    )
    burst_ctl.start()

    threads = []
    writers = []


    if (not args.base_out) and args.url and args.outfile:
        writer = RotatingWriter(args.outfile, args.rotate_size_mb, args.format)
        writers.append(writer)
        print(f"# Monitoring {args.url} every {args.interval_ms} ms (timeout {args.timeout_ms} ms). Writing to {args.outfile}", file=sys.stderr)
        t = threading.Thread(
            target=http_worker,
            args=("t0", args.url, args.interval_ms, args.timeout_ms, writer, args.format, tags, burst_ctl, args.burst_http_interval_ms),
            daemon=True,
        )
        t.start()
        threads.append(t)
    else:
        if not args.base_out:
            print("ERROR: --base-out is required in multi-target mode (or use legacy --url/--outfile).", file=sys.stderr)
            sys.exit(2)
        base = args.base_out
        base_dir = os.path.dirname(base) or "."
        os.makedirs(base_dir, exist_ok=True)


        if args.http_target:
            fmt = args.format
            http_file = f"{base}-http.{ 'csv' if fmt=='csv' else 'ndjson' }"
            http_writer = RotatingWriter(http_file, args.rotate_size_mb, 'csv' if fmt=='csv' else 'ndjson')
            writers.append(http_writer)
            hi = args.http_interval_ms or args.interval_ms
            ht = args.http_timeout_ms or args.timeout_ms
            for item in args.http_target:
                try:
                    name, url = item.split("=", 1)
                except ValueError:
                    print(f"Invalid --http-target '{item}', expected name=url", file=sys.stderr)
                    continue
                print(f"# HTTP target [{name}] {url} every {hi} ms (timeout {ht}) -> {http_file}", file=sys.stderr)
                th = threading.Thread(
                    target=http_worker,
                    args=(name, url, hi, ht, http_writer, fmt, tags, burst_ctl, args.burst_http_interval_ms),
                    daemon=True,
                )
                th.start()
                threads.append(th)


        if args.l4_target:
            l4_file = f"{base}-l4.csv"
            l4_writer = RotatingWriter(l4_file, args.rotate_size_mb, "csv")
            writers.append(l4_writer)
            for item in args.l4_target:
                try:
                    name, hp = item.split("=", 1)
                    host, port_s = hp.rsplit(":", 1)
                    port = int(port_s)
                except Exception:
                    print(f"Invalid --l4-target '{item}', expected name=host:port", file=sys.stderr)
                    continue
                print(f"# L4 target [{name}] {host}:{port} every {args.l4_interval_ms} ms (timeout {args.l4_timeout_ms}) -> {l4_file}", file=sys.stderr)
                th = threading.Thread(
                    target=l4_worker,
                    args=(name, host, port, args.l4_interval_ms, args.l4_timeout_ms, l4_writer, burst_ctl, args.burst_l4_interval_ms),
                    daemon=True,
                )
                th.start()
                threads.append(th)


        if args.info_target:
            info_file = f"{base}-info.ndjson"
            info_writer = RotatingWriter(info_file, args.rotate_size_mb, "ndjson")
            writers.append(info_writer)
            for item in args.info_target:
                try:
                    name, url = item.split("=", 1)
                except ValueError:
                    print(f"Invalid --info-target '{item}', expected name=url", file=sys.stderr)
                    continue
                print(f"# INFO target [{name}] {url} every {args.info_interval_ms} ms -> {info_file}", file=sys.stderr)
                th = threading.Thread(target=info_worker, args=(name, url, args.info_interval_ms, args.timeout_ms, info_writer, tags), daemon=True)
                th.start()
                threads.append(th)


        if args.counter_target:
            fmt = args.format
            ctr_file = f"{base}-counter.{ 'csv' if fmt=='csv' else 'ndjson' }"
            ctr_writer = RotatingWriter(ctr_file, args.rotate_size_mb, 'csv' if fmt=='csv' else 'ndjson')
            writers.append(ctr_writer)
            for item in args.counter_target:
                try:
                    name, url = item.split("=", 1)
                except ValueError:
                    print(f"Invalid --counter-target '{item}', expected name=url", file=sys.stderr)
                    continue
                print(f"# COUNTER target [{name}] {url} every {args.counter_interval_ms} ms -> {ctr_file}", file=sys.stderr)
                th = threading.Thread(target=counter_worker, args=(name, url, args.counter_interval_ms, args.timeout_ms, ctr_writer, args.format), daemon=True)
                th.start()
                threads.append(th)


        if args.stream_target:
            stream_file = f"{base}-stream.ndjson"
            stream_writer = RotatingWriter(stream_file, args.rotate_size_mb, "ndjson")
            writers.append(stream_writer)
            for item in args.stream_target:
                try:
                    name, url = item.split("=", 1)
                except ValueError:
                    print(f"Invalid --stream-target '{item}', expected name=url", file=sys.stderr)
                    continue
                print(
                    f"# STREAM target [{name}] {url} (format={args.stream_format}, interval_ms={args.stream_interval_ms}, "
                    f"payload_kb={args.stream_payload_kb}, limit={args.stream_limit}) -> {stream_file}",
                    file=sys.stderr,
                )
                if args.stream_format == "raw":
                    th = threading.Thread(
                        target=raw_stream_worker,
                        args=(
                            name,
                            url,
                            args.stream_interval_ms,
                            args.stream_limit,
                            args.stream_payload_kb,
                            args.stream_read_chunk_kb,
                            args.stream_timeout_ms,
                            args.stream_progress_interval_ms,
                            stream_writer,
                        ),
                        daemon=True,
                    )
                else:
                    th = threading.Thread(
                        target=stream_worker,
                        args=(
                            name,
                            url,
                            args.stream_interval_ms,
                            args.stream_limit,
                            args.stream_payload_kb,
                            stream_writer,
                            args.stream_timeout_ms,
                            args.stream_progress_interval_ms,
                        ),
                        daemon=True,
                    )
                th.start()
                threads.append(th)


        if args.download_target:
            download_file = f"{base}-download.ndjson"
            download_writer = RotatingWriter(download_file, args.rotate_size_mb, "ndjson")
            writers.append(download_writer)
            for item in args.download_target:
                try:
                    name, url = item.split("=", 1)
                except ValueError:
                    print(f"Invalid --download-target '{item}', expected name=url", file=sys.stderr)
                    continue
                print(
                    f"# DOWNLOAD target [{name}] {url} (bytes={args.download_bytes}, chunk_kb={args.download_chunk_kb}, "
                    f"pattern={args.download_pattern}, interval_ms={args.download_interval_ms}) -> {download_file}",
                    file=sys.stderr,
                )
                th = threading.Thread(
                    target=download_worker,
                    args=(
                        name,
                        url,
                        args.download_bytes,
                        args.download_chunk_kb,
                        args.download_sleep_ms,
                        args.download_pattern,
                        args.download_meta,
                        args.download_interval_ms,
                        args.download_timeout_ms,
                        download_writer,
                    ),
                    daemon=True,
                )
                th.start()
                threads.append(th)


        if args.upload_target:
            upload_file = f"{base}-upload.ndjson"
            upload_writer = RotatingWriter(upload_file, args.rotate_size_mb, "ndjson")
            writers.append(upload_writer)
            for item in args.upload_target:
                try:
                    name, url = item.split("=", 1)
                except ValueError:
                    print(f"Invalid --upload-target '{item}', expected name=url", file=sys.stderr)
                    continue
                print(
                    f"# UPLOAD target [{name}] {url} (bytes={args.upload_bytes}, chunk_kb={args.upload_chunk_kb}, "
                    f"sink={args.upload_sink}, interval_ms={args.upload_interval_ms}) -> {upload_file}",
                    file=sys.stderr,
                )
                th = threading.Thread(
                    target=upload_worker,
                    args=(
                        name,
                        url,
                        args.upload_bytes,
                        args.upload_chunk_kb,
                        args.upload_sink,
                        args.upload_sleep_ms,
                        args.upload_id_prefix,
                        args.upload_interval_ms,
                        args.upload_timeout_ms,
                        upload_writer,
                    ),
                    daemon=True,
                )
                th.start()
                threads.append(th)


    try:
        while not stop:
            time.sleep(0.2)
    finally:


        join_worker_threads(threads, timeout_s=5.0)
        for w in writers:
            w.close()

if __name__ == "__main__":
    main()
