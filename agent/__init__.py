"""Agent control layer: llmadb execution, MCP tools, permission guard, agent loop.

Dependency rules (enforced by review, see docs/architecture.md):

- `agent` may import `config`.
- `agent` must not import `app` (UI) or `memory` (SQLite).
- `agent` talks to the device exclusively through `llmadb`.
"""

__all__ = ["__version__"]
__version__ = "0.1.0"
