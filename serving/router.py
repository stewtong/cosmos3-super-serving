#!/usr/bin/env python3
"""Bounded node-local router for synchronous Cosmos3-Super video requests."""

import argparse
import http.client
import json
import os
import signal
import tempfile
import threading
import time
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Optional
from urllib.parse import urlsplit

MAX_REQUEST_BYTES = 16 * 1024 * 1024


@dataclass
class Backend:
    name: str
    url: str
    healthy: bool = True
    active: int = 0
    completed: int = 0
    failed: int = 0
    last_latency_s: Optional[float] = None
    semaphore: threading.BoundedSemaphore = field(
        default_factory=lambda: threading.BoundedSemaphore(1), repr=False
    )


class RouterState:
    def __init__(self, backends, *, profile, topology, queue_limit, queue_timeout_s,
                 backend_timeout_s, run_id, health_interval_s=10.0,
                 model_revision=None, container_digest=None, runtime_identity=None,
                 guardrails=False):
        self.backends = [Backend(f"r{index}", url) for index, url in enumerate(backends)]
        self.profile = profile
        self.topology = topology
        self.queue_limit = queue_limit
        self.queue_timeout_s = queue_timeout_s
        self.backend_timeout_s = backend_timeout_s
        self.run_id = run_id
        self.health_interval_s = health_interval_s
        self.model_revision = model_revision
        self.container_digest = container_digest
        self.runtime_identity = runtime_identity
        self.guardrails = guardrails
        self.condition = threading.Condition()
        self.cursor = 0
        self.queue_depth = 0
        self.counters = {
            "admitted": 0,
            "completed": 0,
            "rejected": 0,
            "timed_out": 0,
            "failed": 0,
        }
        self.started_monotonic = time.monotonic()
        self.stopping = threading.Event()

    def acquire_backend(self):
        deadline = time.monotonic() + self.queue_timeout_s
        queued = False
        with self.condition:
            while True:
                count = len(self.backends)
                for offset in range(count):
                    index = (self.cursor + offset) % count
                    backend = self.backends[index]
                    if backend.healthy and backend.semaphore.acquire(blocking=False):
                        backend.active += 1
                        self.cursor = (index + 1) % count
                        self.counters["admitted"] += 1
                        if queued:
                            self.queue_depth -= 1
                        return backend, None

                if not any(backend.healthy for backend in self.backends):
                    if queued:
                        self.queue_depth -= 1
                    self.counters["rejected"] += 1
                    return None, "unavailable"

                if not queued:
                    if self.queue_depth >= self.queue_limit:
                        self.counters["rejected"] += 1
                        return None, "queue_full"
                    self.queue_depth += 1
                    queued = True

                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    self.queue_depth -= 1
                    self.counters["timed_out"] += 1
                    return None, "queue_timeout"
                self.condition.wait(timeout=remaining)

    def release_backend(self, backend, *, success, latency_s):
        with self.condition:
            backend.active -= 1
            backend.last_latency_s = round(latency_s, 3)
            if success:
                backend.completed += 1
                self.counters["completed"] += 1
            else:
                backend.failed += 1
                self.counters["failed"] += 1
            backend.semaphore.release()
            self.condition.notify_all()

    def set_health(self, backend, healthy):
        with self.condition:
            backend.healthy = healthy
            self.condition.notify_all()

    def snapshot(self):
        with self.condition:
            return {
                "run_id": self.run_id,
                "profile": self.profile,
                "topology": self.topology,
                "model_revision": self.model_revision,
                "container_digest": self.container_digest,
                "runtime_identity": self.runtime_identity,
                "guardrails": self.guardrails,
                "policy": "round_robin_idle",
                "active_requests_per_replica": 1,
                "queue_depth": self.queue_depth,
                "queue_limit": self.queue_limit,
                "queue_timeout_seconds": self.queue_timeout_s,
                "healthy_replicas": sum(backend.healthy for backend in self.backends),
                "unavailable_replicas": sum(not backend.healthy for backend in self.backends),
                "counters": dict(self.counters),
                "uptime_seconds": round(time.monotonic() - self.started_monotonic, 1),
                "replicas": [
                    {
                        "name": backend.name,
                        "healthy": backend.healthy,
                        "active": backend.active,
                        "completed": backend.completed,
                        "failed": backend.failed,
                        "last_backend_latency_seconds": backend.last_latency_s,
                    }
                    for backend in self.backends
                ],
            }

    def health_loop(self):
        while not self.stopping.wait(self.health_interval_s):
            for backend in self.backends:
                healthy = check_backend(backend.url, min(self.backend_timeout_s, 10))
                self.set_health(backend, healthy)


def check_backend(base_url, timeout_s):
    parsed = urlsplit(base_url)
    connection = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=timeout_s)
    try:
        connection.request("GET", "/health")
        response = connection.getresponse()
        response.read()
        return 200 <= response.status < 300
    except (OSError, http.client.HTTPException, TimeoutError):
        return False
    finally:
        connection.close()


