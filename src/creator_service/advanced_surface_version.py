"""Deployment marker for the advanced ChatGPT MCP write surface.

This module intentionally has no runtime side effects. Its presence makes the
advanced category/caption rollout an explicit runtime-affecting commit so the
production deployment workflow rebuilds the MCP image with the complete branch.
"""

ADVANCED_SURFACE_VERSION = "2026-09-07.1"
