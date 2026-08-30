class SMTError(Exception):
    """Base class for all application specific errors."""


class SteamOperationFailed(SMTError):
    """Steam accepted the request but reported a failure."""


class BuyOrderFailed(SteamOperationFailed):
    pass


class SellOrderFailed(SteamOperationFailed):
    pass


class ListingNotResolved(SteamOperationFailed):
    """A sell order was placed but its listing id could not be found yet."""


class OrderBookUnavailable(SteamOperationFailed):
    """Steam did not return an order book for the requested item."""
