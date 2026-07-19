# Port: Token Verifier

Validates an access token and returns normalized token claims.

Required behavior:

- Reject missing, malformed, expired, or unsigned tokens.
- Validate issuer and audience.
- Validate subject (sub) is present.
- Resolve signing keys from JWKS with caching.
- Validate and normalize tenant_id, roles, and permissions claims.
- Reject tokens with missing or invalid required claims.
- Return only the normalized TokenClaims shape after all cryptographic, issuer, audience, and subject checks pass.
- Return claims without exposing framework-specific request objects.
