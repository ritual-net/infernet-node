from __future__ import annotations


class AsyncTask:
    """Generic task w/ async `run_forever` loop"""

    def __init__(self: AsyncTask) -> None:
        """Initialize new AsyncTask"""

        # Lifecycle handler
        self._shutdown: bool = False

    async def setup(self: AsyncTask) -> None:
        """Async setup process

        Raises:
            NotImplementedError: Not implemented
        """
        raise NotImplementedError

    async def run_forever(self: AsyncTask) -> None:
        """Default lifecycle loop

        Raises:
            NotImplementedError: Not implemented
        """
        raise NotImplementedError

    async def cleanup(self: AsyncTask) -> None:
        """Async process cleanup

        Raises:
            NotImplementedError: Not implemented
        """
        raise NotImplementedError

    async def stop(self: AsyncTask) -> None:
        """Toggles lifecycle handler to shutdown"""
        self._shutdown = True
