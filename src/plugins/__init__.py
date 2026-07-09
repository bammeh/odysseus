"""Plugin platform primitives for Odysseus."""

from .manager import PluginManager
from .manifest import PluginManifest, PluginManifestError

__all__ = ["PluginManager", "PluginManifest", "PluginManifestError"]
