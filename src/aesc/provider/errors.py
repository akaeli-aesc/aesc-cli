"""
Error types for chat providers.
"""


class ChatProviderError(Exception):
    """Base exception for chat provider errors."""

    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


class APIStatusError(ChatProviderError):
    """HTTP error from the API."""

    def __init__(self, status_code: int, message: str):
        self.status_code = status_code
        super().__init__(f"Error code: {status_code} - {message}")


class APIConnectionError(ChatProviderError):
    """Connection error to the API."""

    pass


class APITimeoutError(ChatProviderError):
    """Timeout when calling the API."""

    pass


class APIEmptyResponseError(ChatProviderError):
    """Empty response from the API."""

    def __init__(self):
        super().__init__("Empty response from API")
