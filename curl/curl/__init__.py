"""
Curl Python Client
Modernized high-level Python wrapper around the curl CLI.

Offers both a simple ergonomic API (like `requests`) for everyday tasks,
and a `ParallelCurlRunner` for executing bulk requests efficiently bypassing the GIL.
"""

from .curl import (
    # Simple / Ergonomic API
    Response,
    request,
    get,
    post,
    put,
    patch,
    delete,
    
    # Advanced Parallel Architecture
    ParallelCurlRunner,
    CurlRequest,
    CurlPlugin,
)

# Define the public API
__all__ = [
    # Ergonomic API
    "Response",
    "request",
    "get",
    "post",
    "put",
    "patch",
    "delete",
    
    # Parallel Engine
    "ParallelCurlRunner",
    "CurlRequest",
    "CurlPlugin",
]
