"""Entry point for Government Browser Agent."""
from __future__ import annotations

import sys


if __name__ == "__main__":
    # On Windows, reload=True forces uvicorn to use SelectorEventLoop
    # which does NOT support subprocesses. Playwright requires ProactorEventLoop
    # to spawn its browser driver. Keep reload=False on Windows.
    #
    # See: https://uvicorn.dev/concepts/event-loop/
    #   "When running with --reload or multiple workers, it uses
    #    SelectorEventLoop instead [on Windows]."
    use_reload = "--reload" in sys.argv or "--watch" in sys.argv

    if sys.platform == "win32" and use_reload:
        print(
            "WARNING: --reload/--watch is incompatible with Playwright on Windows.\n"
            "  uvicorn uses SelectorEventLoop for reload mode, which cannot spawn\n"
            "  subprocesses. Playwright needs ProactorEventLoop.\n"
            "  Starting without reload instead.",
            file=sys.stderr,
        )
        use_reload = False

    import uvicorn

    uvicorn.run(
        "app.main:app",
        host="127.0.0.1",
        port=8000,
        reload=use_reload,
    )
