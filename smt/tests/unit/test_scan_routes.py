from unittest.mock import AsyncMock

import pytest

from smt.main import app
from smt.services.dependencies import get_market_scan_service
from smt.worker.arq import get_arq_service


def finished(scan_id="scan-1", status="done"):
    return {
        "id": scan_id,
        "status": status,
        "collected": 1,
        "measured": 1,
        "error": "",
        "started_at": "2026-09-10T00:00:00+00:00",
        "finished_at": "2026-09-10T00:01:00+00:00",
        "params": {},
        "candidates": [],
    }


@pytest.fixture
def scan_service():
    service = AsyncMock()
    service.new_id = lambda: "scan-new"
    service.latest.return_value = None
    service.get.return_value = None
    app.dependency_overrides[get_market_scan_service] = lambda: service
    yield service
    app.dependency_overrides.pop(get_market_scan_service, None)


@pytest.fixture
def arq():
    service = AsyncMock()
    app.dependency_overrides[get_arq_service] = lambda: service
    yield service
    app.dependency_overrides.pop(get_arq_service, None)


@pytest.mark.asyncio
class TestStartingAScan:
    async def test_the_job_is_queued_with_the_parameters(self, client, scan_service, arq):
        response = await client.post("/api/v1/scan/", json={"app_id": "730", "limit": 5})

        assert response.status_code == 200
        assert response.json()["scan_id"] == "scan-new"
        name, scan_id, params = arq.enqueue.await_args.args
        assert (name, scan_id) == ("market_scan_task", "scan-new")
        assert params["app_id"] == "730"
        assert params["limit"] == 5

    async def test_a_second_scan_is_refused_while_one_runs(self, client, scan_service, arq):
        """Two scans would share one rate limit budget and both would crawl."""
        scan_service.latest.return_value = finished(status="running")

        response = await client.post("/api/v1/scan/", json={})

        assert response.status_code == 409
        arq.enqueue.assert_not_awaited()

    async def test_a_finished_scan_does_not_block_the_next(self, client, scan_service, arq):
        scan_service.latest.return_value = finished()

        assert (await client.post("/api/v1/scan/", json={})).status_code == 200

    async def test_nonsense_parameters_are_refused(self, client, scan_service, arq):
        response = await client.post("/api/v1/scan/", json={"buy_percentile": 0})

        assert response.status_code == 422
        arq.enqueue.assert_not_awaited()


@pytest.mark.asyncio
class TestReadingAScan:
    async def test_the_latest_scan_is_returned(self, client, scan_service):
        scan_service.latest.return_value = finished()

        response = await client.get("/api/v1/scan/latest")

        assert response.json()["id"] == "scan-1"

    async def test_no_scan_yet_says_so(self, client, scan_service):
        assert (await client.get("/api/v1/scan/latest")).status_code == 404

    async def test_an_expired_scan_says_so(self, client, scan_service):
        response = await client.get("/api/v1/scan/gone")

        assert response.status_code == 404
        assert "not around any more" in response.json()["detail"]
