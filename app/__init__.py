"""Desktop UI layer (PySide6).

The UI owns no business logic: it renders events emitted by `agent` and
calls `config`/`memory` through their public APIs only. A future port to
Tauri or another toolkit replaces this package alone.
"""

__all__ = ["main"]
