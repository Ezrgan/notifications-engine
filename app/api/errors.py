"""HTTP-layer errors for the API composition root. Not domain exceptions."""


class UnauthorizedError(Exception):
    """Missing, invalid, or inactive API key. Handler always returns the same 401 body."""
