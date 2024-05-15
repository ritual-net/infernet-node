"""
This module contains the following classes:

1. KeyFormatter: Key formatter for Redis. Formats keys for Redis using the pattern
    <address>:<id>.

2. DataStoreCounters: Manages job-related counters for onchain and offchain jobs. Also
    tracks container statuses.

3. DataStore: Stores and retrieve job results to / from Redis. Stores pending jobs in a
    different Redis database than completed jobs for efficient retrieval.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict
from datetime import timedelta
from json import dumps, loads
from typing import Optional

import redis

from shared import ContainerResult, JobResult, JobStatus
from shared.message import BaseMessage, OffchainMessage
from utils import log

# Loose expiration time for pending jobs
PENDING_JOB_TTL = 15  # minutes


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


class DataStoreCounters:
    """Class to store and retrieve job-related counters

    Job counters track the number of jobs by status (success, failed) and location
    (onchain, offchain).

    Container counters track the number of container runs by status (success, failed).

    Public methods:
        pop_job_counters: Returns job counters and resets them
        pop_container_counters: Returns container counters and resets them
        increment_job_counter: Increment job counter
        increment_container_counter: Increment container counter

    Private methods:
        _default_job_counters: Default value for job counters
        _default_container_counters: Default value for container counters

    Attributes:
        job_counters (dict[str, dict[str, int]]): Job counters
        container_counters (dict[str, dict[str, int]]): Container counters
    """

    def __init__(self: DataStoreCounters) -> None:
        """Initialize the counters"""

        # Job counters
        self.job_counters = DataStoreCounters._default_job_counters()

        # Container counters
        self.container_counters: defaultdict[str, dict[str, int]] = defaultdict(
            DataStoreCounters._default_container_counters
        )

    @staticmethod
    def _default_job_counters() -> dict[str, dict[str, int]]:
        """Default value for job counters"""

        return {
            "offchain": {"success": 0, "failed": 0},
            "onchain": {"success": 0, "failed": 0},
        }

    def pop_job_counters(self: DataStoreCounters) -> dict[str, dict[str, int]]:
        """Returns job counters and resets them

        Returns:
             dict[str, dict[str, int]]: Job counters
        """
        job_counters = self.job_counters
        self.job_counters = DataStoreCounters._default_job_counters()
        return job_counters

    @staticmethod
    def _default_container_counters() -> dict[str, int]:
        """Default value for container counters"""

        return {
            "success": 0,
            "failed": 0,
        }

    def pop_container_counters(
        self: DataStoreCounters,
    ) -> defaultdict[str, dict[str, int]]:
        """Returns container counters and resets them

        Returns:
            defaultdict[str, dict[str, int]]: Container counters
        """
        container_counters = self.container_counters
        self.container_counters = defaultdict(
            DataStoreCounters._default_container_counters
        )
        return container_counters

    def increment_job_counter(
        self: DataStoreCounters,
        status: JobStatus,
        location: str,
    ) -> None:
        """Increment job counter

        Args:
            status (JobStatus): Job status
            location (str): Job location
        """
        self.job_counters[location][status] += 1

    def increment_container_counter(
        self: DataStoreCounters,
        status: JobStatus,
        container: str,
    ) -> None:
        """Increment container counter

        Args:
            status (JobStatus): Container status
            container (str): Container ID
        """
        self.container_counters[container][status] += 1


class DataStore:
    """Data store for jobs

    Stores and retrieves job results as JSON string to / from Redis. Stores pending
    jobs in a different Redis database for efficient retrieval.

    Also tracks total number of jobs by status, both onchain and offchain, as well as
    individual container statuses and counts.

    Public methods:
        get: Get job data
        get_job_ids: Get all job IDs for given address
        get_pending_counters: Returns pending counters
        set_running: Track running job, store in pending jobs cache if offchain
        set_success: Track successful job, store in completed jobs cache if offchain
        set_failed: Track failed job, store in completed jobs cache if offchain
        track_container_status: Track container status

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
        self.counters = DataStoreCounters()

        # Counter for pending on-chain jobs. Off-chain jobs are tracked in Redis.
        self._onchain_pending = 0

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

    def get_pending_counters(self: DataStore) -> dict[str, int]:
        """Returns pending counters for onchain and offchain jobs

        Returns:
            dict[str, int]: Pending counters
        """
        return {"offchain": self._pending.dbsize(), "onchain": self._onchain_pending}

    def _set(
        self: DataStore,
        message: OffchainMessage,
        status: JobStatus,
        results: list[ContainerResult] = [],
    ) -> None:
        """Private method to set job data

        Sets job data to Redis. If status is "running", sets job as pending. If status
        is "success" or "failed", sets job as completed, and removes it from pending.

        NOTE: Pending jobs are set with an expiration time of PENDING_JOB_TTL minutes,
        which is a loose upper bound on the time it should take for a job to complete.
        This is to ensure crashes and / or incorrect use of the `/status` endpoint do
        not leave jobs in a pending state indefinitely.

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
            # Set job as pending. Expiration time is PENDING_JOB_TTL
            self._pending.setex(
                KeyFormatter.format(message),
                timedelta(minutes=PENDING_JOB_TTL),
                dumps(asdict(job)),
            )
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
        jobs DBs. Ignores jobs that are not found. Optionally returns intermediate
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
        else:
            self._onchain_pending += 1

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
            self.counters.increment_job_counter("success", "offchain")
        else:
            self._onchain_pending -= 1
            self.counters.increment_job_counter("success", "onchain")

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
            self.counters.increment_job_counter("failed", "offchain")
        else:
            self._onchain_pending -= 1
            self.counters.increment_job_counter("failed", "onchain")

    def track_container_status(
        self: DataStore,
        container: str,
        status: JobStatus,
    ) -> None:
        """Track container status

        Args:
            container (str): Container ID
            status (JobStatus): Container status
        """
        self.counters.increment_container_counter(status, container)
