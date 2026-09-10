"""How a Steam session survives being handed to another process, checked without Steam."""

import pytest
from steampy.client import SteamClient

from smt.core.config import get_settings


GUARD = {"steamid": "76561198357835941", "shared_secret": "s", "identity_secret": "i"}

COOKIES = [
    {"name": "steamLoginSecure", "value": "7656%7C%7Ctoken", "domain": "steamcommunity.com", "path": "/"},
    {"name": "sessionid", "value": "abc123def456", "domain": "steamcommunity.com", "path": "/"},
    {"name": "steamCountry", "value": "LV%7Chash", "domain": "steamcommunity.com", "path": "/"},
    {"name": "steamLoginSecure", "value": "7656%7C%7Ctoken", "domain": "store.steampowered.com", "path": "/"},
]


def build_client() -> SteamClient:
    settings = get_settings()
    return SteamClient(
        api_key=settings.STEAM_API_KEY,
        username=settings.STEAM_USERNAME,
        password=settings.STEAM_PASSWORD,
    )


def restore(client: SteamClient) -> None:
    """The same steps the service takes when adopting a published session."""
    for cookie in COOKIES:
        client._session.cookies.set(cookie["name"], cookie["value"], domain=cookie["domain"], path=cookie["path"])
    client.steam_guard = GUARD
    client.was_login_executed = True
    client.market._set_login_executed(client.steam_guard, client._get_session_id())


@pytest.fixture
def client():
    return build_client()


class TestRestoringACookieSession:
    def test_the_session_id_survives(self, client):
        restore(client)

        assert client._get_session_id() == "abc123def456"

    def test_the_market_can_sign_its_requests(self, client):
        """Without this every market POST would carry a null session id."""
        restore(client)

        assert client.market.was_login_executed is True
        assert client.market._session_id == "abc123def456"
        assert client.market._steam_guard == GUARD

    def test_cookies_keep_their_domains(self, client):
        restore(client)

        community = client._session.cookies.get_dict(domain="steamcommunity.com")
        store = client._session.cookies.get_dict(domain="store.steampowered.com")

        assert "steamLoginSecure" in community
        assert "steamLoginSecure" in store


class TestSteampyShortcuts:
    """The library offers two shortcuts for this, and neither one works."""

    def test_set_login_cookies_loses_the_session_id(self, client):
        client.steam_guard = GUARD
        client.set_login_cookies({"sessionid": "abc123def456", "steamLoginSecure": "token"})

        # it stores the cookies without a domain, then reads them back with a domain
        # filter, so the market is wired up with nothing to sign requests with
        assert client._get_session_id() is None
        assert client.market._session_id is None

    def test_is_session_alive_needs_credentials_the_client_may_not_have(self):
        bare = SteamClient(api_key="x")
        bare.was_login_executed = True

        with pytest.raises(AttributeError):
            bare.is_session_alive()


class TestHeadersSteamWillAccept:
    """Measured against Steam: Accept and Accept-Language both draw a 429, whatever their value."""

    def test_neither_header_is_sent(self):
        from smt.core.config import get_settings
        from smt.services.steam import UNWELCOME_HEADERS, SteamService

        service = SteamService(get_settings())

        for header in UNWELCOME_HEADERS:
            assert header not in service.client._session.headers

    def test_the_parser_looks_for_english_labels(self):
        import inspect

        from steampy import utils

        source = inspect.getsource(utils.get_market_listings_from_html)

        assert "My buy orders" in source
        assert "My sell listings" in source

    def test_we_do_not_promise_to_decode_what_we_cannot(self):
        """requests advertises the codecs it has; overriding that leaves undecodable bytes."""
        from smt.services.steam import MOBILE_HEADERS, WEB_HEADERS

        assert "Accept-Encoding" not in WEB_HEADERS
        assert "Accept-Encoding" not in MOBILE_HEADERS
