import base64
import json
import urllib.request
from typing import Any


class BTCSRpc:
    def __init__(self, url: str, user: str, password: str, wallet: str = ""):
        self.url = url.rstrip("/")
        self.user = user
        self.password = password
        self.wallet = wallet

    def _endpoint(self) -> str:
        if self.wallet:
            return f"{self.url}/wallet/{self.wallet}"
        return self.url

    def call(self, method: str, params: list | None = None) -> Any:
        payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params or []}
        data = json.dumps(payload).encode()
        req = urllib.request.Request(self._endpoint(), data=data, headers={"Content-Type": "application/json"})
        creds = base64.b64encode(f"{self.user}:{self.password}".encode()).decode()
        req.add_header("Authorization", f"Basic {creds}")
        with urllib.request.urlopen(req, timeout=30) as resp:
            obj = json.loads(resp.read().decode())
        if obj.get("error"):
            raise RuntimeError(f"RPC {method} error: {obj['error']}")
        return obj["result"]

    def getblocktemplate(self, rules=None):
        params = [{}]
        if rules:
            params = [{"rules": rules}]
        return self.call("getblocktemplate", params)

    def getblockchaininfo(self):
        return self.call("getblockchaininfo")

    def submitblock(self, block_hex: str):
        return self.call("submitblock", [block_hex])

    def getaddressinfo(self, address: str):
        return self.call("getaddressinfo", [address])

    def getnewaddress(self, label: str = ""):
        return self.call("getnewaddress", [label])

    def generatetoaddress(self, n: int, address: str):
        return self.call("generatetoaddress", [n, address])
