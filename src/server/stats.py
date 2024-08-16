from __future__ import annotations

import asyncio
import time
from typing import Any, Optional
from uuid import uuid4

from fluent import sender  # type: ignore

from chain.wallet import Wallet
from orchestration import DataStore, Guardian
from shared.service import AsyncTask
from utils.logging import log

# Constants - intervals in seconds for forwarding stats to Ritual
LIVE_INTERVAL = 60
NODE_INTERVAL = 3600


class StatCollector:
    """Collects machine stats

    Methods to create machine ID, execute shell commands, and collect various
    machine stats.

    Methods:
        get_uid: Create a unique machine ID
        get_ip: Get the external IP address
        get_resources: Get {cpu, disk, gpu, kernel, memory} specs asynchronously
        get_utilization: Get {cpu, disk, gpu, memory} utilization
        get_uptime: Get the machine uptime

    Private Methods:
        _execute: Execute a shell command asynchronously
    """

    @classmethod
    async def _execute(cls, command: str) -> Optional[str]:
        """Execute a shell command asynchronously.

        Args:
            command (str): The shell command to execute.

        Returns:
            Optional[str]: The output of the shell command, or None if the command
                failed.
        """
        process = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        outputb, errorb = await process.communicate()

        if output := outputb.decode("utf-8").strip():
            return output

        if error := errorb.decode("utf-8").strip():
            log.debug(
                "Error executing command",
                exc_info=True,
                extra={"command": command, "error": error},
            )

        return None

    @classmethod
    async def get_uid(cls) -> Optional[str]:
        """Create a unique machine ID.

        Generate a unique machine ID by hashing the machine ID and the external IP
        address. If we can't get the machine ID, just generate a random UUID.

        Returns:
            str: A unique machine ID
        """
        machine_id = await cls._execute("cat /etc/machine-id")
        external_ip = await cls.get_ip()

        # Hash the machine ID and external IP
        unique_id = await cls._execute(
            f'echo "{machine_id}_{external_ip}"' "| sha256sum | awk '{print $1}'"
        )

        # If we can't get the machine ID, generate random
        if not machine_id or not unique_id:
            return str(uuid4())

        return unique_id

    @classmethod
    async def get_ip(cls) -> Optional[str]:
        """Get the external IP address"""
        return await cls._execute("curl http://icanhazip.com")

    @classmethod
    async def get_resources(cls) -> dict[str, Optional[str]]:
        """Get {cpu, disk, gpu, kernel, memory} specs asynchronously."""

        commands = {
            "cpu": """lscpu | awk -F: '/^Architecture:|^CPU\(s\):|^Model name:/ { gsub(/^[ \t]+/, "", $2); printf("%s ", $2); } END { print ""; }'""",  # noqa: E501
            "disk": "df -h | awk '/\/$/ {print $2}'",
            "gpu": """if which nvidia-smi > /dev/null; then nvidia-smi --query-gpu=gpu_name --format=csv,noheader | awk '{name=$0; count++} END {if(count > 0) print count " x " name}'; fi""",  # noqa: E501
            "kernel": "uname -mrs",
            "memory": "free -h | awk '/Mem:/ {print $2}'",
        }

        tasks = [
            asyncio.create_task(cls._execute(command)) for command in commands.values()
        ]
        results = await asyncio.gather(*tasks)
        return dict(zip(commands.keys(), results))

    @classmethod
    async def get_utilization(cls) -> dict[str, Optional[str]]:
        """Get {cpu, disk, gpu, memory} utilization"""

        commands = {
            "cpu": """mpstat | awk '$2 == "all" {printf "%.1f%%", 100 - $12 - $9}'""",
            "disk": "df -h | awk '/\/$/ {print $5}'",
            "io": """iostat -p sda -d 4 1 -y | awk '/^sda / {print $3" kB_read/s" ", " $4 " kB_wrtn/s"}'""",  # noqa: E501
            "gpu": """bash -c "if which nvidia-smi > /dev/null; then nvidia-smi --query-gpu=utilization.gpu --format=csv,noheader | awk '{print \$1}' | awk '{sum += \$1; count++} END {if (count > 0) print sum / count}'; fi" """,  # noqa: E501
            "memory": """free -m | awk '/Mem:/ {printf "%.f%%", $3 / $2 * 100}'""",
            "network": """ifstat 5 1 | awk 'NR>2 {for (i=1; i<=NF; i+=2) inSum += $i; for (i=2; i<=NF; i+=2) outSum += $i} END {print inSum " KB/s, " outSum " KB/s"}'""",  # noqa: E501
        }

        tasks = [
            asyncio.create_task(cls._execute(command)) for command in commands.values()
        ]
        results = await asyncio.gather(*tasks)
        return dict(zip(commands.keys(), results))

    @classmethod
    async def get_uptime(cls) -> Optional[str]:
        """Get the machine uptime"""
        return await cls._execute("uptime -p")


