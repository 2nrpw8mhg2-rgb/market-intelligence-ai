class MarketDataError(Exception):
    """Base error for provider failures."""


class MarketDataAuthenticationError(MarketDataError):
    pass


class MarketDataRateLimitError(MarketDataError):
    pass


class MarketDataResponseError(MarketDataError):
    pass
