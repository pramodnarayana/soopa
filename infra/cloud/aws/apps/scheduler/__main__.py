"""
Application Layer (Layer 3) - Scheduler Bounded Context
=======================================================
The Scheduler bounded context does not own any infrastructure (Queues/Databases).
Its Compute layer has been completely consolidated into the unified 'workers' stack.
This stack is now deprecated and can be safely destroyed/removed.
"""
