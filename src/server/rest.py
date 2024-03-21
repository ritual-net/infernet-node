from __future__ import annotations

from asyncio import CancelledError, Event, create_task
from typing import Any, Optional, Tuple, Union, cast
from uuid import uuid4

from hypercorn.asyncio import serve
from hypercorn.config import Config
from quart import Quart, Response, jsonify, request

from chain.processor import ChainProcessor
from orchestration import ContainerManager, DataStore, Guardian, Orchestrator
from shared import AsyncTask, JobResult
from shared.message import (
    BaseMessage,
    DelegatedSubscriptionMessage,
    GuardianError,
    MessageType,
    OffchainJobMessage,
    OffchainMessage,
)
from utils import log
from utils.config import ConfigChain, ConfigServer
from utils.parser import from_union


class RESTServer(AsyncTask):
    """A REST webserver that processes off-chain requests.

    Attributes:
        _app (Quart): Quart webserver instance
        _app_config (Config): Quart webserver configuration
        _chain (bool): chain enabled status
        _manager (ContainerManager): container manager instance
        _orchestrator (Orchestrator): orchestrator instance
        _port (int): webserver port
        _processor (Optional[ChainProcessor]): chain processor instance
        _store (DataStore): data store instance
        _version (str): node version
        _wallet_address (Optional[str]): node wallet address
    """

    def __init__(
        self: RESTServer,
        guardian: Guardian,
        manager: ContainerManager,
        orchestrator: Orchestrator,
        processor: Optional[ChainProcessor],
        store: DataStore,
        config_chain: ConfigChain,
        config_server: ConfigServer,
        version: str,
        wallet_address: Optional[str],
    ) -> None:
        """Initialize new RESTServer

        Args:
            guardian (Guardian): Guardian instance
            manager (ContainerManager): Container manager instance
            orchestrator (Orchestrator): Orchestrator instance
            processor (Optional[ChainProcessor]): Chain processor instance
            wallet (Wallet): Wallet instance
            store (DataStore): Data store instance
            config_chain (ConfigChain): chain configuration parameters
            config_server (ConfigServer): server configuration parameters
            version (str): node version
            wallet_address (Optional[str]): node wallet address
        """

        # Initialize inherited async task
        super().__init__()

        self._guardian = guardian
        self._manager = manager
        self._orchestrator = orchestrator
        self._processor = processor
        self._store = store
        self._chain = config_chain["enabled"]
        self._port = config_server["port"]
        self._version = version
        self._wallet_address = wallet_address

        log.info("Initialized RESTServer", port=self._port)

    async def setup(self: RESTServer) -> None:
        """Run RESTServer setup"""

        # Webserver setup
        self._app = Quart(__name__)
        self._app_config = Config.from_mapping(
            {
                "bind": [f"0.0.0.0:{self._port}"],
                # Supress startup log
                # Production server already doesn't log per request
                "loglevel": "WARNING",
            }
        )

        # Register Quart routes
        self.register_routes()

        # Event to signal shutdown
        self._shutdown_event = Event()

    def register_routes(self: RESTServer) -> None:
        """Registers Quart webserver routes"""

        @self._app.route("/health", methods=["GET"])
        async def health() -> Tuple[Response, int]:
            """Collects health of node

            Returns:
                Response (dict[str, str]): node health
            """
            return (
                jsonify(
                    {
                        "status": "healthy",
                    }
                ),
                200,
            )

        @self._app.route("/info", methods=["GET"])
        async def info() -> Tuple[Response, int]:
            """Collects node info

            Returns running container information and pending job counts.

            Returns:
                Response (dict[str, Any]): node stats
            """
            return (
                jsonify(
                    {
                        "containers": self._manager.running_container_info,
                        "pending": self._store.get_pending_counters(),
                    }
                ),
                200,
            )

        @self._app.route("/api/chain/enabled", methods=["GET"])
        async def get_chain_status() -> Tuple[Response, int]:
            """Collects status of whether chain module is enabled or not

            Returns:
                Response (dict[str, bool]): chain enabled true/false
            """
            return jsonify({"enabled": self._chain}), 200

        @self._app.route("/api/chain/address", methods=["GET"])
        async def get_node_address() -> Tuple[Response, int]:
            """Collects node address, if exists

            Returns:
                Tuple[Response, int]: node address or "" if chain disabled
            """
            return (
                jsonify(
                    {"address": self._wallet_address if self._wallet_address else ""}
                ),
                200,
            )

        @self._app.route("/api/jobs", methods=["POST"])
        async def create_job() -> Tuple[Response, int]:
            """Creates new off-chain job (direct compute request or subscription)

            Returns:
                Response (dict[str, str]): created job ID
            """
            try:
                # Collect JSON body
                data = await request.get_json(force=True)

                # Get the IP address of the client
                client_ip = request.remote_addr
                if not client_ip:
                    return jsonify({"error": "Could not get client IP address"}), 400

                log.debug("Received new off-chain raw message", msg=data)

                # Parse message data, inject uuid and client IP
                parsed: OffchainMessage = from_union(
                    OffchainMessage,
                    {"id": str(uuid4()), "ip": client_ip, **data},
                )

                # Filter message through guardian
                filtered = self._guardian.process_message(parsed)

                if isinstance(filtered, GuardianError):
                    log.info(
                        "Error submitting job",
                        endpoint="/api/jobs",
                        method="POST",
                        status=403,
                        err=filtered.error,
                        **filtered.params,
                    )
                    return (
                        jsonify({"error": filtered.error, "params": filtered.params}),
                        405,
                    )

                if filtered.type == MessageType.OffchainJob:
                    # Submit filtered off-chain job message to orchestrator
                    create_task(
                        self._orchestrator.process_offchain_job(
                            cast(OffchainJobMessage, filtered)
                        )
                    )
                elif filtered.type == MessageType.DelegatedSubscription:
                    # Should only reach this point if chain is enabled (else, filtered
                    # out upstream)
                    if self._processor is None:
                        raise RuntimeError("Chain not enabled")

                    # Submit filtered delegated subscription message to processor
                    create_task(
                        self._processor.track(
                            cast(DelegatedSubscriptionMessage, filtered)
                        )
                    )

                # Return created message ID
                log.info(
                    "Processed REST response",
                    endpoint="/api/jobs",
                    method="POST",
                    status=200,
                    id=str(parsed.id),
                )
                return jsonify({"id": str(parsed.id)}), 200
            except Exception as e:
                # Return error
                log.error(
                    "Processed REST response",
                    endpoint="/api/jobs",
                    method="POST",
                    status=500,
                    err=str(e),
                )
                return jsonify({"error": f"Could not enqueue job: {str(e)}"}), 500

        @self._app.route("/api/jobs/batch", methods=["POST"])
        async def create_job_batch() -> Tuple[Response, int]:
            """Creates off-chain jobs in batch (direct compute requests / subscriptions)

            Returns:
                Response (list[dict[str, Any]]): created job IDs
            """
            try:
                # Collect JSON body
                data = await request.get_json(force=True)

                # Get the IP address of the client
                client_ip = request.remote_addr
                if not client_ip:
                    return jsonify({"error": "Could not get client IP address"}), 400

                log.debug("Received new off-chain raw message batch", msg=data)

                # If data is not an array, return error
                if not isinstance(data, list):
                    return jsonify({"error": "Expected a list"}), 400

                # Inject uuid and client IP to each message
                parsed: list[OffchainMessage] = [
                    from_union(
                        OffchainMessage,
                        {"id": str(uuid4()), "ip": client_ip, **item},
                    )
                    for item in data
                ]

                # Filter messages through guardian
                filtered = cast(
                    list[Union[OffchainMessage, GuardianError]],
                    [
                        (
                            self._guardian.process_message(item)
                            if item is not None
                            else None
                        )
                        for item in parsed
                    ],
                )

                results: list[dict[str, Any]] = []
                for item in filtered:
                    if isinstance(item, GuardianError):
                        results.append({"error": item.error, "params": item.params})
                    elif isinstance(item, OffchainMessage):  # type: ignore
                        # Submit filtered message to orchestrator
                        assert item is not None

                        if item.type == MessageType.OffchainJob:
                            create_task(
                                self._orchestrator.process_offchain_job(
                                    cast(OffchainJobMessage, item)
                                )
                            )
                            results.append({"id": str(item.id)})
                        elif item.type == MessageType.DelegatedSubscription:
                            # Should only reach this point if chain is enabled (else,
                            # filtered out upstream)
                            if self._processor is None:
                                raise RuntimeError("Chain not enabled")

                            # Submit filtered delegated subscription message to processor
                            create_task(
                                self._processor.track(
                                    cast(DelegatedSubscriptionMessage, item)
                                )
                            )
                        else:
                            results.append({"error": "Could not parse message"})

                # Return created message IDs or errors
                log.info(
                    "Processed REST response",
                    endpoint="/api/jobs/batch",
                    method="POST",
                    status=200,
                    results=results,
                )
                return jsonify(results), 200
            except Exception as e:
                # Return error
                log.error(
                    "Processed REST response",
                    endpoint="/api/jobs/batch",
                    method="POST",
                    status=500,
                    err=str(e),
                )
                return jsonify({"error": f"Could not enqueue job:  {str(e)}"}), 500

        @self._app.route("/api/jobs", methods=["GET"])
        async def get_job() -> Tuple[Response, int]:
            # Get the IP address of the client
            client_ip = request.remote_addr
            if not client_ip:
                return jsonify({"error": "Could not get client IP address"}), 400

            # Get job ID from query
            job_ids = request.args.getlist("id")

            # If no job ID is specified, return all job IDs
            if not job_ids:
                # Optionally filter by pending or completed job status
                pending = request.args.get("pending")
                if pending == "true":
                    ids = self._store.get_job_ids(client_ip, pending=True)
                elif pending == "false":
                    ids = self._store.get_job_ids(client_ip, pending=False)
                else:
                    ids = self._store.get_job_ids(client_ip)
                return jsonify(ids), 200
            else:
                # Get intermediate results flag from query
                intermediate = request.args.get("intermediate") == "true"

                data: list[JobResult] = self._store.get(
                    [BaseMessage(id, client_ip) for id in job_ids], intermediate
                )
                return jsonify(data), 200

        @self._app.route("/api/status", methods=["PUT"])
        async def store_job_status() -> Tuple[Response, int]:
            """Stores job status in data store"""
            try:
                # Collect JSON body
                data = await request.get_json(force=True)

                # Get the IP address of the client
                client_ip = request.remote_addr
                if not client_ip:
                    return jsonify({"error": "Could not get client IP address"}), 400

                log.debug("Received new result", result=data)

                # Create off-chain message with client IP
                parsed: OffchainMessage = from_union(
                    OffchainMessage,
                    {
                        "id": data["id"],
                        "ip": client_ip,
                        "containers": data["containers"],
                        "data": {},
                    },
                )

                # Store job status
                match data["status"]:
                    case "success":
                        self._store.set_success(parsed, [])
                        for container in data["containers"]:
                            self._store.track_container(container)
                    case "failed":
                        self._store.set_failed(parsed, [])
                        for container in data["containers"]:
                            self._store.track_container(container)
                    case "running":
                        self._store.set_running(parsed)
                    case _:
                        return jsonify({"error": "Status is invalid"}), 400

                return jsonify(), 200
            except Exception as e:
                # Return error
                log.error(
                    "Processed REST response",
                    endpoint="/api/status",
                    method="PUT",
                    status=500,
                    err=e,
                )
                return jsonify({"error": "Could not store job status"}), 500

    async def run_forever(self: RESTServer) -> None:
        """Main RESTServer lifecycle loop. Uses production hypercorn server"""

        log.info("Serving REST webserver", addr="0.0.0.0", port=self._port)

        async def shutdown_trigger() -> None:
            """Shutdown trigger for hypercorn"""
            await self._shutdown_event.wait()

        server_task = create_task(
            serve(
                app=self._app,
                config=self._app_config,
                mode="asgi",
                # Stop server when stop event is set
                shutdown_trigger=shutdown_trigger,
            )
        )

        try:
            await server_task
        except CancelledError:
            pass  # Expected due to cancellation

    async def stop(self: RESTServer) -> None:
        """Stops the RESTServer."""
        log.info("Stopping REST webserver")

        # Set shutdown event to stop server
        self._shutdown_event.set()

    async def cleanup(self: RESTServer) -> None:
        """Runs RESTServer cleanup"""
        pass
