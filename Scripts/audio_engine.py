"""
Contains class AudioEngine: 
- wrapper for the LocalSynthRouter class
"""

from engines.router import LocalSynthRouter

# Backwards-compatible name used by older imports
AudioEngine = LocalSynthRouter

__all__ = ["AudioEngine", "LocalSynthRouter"]