def forward_request(backend_url, handler, timeout_s):
    parsed = urlsplit(backend_url)
    length = int(handler.headers.get("Content-Length", "0"))
    request_body = handler.rfile.read(length)
    headers = {
        "Accept": handler.headers.get("Accept", "video/mp4"),
        "Content-Type": handler.headers.get("Content-Type", "application/octet-stream"),
        "Content-Length": str(len(request_body)),
    }
    connection = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=timeout_s)
    response_file = tempfile.SpooledTemporaryFile(max_size=16 * 1024 * 1024)
    try:
        connection.request("POST", "/v1/videos/sync", body=request_body, headers=headers)
        response = connection.getresponse()
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            response_file.write(chunk)
        response_file.seek(0, os.SEEK_END)
        response_length = response_file.tell()
        response_file.seek(0)
        return response.status, response.getheader("Content-Type", "application/octet-stream"), response_length, response_file
    except Exception:
        response_file.close()
        raise
    finally:
        connection.close()


class RouterHandler(BaseHTTPRequestHandler):
    server_version = "cosmos3-super-router/1"

    @property
    def state(self):
        return self.server.router_state

    def log_message(self, format_string, *args):
        print(f"router {self.address_string()} {format_string % args}")

    def send_json(self, status, payload):
        encoded = json.dumps(payload, sort_keys=True).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def do_GET(self):
        if self.path == "/status":
            self.send_json(200, self.state.snapshot())
            return
        if self.path == "/healthz":
            snapshot = self.state.snapshot()
            status = 200 if snapshot["healthy_replicas"] else 503
            self.send_json(status, {
                "healthy": bool(snapshot["healthy_replicas"]),
                "healthy_replicas": snapshot["healthy_replicas"],
                "configured_replicas": len(snapshot["replicas"]),
            })
            return
        if self.path == "/metrics":
            self.send_json(200, self.state.snapshot())
            return
        self.send_error(404)

    def do_POST(self):
        if self.path != "/v1/videos/sync":
            self.send_error(404)
            return
        try:
            content_length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self.send_json(400, {"error": "invalid content length"})
            return
        if content_length <= 0:
            self.send_json(400, {"error": "request body is required"})
            return
        if content_length > MAX_REQUEST_BYTES:
            self.send_json(413, {"error": "request body exceeds router limit"})
            return
        backend, failure = self.state.acquire_backend()
        if failure == "queue_full":
            self.send_json(429, {"error": "node queue is full"})
            return
        if failure == "queue_timeout":
            self.send_json(504, {"error": "node queue timeout"})
            return
        if failure == "unavailable":
            self.send_json(503, {"error": "no healthy replica is available"})
            return

        started = time.monotonic()
        success = False
        response_file = None
        try:
            status, content_type, length, response_file = forward_request(
                backend.url, self, self.state.backend_timeout_s
            )
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(length))
            self.end_headers()
            while True:
                chunk = response_file.read(1024 * 1024)
                if not chunk:
                    break
                self.wfile.write(chunk)
            success = 200 <= status < 300
        except (OSError, http.client.HTTPException, TimeoutError):
            self.state.set_health(backend, False)
            self.send_json(502, {
                "error": "backend request failed after dispatch",
                "retry": "not attempted",
            })
        finally:
            if response_file is not None:
                response_file.close()
            self.state.release_backend(
                backend, success=success, latency_s=time.monotonic() - started
            )


class RouterServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, state):
        super().__init__(address, RouterHandler)
        self.router_state = state


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1", choices=["127.0.0.1", "localhost"])
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--backends", required=True, help="comma-separated loopback base URLs")
    parser.add_argument("--profile", required=True)
    parser.add_argument("--topology", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--queue-limit", type=int, default=8)
    parser.add_argument("--queue-timeout", type=float, default=900)
    parser.add_argument("--backend-timeout", type=float, default=5400)
    parser.add_argument("--health-interval", type=float, default=10)
    parser.add_argument("--model-revision")
    parser.add_argument("--container-digest")
    parser.add_argument("--runtime-identity")
    parser.add_argument("--guardrails", action="store_true")
    args = parser.parse_args()
    if args.queue_limit < 0 or args.queue_timeout <= 0 or args.backend_timeout <= 0:
        parser.error("queue limit must be nonnegative and timeouts must be positive")

    backends = [value.strip() for value in args.backends.split(",") if value.strip()]
    if not backends:
        parser.error("at least one backend is required")
    for backend in backends:
        parsed = urlsplit(backend)
        if parsed.hostname not in {"127.0.0.1", "localhost"} or not parsed.port:
            parser.error("every backend must be an explicit loopback URL with a port")

    state = RouterState(
        backends,
        profile=args.profile,
        topology=args.topology,
        queue_limit=args.queue_limit,
        queue_timeout_s=args.queue_timeout,
        backend_timeout_s=args.backend_timeout,
        run_id=args.run_id,
        health_interval_s=args.health_interval,
        model_revision=args.model_revision,
        container_digest=args.container_digest,
        runtime_identity=args.runtime_identity,
        guardrails=args.guardrails,
    )
    for backend in state.backends:
        backend.healthy = check_backend(backend.url, min(args.backend_timeout, 10))

    server = RouterServer((args.host, args.port), state)
    checker = threading.Thread(target=state.health_loop, daemon=True)
    checker.start()

    def stop_server(_signum, _frame):
        state.stopping.set()
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, stop_server)
    signal.signal(signal.SIGINT, stop_server)
    try:
        server.serve_forever()
    finally:
        state.stopping.set()
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