class StatSender(AsyncTask):
    """Periodically forwards node stats via fluentbit

    Sends node (long-lived) stats and live (short-lived) stats via fluentbit, at
    different intervals.

    Attributes:
        _uid (str): A unique machine ID
        _version (str): The version of the node
        _port (int): The port of the local REST server
        _guardian (Guardian): The guardian instance
        _store (DataStore): The data store instance
        _wallet (Optional[Wallet]): Optional wallet instance, if chain enabled
        _chain_id (Optional[int]): Optional chain ID, if chain enabled
        _sender (sender.FluentSender): The fluentbit sender
    """

    def __init__(
        self: StatSender,
        version: str,
        port: int,
        guardian: Guardian,
        store: DataStore,
        wallet: Optional[Wallet],
        chain_id: Optional[int],
    ) -> None:
        """Initialize StatSender

        Args:
            version (str): The version of the node
            port (int): The port of the local REST server
            guardian (Guardian): The guardian instance
            store (DataStore): The data store instance
            wallet (Optional[Wallet]): Optional wallet instance, if chain enabled
            chain_id (Optional[int]): Optional chain ID, if chain enabled

        """
        super().__init__()
        self._version = version
        self._port = port
        self._guardian = guardian
        self._store = store
        self._wallet = wallet
        self._chain_id = chain_id

    async def setup(self: StatSender) -> None:
        """Create a unique ID and initialize the sender"""

        self._uid = await StatCollector.get_uid()
        self._sender = sender.FluentSender("stats", host="fluentbit", port=24224)

    async def _get_node_stats(self: StatSender) -> dict[str, Any]:
        """Collect boot stats"""

        job_counters = self._store.counters.pop_job_counters()
        container_counters = self._store.counters.pop_container_counters()

        return {
            "uid": self._uid,
            "address": None if self._wallet is None else self._wallet.address,
            "chain_id": None if self._chain_id is None else self._chain_id,
            "containers": self._guardian.restrictions,
            "counters": {
                "jobs": job_counters,
                "containers": container_counters,
            },
            "ip": await StatCollector.get_ip(),
            "port": self._port,
            "resources": await StatCollector.get_resources(),
            "uptime": await StatCollector.get_uptime(),
            "version": self._version,
        }

    async def _get_live_stats(self: StatSender) -> dict[str, Any]:
        """Collect live stats"""

        return {
            "uid": self._uid,
            "jobs_pending": self._store.get_pending_counters(),
            "utilization": await StatCollector.get_utilization(),
        }

    async def send_node_stats_shutdown(
        self: StatSender, error: Optional[str] = None
    ) -> None:
        """Send node stats with optional error message at shutdown

        Args:
            error (Optional[str]): The error message to report
        """
        data = await self._get_node_stats()
        if error:
            data["error"] = error
        self._sender.emit(label="node", data=data)

    async def run_forever(self: StatSender) -> None:
        """Default lifecycle loop

        Sends node stats to fluentbit on startup, then every NODE_INTERVAL seconds.
        Sends live stats every LIVE_INTERVAL seconds; LIVE_INTERVAL must be less than
        NODE_INTERVAL. Asynchronous sleep is used to wait to avoid blocking.
        """

        last_sent = None
        while not self._shutdown:
            now = time.time()

            # Send node stats at boot, then every NODE_INTERVAL seconds
            if not last_sent or (now - last_sent >= NODE_INTERVAL):
                self._sender.emit(label="node", data=await self._get_node_stats())
                last_sent = now

            # Get live stats
            live_stats = asyncio.create_task(self._get_live_stats())

            # Wait for LIVE_INTERVAL seconds
            await asyncio.sleep(LIVE_INTERVAL)

            # Ensure live stats collection is complete before sending
            await live_stats
            self._sender.emit(label="live", data=live_stats.result())

    async def stop(self: StatSender) -> None:
        """Stop the task"""
        self._shutdown = True

    async def cleanup(self: StatSender) -> None:
        """No cleanup needed"""
        self._sender.close()
