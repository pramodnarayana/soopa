# patches

A centralized library of monkey-patches for third-party open-source dependencies.

## Why does this exist?

Some upstream libraries we depend on have bugs, dropped backwards-compatibility,
or are otherwise missing functionality we need. Rather than scattering fixes
across multiple adapters or services, we collect them here so:

- Every fix has a clear home with documented rationale.
- Fixes are applied idempotently (applying twice is harmless).
- When the upstream library ships a fix, we can remove the patch in one place.

## Modules

| Module | Library | Reason |
|--------|---------|--------|
| `patches.paramiko` | paramiko ≥ 3.4 | Restore support for legacy ssh-rsa (SHA-1) algorithm dropped in 3.4 |

## Usage

```python
from patches import paramiko as _  # side-effect: patch is applied on import
```

Or explicitly:

```python
from patches.paramiko import apply_legacy_algorithm_support

apply_legacy_algorithm_support()
```
