"""Wayback Machine SDK.

A comprehensive client for interacting with the Internet Archive's Wayback Machine.
Currently supports the Save Page Now 2 (SPN2) API for URL preservation, with
foundational architecture for CDX searching and Availability API integration.
"""

from .wayback_machine import WaybackMachine

__all__ = ["WaybackMachine"]
