class IdentityProviderPortError(Exception):
    def __init__(
        self, message: str, status_code: int = 500, original_error: Exception | None = None
    ):
        super().__init__(message)
        self.status_code = status_code
        self.original_error = original_error
