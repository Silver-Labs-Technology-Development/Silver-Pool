from __future__ import annotations

import base64
import json
import logging
import urllib.error
import urllib.request
from typing import Any

log = logging.getLogger(__name__)


class RPCError(RuntimeError):
    def __init__(self, method: str, message: str, code: int | None = None):
        super().__init__(f"RPC {method} failed: {message}")
        self.method = method
        self.code = code


class BTCSRpc:
    """Minimal authenticated JSON-RPC client for the real BTCS Core daemon."""

    def __init__(
        self,
        url: str,
        user: str,
        password: str,
        wallet: str = "",
        timeout: float = 30.0,
    ):
        self.url = url.rstrip("/")
        self.user = user
        self.password = password
        self.wallet = wallet
        self.timeout = timeout

    def _endpoint(self, wallet: str | None) -> str:
        if wallet:
            return f"{self.url}/wallet/{wallet}"
        return self.url

    def _request(self, method: str, params: list | None, wallet: str | None) -> Any:
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": method,
            "params": params or [],
        }
        data = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            self._endpoint(wallet),
            data=data,
            headers={"Content-Type": "application/json"},
        )
        credentials = base64.b64encode(
            f"{self.user}:{self.password}".encode("utf-8")
        ).decode("ascii")
        request.add_header("Authorization", f"Basic {credentials}")
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                body = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            try:
                obj = json.loads(body)
                error = obj.get("error") or {}
                raise RPCError(
                    method,
                    error.get("message", f"HTTP {exc.code}"),
                    error.get("code"),
                ) from exc
            except (ValueError, AttributeError):
                raise RPCError(method, f"HTTP {exc.code}: {body[:300]}") from exc
        except urllib.error.URLError as exc:
            raise RPCError(method, f"connection failed: {exc.reason}") from exc
        except TimeoutError as exc:
            raise RPCError(method, "request timed out") from exc

        try:
            obj = json.loads(body)
        except ValueError as exc:
            raise RPCError(method, "invalid JSON response") from exc
        if obj.get("error"):
            error = obj["error"]
            raise RPCError(
                method,
                error.get("message", str(error)),
                error.get("code"),
            )
        return obj.get("result")

    def call(self, method: str, params: list | None = None, wallet: bool | None = None) -> Any:
        use_wallet = self.wallet if wallet is None else (self.wallet if wallet else None)
        return self._request(method, params, use_wallet)

    def call_base(self, method: str, params: list | None = None) -> Any:
        return self._request(method, params, None)

    def call_wallet(self, method: str, params: list | None = None) -> Any:
        if not self.wallet:
            raise RPCError(method, "no wallet configured")
        return self._request(method, params, self.wallet)

    # Node methods -----------------------------------------------------
    def getblocktemplate(self, rules: list[str] | None = None):
        return self.call_base(
            "getblocktemplate",
            [{"rules": rules or ["segwit"]}],
        )

    def getblockchaininfo(self):
        return self.call_base("getblockchaininfo")

    def getnetworkinfo(self):
        return self.call_base("getnetworkinfo")

    def getmempoolinfo(self):
        return self.call_base("getmempoolinfo")

    def getblockcount(self) -> int:
        return int(self.call_base("getblockcount"))

    def getbestblockhash(self) -> str:
        return self.call_base("getbestblockhash")

    def getblockhash(self, height: int) -> str:
        return self.call_base("getblockhash", [int(height)])

    def getblock(self, block_hash: str, verbosity: int = 1):
        return self.call_base("getblock", [block_hash, verbosity])

    def submitblock(self, block_hex: str):
        return self.call_base("submitblock", [block_hex])

    def getaddressinfo(self, address: str):
        return self.call_wallet("getaddressinfo", [address])

    def validateaddress(self, address: str):
        return self.call_base("validateaddress", [address])

    # Wallet methods ---------------------------------------------------
    def listwallets(self) -> list[str]:
        return list(self.call_base("listwallets"))

    def ensure_wallet(self) -> None:
        if not self.wallet:
            return
        wallets = self.listwallets()
        if self.wallet in wallets:
            return
        try:
            self.call_base("loadwallet", [self.wallet])
            log.info("wallet_loaded name=%s", self.wallet)
            return
        except RPCError:
            pass
        try:
            self.call_base("createwallet", [self.wallet])
            log.info("wallet_created name=%s", self.wallet)
        except RPCError as exc:
            if "already exists" not in str(exc):
                raise

    def getnewaddress(self, label: str = "") -> str:
        return self.call_wallet("getnewaddress", [label])

    def getwalletinfo(self):
        return self.call_wallet("getwalletinfo")

    def sendtoaddress(self, address: str, amount: float, comment: str = ""):
        return self.call_wallet("sendtoaddress", [address, amount, comment])

    def generatetoaddress(self, n: int, address: str):
        return self.call_base("generatetoaddress", [int(n), address])
