import threading
import time
import unittest
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from serving.router import RouterServer, RouterState


class FakeBackendHandler(BaseHTTPRequestHandler):
    def log_message(self, _format, *_args):
        return

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        self.rfile.read(length)
        payload = b"video"
        self.send_response(200)
        self.send_header("Content-Type", "video/mp4")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


class RouterStateTests(unittest.TestCase):
    def test_round_robin_assigns_idle_replicas(self):
        state = RouterState(
            ["http://127.0.0.1:8100", "http://127.0.0.1:8101"],
            profile="throughput", topology="2x4", queue_limit=1,
            queue_timeout_s=1, backend_timeout_s=2, run_id="test",
        )
        first, failure = state.acquire_backend()
        second, failure_two = state.acquire_backend()
        self.assertIsNone(failure)
        self.assertIsNone(failure_two)
        self.assertEqual((first.name, second.name), ("r0", "r1"))
        state.release_backend(first, success=True, latency_s=1)
        state.release_backend(second, success=True, latency_s=1)

    def test_queue_limit_rejects_excess_request(self):
        state = RouterState(
            ["http://127.0.0.1:8100"], profile="latency", topology="1x8",
            queue_limit=1, queue_timeout_s=1, backend_timeout_s=2, run_id="test",
        )
        backend, _ = state.acquire_backend()
        waiting = {}

        def wait_for_backend():
            waiting["result"] = state.acquire_backend()

        thread = threading.Thread(target=wait_for_backend)
        thread.start()
        deadline = time.monotonic() + 1
        while state.snapshot()["queue_depth"] != 1 and time.monotonic() < deadline:
            time.sleep(0.005)
        extra, failure = state.acquire_backend()
        self.assertIsNone(extra)
        self.assertEqual(failure, "queue_full")
        state.release_backend(backend, success=True, latency_s=1)
        thread.join(timeout=1)
        self.assertIsNotNone(waiting["result"][0])
        state.release_backend(waiting["result"][0], success=True, latency_s=1)

    def test_queue_timeout_is_distinct(self):
        state = RouterState(
            ["http://127.0.0.1:8100"], profile="latency", topology="1x8",
            queue_limit=1, queue_timeout_s=0.02, backend_timeout_s=2, run_id="test",
        )
        backend, _ = state.acquire_backend()
        selected, failure = state.acquire_backend()
        self.assertIsNone(selected)
        self.assertEqual(failure, "queue_timeout")
        state.release_backend(backend, success=True, latency_s=1)

    def test_unhealthy_capacity_rejects_before_dispatch(self):
        state = RouterState(
            ["http://127.0.0.1:8100"], profile="latency", topology="1x8",
            queue_limit=1, queue_timeout_s=1, backend_timeout_s=2, run_id="test",
        )
        state.set_health(state.backends[0], False)
        backend, failure = state.acquire_backend()
        self.assertIsNone(backend)
        self.assertEqual(failure, "unavailable")
        self.assertEqual(state.snapshot()["healthy_replicas"], 0)

    def test_snapshot_excludes_backend_addresses(self):
        state = RouterState(
            ["http://127.0.0.1:8100"], profile="latency", topology="1x8",
            queue_limit=1, queue_timeout_s=1, backend_timeout_s=2, run_id="test",
        )
        snapshot = state.snapshot()
        self.assertNotIn("url", snapshot["replicas"][0])
        self.assertEqual(snapshot["active_requests_per_replica"], 1)

    def test_failure_updates_counter_without_requeue(self):
        state = RouterState(
            ["http://127.0.0.1:8100"], profile="latency", topology="1x8",
            queue_limit=1, queue_timeout_s=1, backend_timeout_s=2, run_id="test",
        )
        backend, _ = state.acquire_backend()
        state.release_backend(backend, success=False, latency_s=3)
        snapshot = state.snapshot()
        self.assertEqual(snapshot["counters"]["admitted"], 1)
        self.assertEqual(snapshot["counters"]["failed"], 1)
        self.assertEqual(snapshot["replicas"][0]["failed"], 1)

    def test_http_router_preserves_success_response(self):
        backend_server = ThreadingHTTPServer(("127.0.0.1", 0), FakeBackendHandler)
        backend_thread = threading.Thread(target=backend_server.serve_forever, daemon=True)
        backend_thread.start()
        backend_url = f"http://127.0.0.1:{backend_server.server_port}"
        state = RouterState(
            [backend_url], profile="latency", topology="1x8",
            queue_limit=1, queue_timeout_s=1, backend_timeout_s=2,
            run_id="test", model_revision="revision", container_digest="digest",
            runtime_identity="runtime",
        )
        router_server = RouterServer(("127.0.0.1", 0), state)
        router_thread = threading.Thread(target=router_server.serve_forever, daemon=True)
        router_thread.start()
        try:
            request = urllib.request.Request(
                f"http://127.0.0.1:{router_server.server_port}/v1/videos/sync",
                data=b"request",
                method="POST",
                headers={"Content-Type": "multipart/form-data", "Accept": "video/mp4"},
            )
            with urllib.request.urlopen(request, timeout=2) as response:
                self.assertEqual(response.status, 200)
                self.assertEqual(response.headers["Content-Type"], "video/mp4")
                self.assertEqual(response.read(), b"video")
            snapshot = state.snapshot()
            self.assertEqual(snapshot["counters"]["completed"], 1)
            self.assertEqual(snapshot["model_revision"], "revision")
            self.assertEqual(snapshot["container_digest"], "digest")
        finally:
            router_server.shutdown()
            router_server.server_close()
            backend_server.shutdown()
            backend_server.server_close()


if __name__ == "__main__":
    unittest.main()
