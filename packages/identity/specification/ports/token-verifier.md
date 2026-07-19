# Port: Token Verifier

Validates an access token and returns normalized token claims.

Required behavior:

- Reject missing, malformed, expired, or unsigned tokens.
- Validate issuer and audience.
- Resolve signing keys from JWKS with caching.
- Return claims without exposing framework-specific request objects.
