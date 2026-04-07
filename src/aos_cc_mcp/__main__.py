"""Entry point for `python -m aos_cc_mcp`.

This module exists to avoid the python -m double-import problem:
running `python -m aos_cc_mcp.server` loads server.py as __main__
AND as aos_cc_mcp.server (when tools.py imports it), creating two
separate FastMCP instances. Using `python -m aos_cc_mcp` instead
loads the package once and delegates to server.main() via normal
import, which is the same import path the test suite uses.
"""

from aos_cc_mcp.server import main

if __name__ == "__main__":
    main()
