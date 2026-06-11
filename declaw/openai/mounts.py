"""Placeholder for cloud-bucket mount strategies.

Declaw sandboxes persist via memory + disk snapshots today. Bind-mounts
and cloud-bucket mounts are not yet part of the public API; this symbol
is reserved so the import surface stays stable when we add them.
"""

from __future__ import annotations

# Reserved for a future cloud-bucket mount implementation.
DeclawCloudBucketMountStrategy = None

__all__ = ["DeclawCloudBucketMountStrategy"]
