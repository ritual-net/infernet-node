from __future__ import annotations

from collections import Counter
from dataclasses import asdict
from json import dumps, loads
from typing import Optional, Dict

import redis

from shared import ContainerResult, JobResult, JobStatus
from shared.message import BaseMessage, OffchainMessage
from utils import log


class KeyFormatter:
    """Key formatter for Redis

    Formats keys for Redis using the following pattern:
    <address>:<id>
    """

    @classmethod
    def format(cls, message: BaseMessage) -> str:
        """Format key for given message

        Concatenates address and message id to obtain unique key

        Args:
            message (BaseMessage): Message

        Returns:
            str: Formatted key
        """
        return f"{message.ip}:{message.id}"

    @classmethod
    def get_id(cls, key: str) -> str:
        """Get message id from key

        Args:
            key (str): Key

        Returns:
            str: Message id
        """
        return key.split(":")[1]

    @classmethod
    def matchstr_address(cls, address: str) -> str:
        """Match string for given address

        Args:
            address (str): IP address

        Returns:
            str: Match string to be used with Redis scan_iter
        """
        return f"{address}:*"


class DataStore:
    """Data store for jobs

    Stores and retrieves job results as JSON string to / from Redis. Stores pending
    jobs in a different Redis database for efficient retrieval.

    Also tracks total number of jobs for each status, both onchain and offchain.

    Public methods:
        get: Get job data
        get_job_ids: Get all job IDs for given address
        get_pending_counters: Returns pending counters
        pop_total_counters: Returns total counters and resets them
        set_running: Track running job, store in pending jobs cache if offchain
        set_success: Track successful job, store in completed jobs cache if offchain
        set_failed: Track failed job, store in completed jobs cache if offchain

    Private methods:
        _set: Private method to set job data
        _get_pending: Get all pending job IDs for given address
        _get_completed: Get all completed job IDs for given address

    Attributes:
        _completed (redis.Redis): Redis client for completed jobs db
        _pending (redis.Redis): Redis client for pending jobs db
    """

    def __init__(self: DataStore, host: str, port: int) -> None:
        """Initialize data store

        Establishes connection to Redis databases. Flushes pending jobs db.

        Args:
            host (str, optional): Redis host.
            port (int, optional): Redis port.

        Raises:
            RuntimeError: If connection to Redis databases fails
        """

        # Initialize counters
        self.total_counters: Dict[str, Counter[str]] = {
            "offchain": Counter(),
            "onchain": Counter(),
            "container": Counter(),
        }

        self.pending_counters: Dict[str, int] = {
            "offchain": 0,
            "onchain": 0,
        }

        # Initialize cache for offchain jobs
        self._completed = redis.Redis(host=host, port=port, db=0)
        self._pending = redis.Redis(host=host, port=port, db=1)

        try:
            # Check connection
            self._completed.ping()
            self._pending.ping()

            # Flush pending jobs db
            self._pending.flushdb()
        except redis.exceptions.ConnectionError:
            raise RuntimeError(
                "Could not connect to Redis. Please check your configuration."
            )

        log.info("Initialized Redis client", host=host, port=port)

    def pop_total_counters(self: DataStore) -> dict[str, Counter[str]]:
        """Returns total counters and resets them

        Returns:
            dict[str, Counter]: Total counters
        """
        total_counters = self.total_counters
        self.total_counters = {
            "offchain": Counter(),
            "onchain": Counter(),
            "container": Counter(),
        }
        return total_counters

    def get_pending_counters(self: DataStore) -> dict[str, int]:
        """Returns pending counters

        Returns:
            dict[str, int]: Pending counters
        """
        return self.pending_counters

    def _set(
        self: DataStore,
        message: OffchainMessage,
        status: JobStatus,
        results: list[ContainerResult] = [],
    ) -> None:
        """Private method to set job data

        Sets job data to Redis. If status is "running", sets job as pending. If status
        is "success" or "failed", sets job as completed, and removes it from pending.

        Args:
            message (OffchainMessage): Job message
            status (JobStatus): Job status
            results (list[ContainerResult], optional): Job results. Defaults to [].
        """
        job = JobResult(
            id=message.id,
            status=status,
            intermediate_results=results[:-1],
            result=results[-1] if results else None,
        )

        if status == "running":
            # Set job as pending
            self._pending.set(KeyFormatter.format(message), dumps(asdict(job)))
        else:
            # Remove job from pending
            self._pending.delete(KeyFormatter.format(message))

            # Set job as completed
            self._completed.set(KeyFormatter.format(message), dumps(asdict(job)))

    def get(
        self: DataStore, messages: list[BaseMessage], intermediate: bool = False
    ) -> list[JobResult]:
        """Get job data

        Returns job data from Redis for specified job IDs. Checks pending and completed
        jobs db. Ignores jobs that are not found. Optionally returns intermediate
        results.

        Args:
            message (BaseMessage): Job message
            intermediate (bool, optional): Whether to return intermediate results.
                Defaults to False to avoid returning large amounts of data.

        Returns:
            Optional[JobResult]: Job result or None
        """
        keys = [KeyFormatter.format(message) for message in messages]
        values = [
            loads(value.decode("utf-8"))
            for value in self._completed.mget(keys) + self._pending.mget(keys)
            if value
        ]

        if not intermediate:
            for value in values:
                del value["intermediate_results"]
        return values

    def _get_pending(self: DataStore, address: str) -> list[str]:
        """Get all pending job IDs for given address

        Args:
            address (str): IP address

        Returns:
            list[str]: List of job IDs
        """
        return [
            KeyFormatter.get_id(key.decode("utf-8"))
            for key in self._pending.scan_iter(KeyFormatter.matchstr_address(address))
        ]

    def _get_completed(self: DataStore, address: str) -> list[str]:
        """Get all completed job IDs for given address

        Args:
            address (str): IP address

        Returns:
            list[str]: List of job IDs
        """
        return [
            KeyFormatter.get_id(key.decode("utf-8"))
            for key in self._completed.scan_iter(KeyFormatter.matchstr_address(address))
        ]

    def get_job_ids(
        self: DataStore, address: str, pending: Optional[bool] = None
    ) -> list[str]:
        """Get all job IDs for given address

        Optionally filter by pending or completed job status. If pending is None,
        returns all job IDs.

        Args:
            address (str): IP address
            pending (Optional[bool]): Whether to only return pending or completed jobs

        Returns:
            list[str]: List of job IDs
        """

        # Get all pending and completed job IDs
        if pending is True:
            return self._get_pending(address)
        elif pending is False:
            return self._get_completed(address)
        else:
            return self._get_pending(address) + self._get_completed(address)

    def set_running(self: DataStore, message: Optional[OffchainMessage]) -> None:
        """Track running job, store in pending jobs cache if offchain

        Args:
            message (Optional[OffchainMessage]): Job message
        """
        if message:
            self._set(message, "running")
            self.pending_counters["offchain"] += 1
        else:
            self.pending_counters["onchain"] += 1

    def set_success(
        self: DataStore,
        message: Optional[OffchainMessage],
        results: list[ContainerResult],
    ) -> None:
        """Track successful job, store in completed jobs cache if offchain

        Args:
            message (Optional[OffchainMessage]): Job message
            results (list[ContainerResult]): Job results
        """
        if message:
            self._set(message, "success", results)
            self.pending_counters["offchain"] -= 1
            self.total_counters["offchain"]["success"] += 1
        else:
            self.pending_counters["onchain"] -= 1
            self.total_counters["onchain"]["success"] += 1

    def set_failed(
        self: DataStore,
        message: Optional[OffchainMessage],
        results: list[ContainerResult],
    ) -> None:
        """Track failed job, store in completed jobs cache if offchain

        Args:
            message (Optional[OffchainMessage]): Job message
            results (list[ContainerResult]): Job results
        """
        if message:
            self._set(message, "failed", results)
            self.pending_counters["offchain"] -= 1
            self.total_counters["offchain"]["failed"] += 1
        else:
            self.pending_counters["onchain"] -= 1
            self.total_counters["onchain"]["failed"] += 1

    def track_container(self: DataStore, container: str) -> None:
        """Track container

        Increments container counter

        Args:
            container (str): Container ID
        """
        self.total_counters["container"][container] += 1
