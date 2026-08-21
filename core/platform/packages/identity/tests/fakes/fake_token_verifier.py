from identity.domain.identity_context import TokenClaims
from identity.ports.outbound.token_verifier_port import TokenValidationError, TokenVerifierPort


class FakeTokenVerifier(TokenVerifierPort):
    """In-Memory fake for TokenVerifierPort."""

    def __init__(self) -> None:
        self.tokens: dict[str, TokenClaims] = {}
        self.should_raise_format_error: bool = False
        self.verified_calls: list[str] = []

    def given_valid_token(self, token: str, claims: TokenClaims) -> None:
        """Pre-configure the fake with a valid token."""
        self.tokens[token] = claims

    def given_invalid_format_error(self) -> None:
        """Configure the fake to always raise a TokenValidationError for testing bad signatures."""
        self.should_raise_format_error = True

    async def verify(self, token: str) -> TokenClaims:
        self.verified_calls.append(token)

        if self.should_raise_format_error:
            raise TokenValidationError("Invalid token format or signature")

        if token not in self.tokens:
            raise TokenValidationError("Signature has expired or token is invalid")

        return self.tokens[token]
