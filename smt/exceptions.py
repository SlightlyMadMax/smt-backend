class SMTError(Exception):
    """Base class for all application specific errors."""


class PoolItemAlreadyExists(SMTError):
    """The item is already in the trading pool."""


class UnknownPoolItem(SMTError):
    """The referenced item is not in the trading pool."""


class SteamLoginUnavailable(SMTError):
    """Steam refused to establish a session and further attempts are on cooldown."""


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
