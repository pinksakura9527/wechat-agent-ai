"""Configuration package: app settings, persona templates, permission schema.

This package is the bottom of the dependency graph. It must not import
``app``, ``agent`` or ``memory``.
"""

from config.settings import (
    APP_NAME,
    ApiConfig,
    AppSettings,
    RuntimeConfig,
    user_data_dir,
)

__all__ = [
    "APP_NAME",
    "ApiConfig",
    "AppSettings",
    "RuntimeConfig",
    "user_data_dir",
]
