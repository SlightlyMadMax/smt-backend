import datetime
from unittest.mock import AsyncMock, patch

import pytest

from smt.exceptions import SteamLoginUnavailable
from smt.services.steam import LOGIN_COOLDOWN_BASE, LOGIN_COOLDOWN_MAX, SteamService


@pytest.fixture
def service():
    with patch.object(SteamService, "__init__", lambda self, settings=None: None):
        svc = SteamService()
    svc._last_check = None
    svc._check_interval = datetime.timedelta(minutes=5)
    svc._login_blocked_until = None
    svc._login_failures = 0
    return svc


@pytest.mark.asyncio
class TestEnsureLogin:
    async def test_marks_the_session_checked_on_success(self, service):
        service._log_in = AsyncMock()

        await service._ensure_login()

        assert service._last_check is not None
        assert service._login_failures == 0

    async def test_skips_the_network_while_the_session_is_fresh(self, service):
        service._log_in = AsyncMock()
        service._last_check = datetime.datetime.now(datetime.UTC)

        await service._ensure_login()

        service._log_in.assert_not_awaited()

    async def test_failure_raises_and_starts_a_cooldown(self, service):
        service._log_in = AsyncMock(side_effect=KeyError("client_id"))

        with pytest.raises(SteamLoginUnavailable):
            await service._ensure_login()

        assert service._login_failures == 1
        assert service._login_blocked_until is not None

    async def test_further_calls_do_not_touch_the_network_during_cooldown(self, service):
        service._log_in = AsyncMock(side_effect=KeyError("client_id"))
        with pytest.raises(SteamLoginUnavailable):
            await service._ensure_login()

        service._log_in.reset_mock()
        for _ in range(20):
            with pytest.raises(SteamLoginUnavailable, match="cooldown"):
                await service._ensure_login()

        service._log_in.assert_not_awaited()

    async def test_cooldown_grows_with_consecutive_failures(self, service):
        service._log_in = AsyncMock(side_effect=KeyError("client_id"))
        cooldowns = []
        for _ in range(3):
            service._login_blocked_until = None
            with pytest.raises(SteamLoginUnavailable):
                await service._ensure_login()
            cooldowns.append(service._login_blocked_until)

        assert cooldowns[0] < cooldowns[1] < cooldowns[2]

    async def test_cooldown_is_capped(self, service):
        service._log_in = AsyncMock(side_effect=KeyError("client_id"))
        service._login_failures = 20
        before = datetime.datetime.now(datetime.UTC)

        with pytest.raises(SteamLoginUnavailable):
            await service._ensure_login()

        assert service._login_blocked_until - before <= LOGIN_COOLDOWN_MAX + datetime.timedelta(seconds=1)

    async def test_success_after_failures_clears_the_cooldown(self, service):
        service._log_in = AsyncMock(side_effect=KeyError("client_id"))
        with pytest.raises(SteamLoginUnavailable):
            await service._ensure_login()

        service._login_blocked_until = None
        service._log_in = AsyncMock()
        await service._ensure_login()

        assert service._login_failures == 0
        assert service._login_blocked_until is None

    async def test_first_cooldown_matches_the_base(self, service):
        service._log_in = AsyncMock(side_effect=KeyError("client_id"))
        before = datetime.datetime.now(datetime.UTC)

        with pytest.raises(SteamLoginUnavailable):
            await service._ensure_login()

        assert service._login_blocked_until - before >= LOGIN_COOLDOWN_BASE - datetime.timedelta(seconds=1)
