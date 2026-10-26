from __future__ import annotations

import base64
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from btcs_pool.rpc import BTCSRpc, RPCError


class RpcFixture:
    def __init__(self):
        self.requests: list[dict] = []
        self.fail_auth = False
        self.chain = {
            "chain": "regtest",
            "blocks": 123,
            "headers": 123,
            "verificationprogress": 1.0,
            "initialblockdownload": False,
            "difficulty": 4.65e-10,
            "warnings": [],
        }
        self.network = {"connections": 3, "warnings": ["test warning"]}
        self.mempool = {"size": 2}
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                return

            def do_POST(self):
                length = int(self.headers.get("Content-Length", "0"))
                payload = json.loads(self.rfile.read(length))
                outer.requests.append(
                    {
                        "path": self.path,
                        "headers": dict(self.headers),
                        "payload": payload,
                    }
                )
                authorization = self.headers.get("Authorization", "")
                expected = "Basic " + base64.b64encode(b"user:pass").decode()
                if outer.fail_auth or authorization != expected:
                    body = json.dumps({"error": {"code": -32600, "message": "unauthorized"}}).encode()
                    self.send_response(401)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return

                method = payload.get("method")
                if method == "getblockchaininfo":
                    result = outer.chain
                elif method == "getnetworkinfo":
                    result = outer.network
                elif method == "getmempoolinfo":
                    result = outer.mempool
                elif method == "getblockcount":
                    result = 123
                elif method == "getblockhash":
                    result = "aa" * 32
                elif method == "submitblock":
                    result = None
                elif method == "unknown":
                    result = None
                    body = json.dumps(
                        {"result": None, "error": {"code": -32601, "message": "no such method"}}
                    ).encode()
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
                else:
                    result = payload.get("params")
                body = json.dumps({"result": result, "error": None}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)


@pytest.fixture()
def rpc_fixture():
    fixture = RpcFixture()
    try:
        yield fixture
    finally:
        fixture.close()


def test_rpc_success_auth_and_wallet_path(rpc_fixture):
    rpc = BTCSRpc(rpc_fixture.url, "user", "pass", "pool")
    assert rpc.getblockcount() == 123
    assert rpc.getblockhash(100) == "aa" * 32
    assert rpc.submitblock("00") is None
    assert rpc.call_wallet("getnewaddress", ["label"]) == ["label"]
    assert rpc_fixture.requests[0]["path"] == "/"
    assert rpc_fixture.requests[-1]["path"] == "/wallet/pool"
    assert rpc_fixture.requests[0]["payload"]["jsonrpc"] == "2.0"
    assert rpc_fixture.requests[0]["payload"]["method"] == "getblockcount"
    assert rpc_fixture.requests[1]["payload"]["method"] == "getblockhash"
    assert rpc_fixture.requests[1]["payload"]["params"] == [100]


def test_rpc_getblocktemplate_uses_segwit_rules(rpc_fixture):
    rpc = BTCSRpc(rpc_fixture.url, "user", "pass")
    result = rpc.getblocktemplate(["segwit"])
    assert result == [{"rules": ["segwit"]}]
    assert rpc_fixture.requests[-1]["payload"]["method"] == "getblocktemplate"


def test_rpc_returns_domain_error(rpc_fixture):
    rpc = BTCSRpc(rpc_fixture.url, "user", "pass")
    with pytest.raises(RPCError) as excinfo:
        rpc.call_base("unknown")
    assert excinfo.value.code == -32601
    assert "no such method" in str(excinfo.value)


def test_rpc_http_auth_error(rpc_fixture):
    rpc_fixture.fail_auth = True
    rpc = BTCSRpc(rpc_fixture.url, "user", "wrong")
    with pytest.raises(RPCError) as excinfo:
        rpc.getblockchaininfo()
    assert "unauthorized" in str(excinfo.value)


def test_rpc_connection_failure():
    rpc = BTCSRpc("http://127.0.0.1:1", "user", "pass", timeout=0.5)
    with pytest.raises(RPCError) as excinfo:
        rpc.getblockchaininfo()
    assert "connection failed" in str(excinfo.value)


def test_rpc_wallet_requires_configuration():
    rpc = BTCSRpc("http://127.0.0.1:1", "user", "pass", "")
    with pytest.raises(RPCError, match="no wallet configured"):
        rpc.call_wallet("getnewaddress")
