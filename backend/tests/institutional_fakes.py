"""In-process fakes of the SoSoValue and CoinGecko treasury endpoints — FOR TESTS ONLY.

They serve the synthetic historical fixtures in ``tests/fixtures/institutional`` (documented
response shapes, hand-designed values — see that folder's README) through
``httpx2.MockTransport`` to the real adapters and the real HTTP client.
"""

from __future__ import annotations

import copy
import json
import re
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx2

FIXTURES = Path(__file__).parent / "fixtures" / "institutional"


def fixture(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text())


def _json(obj: object, status: int = 200) -> httpx2.Response:
    return httpx2.Response(
        status, content=json.dumps(obj).encode(), headers={"content-type": "application/json"}
    )


@dataclass
class SoSoValueFake:
    """Serves the fixtures; tests edit ``files`` (a deep copy) to simulate changes."""

    files: dict[str, Any] = field(default_factory=dict)
    script: deque[httpx2.Response] = field(default_factory=deque)
    requests: list[httpx2.Request] = field(default_factory=list)

    FUND = re.compile(r"^/openapi/v1/etfs/(?P<t>[^/]+)/history$")
    PURCHASES = re.compile(r"^/openapi/v1/btc-treasuries/(?P<t>[^/]+)/purchase-history$")

    def __post_init__(self) -> None:
        if not self.files:
            self.files = {p.name: fixture(p.name) for p in FIXTURES.glob("sosovalue_*.json")}

    def transport(self) -> httpx2.MockTransport:
        return httpx2.MockTransport(self._handle)

    def data(self, name: str) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = self.files[name]["data"]
        return rows

    async def _handle(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        if self.script:
            return self.script.popleft()
        if request.headers.get("x-soso-api-key") != "test-key":
            return _json({"code": 400101, "message": "Invalid API Key", "data": None}, 401)
        path = request.url.path
        q = request.url.params
        name = None
        if path == "/openapi/v1/etfs/summary-history":
            name = f"sosovalue_etf_summary_{q['symbol']}.json"
        elif path == "/openapi/v1/etfs":
            name = f"sosovalue_etf_list_{q['symbol']}.json"
        elif path == "/openapi/v1/btc-treasuries":
            name = "sosovalue_btc_treasuries.json"
        elif match := self.FUND.match(path):
            name = f"sosovalue_etf_history_{match['t']}.json"
        elif match := self.PURCHASES.match(path):
            name = f"sosovalue_purchase_history_{match['t']}.json"
            body = copy.deepcopy(self.files.get(name))
            if body is not None and "end_date" in q:
                body["data"] = [r for r in body["data"] if r["date"] <= q["end_date"]]
            if body is not None:
                body["data"] = body["data"][: int(q.get("limit", "50"))]
                return _json(body)
        if name is None or name not in self.files:
            return _json({"code": 400003, "message": "Invalid parameter value", "data": None}, 400)
        return _json(self.files[name])


@dataclass
class CoinGeckoTreasuryFake:
    body: dict[str, Any] = field(
        default_factory=lambda: fixture("coingecko_public_treasury_bitcoin.json")
    )
    requests: list[httpx2.Request] = field(default_factory=list)

    def transport(self) -> httpx2.MockTransport:
        return httpx2.MockTransport(self._handle)

    async def _handle(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        if request.url.path.startswith("/api/v3/companies/public_treasury/"):
            return _json(self.body)
        return _json({"error": "not found"}, 404)
