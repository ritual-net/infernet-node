ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"

DELEGATED_SIGNER_ABI = [
    {
        "type": "function",
        "name": "signer",
        "inputs": [],
        "outputs": [{"name": "", "type": "address", "internalType": "address"}],
        "stateMutability": "view",
    }
]

SUBSCRIPTION_CONSUMER_ABI = [
    {
        "type": "function",
        "name": "getContainerInputs",
        "inputs": [
            {
                "name": "subscriptionId",
                "type": "uint32",
                "internalType": "uint32",
            },
            {"name": "interval", "type": "uint32", "internalType": "uint32"},
            {"name": "timestamp", "type": "uint32", "internalType": "uint32"},
            {"name": "caller", "type": "address", "internalType": "address"},
        ],
        "outputs": [{"name": "", "type": "bytes", "internalType": "bytes"}],
        "stateMutability": "view",
    },
]

COORDINATOR_ABI = [
    {
        "type": "function",
        "name": "DELEGATEE_OVERHEAD_CACHED_WEI",
        "inputs": [],
        "outputs": [{"name": "", "type": "uint256", "internalType": "uint256"}],
        "stateMutability": "view",
    },
    {
        "type": "function",
        "name": "DELEGATEE_OVERHEAD_CREATE_WEI",
        "inputs": [],
        "outputs": [{"name": "", "type": "uint256", "internalType": "uint256"}],
        "stateMutability": "view",
    },
    {
        "type": "function",
        "name": "DELIVERY_OVERHEAD_WEI",
        "inputs": [],
        "outputs": [{"name": "", "type": "uint256", "internalType": "uint256"}],
        "stateMutability": "view",
    },
    {
        "type": "function",
        "name": "EIP712_NAME",
        "inputs": [],
        "outputs": [{"name": "", "type": "string", "internalType": "string"}],
        "stateMutability": "view",
    },
    {
        "type": "function",
        "name": "EIP712_VERSION",
        "inputs": [],
        "outputs": [{"name": "", "type": "string", "internalType": "string"}],
        "stateMutability": "view",
    },
    {
        "type": "function",
        "name": "activateNode",
        "inputs": [],
        "outputs": [],
        "stateMutability": "nonpayable",
    },
    {
        "type": "function",
        "name": "cancelSubscription",
        "inputs": [
            {
                "name": "subscriptionId",
                "type": "uint32",
                "internalType": "uint32",
            }
        ],
        "outputs": [],
        "stateMutability": "nonpayable",
    },
    {
        "type": "function",
        "name": "cooldown",
        "inputs": [],
        "outputs": [{"name": "", "type": "uint256", "internalType": "uint256"}],
        "stateMutability": "view",
    },
    {
        "type": "function",
        "name": "createSubscription",
        "inputs": [
            {"name": "containerId", "type": "string", "internalType": "string"},
            {"name": "inputs", "type": "bytes", "internalType": "bytes"},
            {"name": "maxGasPrice", "type": "uint48", "internalType": "uint48"},
            {"name": "maxGasLimit", "type": "uint32", "internalType": "uint32"},
            {"name": "frequency", "type": "uint32", "internalType": "uint32"},
            {"name": "period", "type": "uint32", "internalType": "uint32"},
            {"name": "redundancy", "type": "uint16", "internalType": "uint16"},
        ],
        "outputs": [{"name": "", "type": "uint32", "internalType": "uint32"}],
        "stateMutability": "nonpayable",
    },
    {
        "type": "function",
        "name": "createSubscriptionDelegatee",
        "inputs": [
            {"name": "nonce", "type": "uint32", "internalType": "uint32"},
            {"name": "expiry", "type": "uint32", "internalType": "uint32"},
            {
                "name": "sub",
                "type": "tuple",
                "internalType": "struct Coordinator.Subscription",
                "components": [
                    {
                        "name": "owner",
                        "type": "address",
                        "internalType": "address",
                    },
                    {
                        "name": "activeAt",
                        "type": "uint32",
                        "internalType": "uint32",
                    },
                    {
                        "name": "period",
                        "type": "uint32",
                        "internalType": "uint32",
                    },
                    {
                        "name": "frequency",
                        "type": "uint32",
                        "internalType": "uint32",
                    },
                    {
                        "name": "redundancy",
                        "type": "uint16",
                        "internalType": "uint16",
                    },
                    {
                        "name": "maxGasPrice",
                        "type": "uint48",
                        "internalType": "uint48",
                    },
                    {
                        "name": "maxGasLimit",
                        "type": "uint32",
                        "internalType": "uint32",
                    },
                    {
                        "name": "containerId",
                        "type": "string",
                        "internalType": "string",
                    },
                    {
                        "name": "inputs",
                        "type": "bytes",
                        "internalType": "bytes",
                    },
                ],
            },
            {"name": "v", "type": "uint8", "internalType": "uint8"},
            {"name": "r", "type": "bytes32", "internalType": "bytes32"},
            {"name": "s", "type": "bytes32", "internalType": "bytes32"},
        ],
        "outputs": [
            {"name": "", "type": "uint32", "internalType": "uint32"},
            {"name": "", "type": "bool", "internalType": "bool"},
        ],
        "stateMutability": "nonpayable",
    },
    {
        "type": "function",
        "name": "deactivateNode",
        "inputs": [],
        "outputs": [],
        "stateMutability": "nonpayable",
    },
    {
        "type": "function",
        "name": "delegateCreatedIds",
        "inputs": [{"name": "", "type": "bytes32", "internalType": "bytes32"}],
        "outputs": [{"name": "", "type": "uint32", "internalType": "uint32"}],
        "stateMutability": "view",
    },
    {
        "type": "function",
        "name": "deliverCompute",
        "inputs": [
            {
                "name": "subscriptionId",
                "type": "uint32",
                "internalType": "uint32",
            },
            {
                "name": "deliveryInterval",
                "type": "uint32",
                "internalType": "uint32",
            },
            {"name": "input", "type": "bytes", "internalType": "bytes"},
            {"name": "output", "type": "bytes", "internalType": "bytes"},
            {"name": "proof", "type": "bytes", "internalType": "bytes"},
        ],
        "outputs": [],
        "stateMutability": "nonpayable",
    },
    {
        "type": "function",
        "name": "deliverComputeDelegatee",
        "inputs": [
            {"name": "nonce", "type": "uint32", "internalType": "uint32"},
            {"name": "expiry", "type": "uint32", "internalType": "uint32"},
            {
                "name": "sub",
                "type": "tuple",
                "internalType": "struct Coordinator.Subscription",
                "components": [
                    {
                        "name": "owner",
                        "type": "address",
                        "internalType": "address",
                    },
                    {
                        "name": "activeAt",
                        "type": "uint32",
                        "internalType": "uint32",
                    },
                    {
                        "name": "period",
                        "type": "uint32",
                        "internalType": "uint32",
                    },
                    {
                        "name": "frequency",
                        "type": "uint32",
                        "internalType": "uint32",
                    },
                    {
                        "name": "redundancy",
                        "type": "uint16",
                        "internalType": "uint16",
                    },
                    {
                        "name": "maxGasPrice",
                        "type": "uint48",
                        "internalType": "uint48",
                    },
                    {
                        "name": "maxGasLimit",
                        "type": "uint32",
                        "internalType": "uint32",
                    },
                    {
                        "name": "containerId",
                        "type": "string",
                        "internalType": "string",
                    },
                    {
                        "name": "inputs",
                        "type": "bytes",
                        "internalType": "bytes",
                    },
                ],
            },
            {"name": "v", "type": "uint8", "internalType": "uint8"},
            {"name": "r", "type": "bytes32", "internalType": "bytes32"},
            {"name": "s", "type": "bytes32", "internalType": "bytes32"},
            {
                "name": "deliveryInterval",
                "type": "uint32",
                "internalType": "uint32",
            },
            {"name": "input", "type": "bytes", "internalType": "bytes"},
            {"name": "output", "type": "bytes", "internalType": "bytes"},
            {"name": "proof", "type": "bytes", "internalType": "bytes"},
        ],
        "outputs": [],
        "stateMutability": "nonpayable",
    },
    {
        "type": "function",
        "name": "eip712Domain",
        "inputs": [],
        "outputs": [
            {"name": "fields", "type": "bytes1", "internalType": "bytes1"},
            {"name": "name", "type": "string", "internalType": "string"},
            {"name": "version", "type": "string", "internalType": "string"},
            {"name": "chainId", "type": "uint256", "internalType": "uint256"},
            {
                "name": "verifyingContract",
                "type": "address",
                "internalType": "address",
            },
            {"name": "salt", "type": "bytes32", "internalType": "bytes32"},
            {
                "name": "extensions",
                "type": "uint256[]",
                "internalType": "uint256[]",
            },
        ],
        "stateMutability": "view",
    },
    {
        "type": "function",
        "name": "getSubscriptionInterval",
        "inputs": [
            {"name": "activeAt", "type": "uint32", "internalType": "uint32"},
            {"name": "period", "type": "uint32", "internalType": "uint32"},
        ],
        "outputs": [{"name": "", "type": "uint32", "internalType": "uint32"}],
        "stateMutability": "view",
    },
    {
        "type": "function",
        "name": "id",
        "inputs": [],
        "outputs": [{"name": "", "type": "uint32", "internalType": "uint32"}],
        "stateMutability": "view",
    },
    {
        "type": "function",
        "name": "maxSubscriberNonce",
        "inputs": [{"name": "", "type": "address", "internalType": "address"}],
        "outputs": [{"name": "", "type": "uint32", "internalType": "uint32"}],
        "stateMutability": "view",
    },
    {
        "type": "function",
        "name": "nodeInfo",
        "inputs": [{"name": "", "type": "address", "internalType": "address"}],
        "outputs": [
            {
                "name": "status",
                "type": "uint8",
                "internalType": "enum Manager.NodeStatus",
            },
            {
                "name": "cooldownStart",
                "type": "uint32",
                "internalType": "uint32",
            },
        ],
        "stateMutability": "view",
    },
    {
        "type": "function",
        "name": "nodeResponded",
        "inputs": [{"name": "", "type": "bytes32", "internalType": "bytes32"}],
        "outputs": [{"name": "", "type": "bool", "internalType": "bool"}],
        "stateMutability": "view",
    },
    {
        "type": "function",
        "name": "redundancyCount",
        "inputs": [{"name": "", "type": "bytes32", "internalType": "bytes32"}],
        "outputs": [{"name": "", "type": "uint16", "internalType": "uint16"}],
        "stateMutability": "view",
    },
    {
        "type": "function",
        "name": "registerNode",
        "inputs": [{"name": "node", "type": "address", "internalType": "address"}],
        "outputs": [],
        "stateMutability": "nonpayable",
    },
    {
        "type": "function",
        "name": "subscriptions",
        "inputs": [{"name": "", "type": "uint32", "internalType": "uint32"}],
        "outputs": [
            {"name": "owner", "type": "address", "internalType": "address"},
            {"name": "activeAt", "type": "uint32", "internalType": "uint32"},
            {"name": "period", "type": "uint32", "internalType": "uint32"},
            {"name": "frequency", "type": "uint32", "internalType": "uint32"},
            {"name": "redundancy", "type": "uint16", "internalType": "uint16"},
            {"name": "maxGasPrice", "type": "uint48", "internalType": "uint48"},
            {"name": "maxGasLimit", "type": "uint32", "internalType": "uint32"},
            {"name": "containerId", "type": "string", "internalType": "string"},
            {"name": "inputs", "type": "bytes", "internalType": "bytes"},
        ],
        "stateMutability": "view",
    },
    {
        "type": "event",
        "name": "NodeActivated",
        "inputs": [
            {
                "name": "node",
                "type": "address",
                "indexed": True,
                "internalType": "address",
            }
        ],
        "anonymous": False,
    },
    {
        "type": "event",
        "name": "NodeDeactivated",
        "inputs": [
            {
                "name": "node",
                "type": "address",
                "indexed": True,
                "internalType": "address",
            }
        ],
        "anonymous": False,
    },
    {
        "type": "event",
        "name": "NodeRegistered",
        "inputs": [
            {
                "name": "node",
                "type": "address",
                "indexed": True,
                "internalType": "address",
            },
            {
                "name": "registerer",
                "type": "address",
                "indexed": True,
                "internalType": "address",
            },
            {
                "name": "cooldownStart",
                "type": "uint32",
                "indexed": False,
                "internalType": "uint32",
            },
        ],
        "anonymous": False,
    },
    {
        "type": "event",
        "name": "SubscriptionCancelled",
        "inputs": [
            {
                "name": "id",
                "type": "uint32",
                "indexed": True,
                "internalType": "uint32",
            }
        ],
        "anonymous": False,
    },
    {
        "type": "event",
        "name": "SubscriptionCreated",
        "inputs": [
            {
                "name": "id",
                "type": "uint32",
                "indexed": True,
                "internalType": "uint32",
            }
        ],
        "anonymous": False,
    },
    {
        "type": "event",
        "name": "SubscriptionFulfilled",
        "inputs": [
            {
                "name": "id",
                "type": "uint32",
                "indexed": True,
                "internalType": "uint32",
            },
            {
                "name": "node",
                "type": "address",
                "indexed": True,
                "internalType": "address",
            },
        ],
        "anonymous": False,
    },
    {
        "type": "error",
        "name": "CooldownActive",
        "inputs": [
            {
                "name": "cooldownStart",
                "type": "uint32",
                "internalType": "uint32",
            }
        ],
    },
    {"type": "error", "name": "GasLimitExceeded", "inputs": []},
    {"type": "error", "name": "GasPriceExceeded", "inputs": []},
    {"type": "error", "name": "IntervalCompleted", "inputs": []},
    {"type": "error", "name": "IntervalMismatch", "inputs": []},
    {
        "type": "error",
        "name": "NodeNotActivateable",
        "inputs": [
            {
                "name": "status",
                "type": "uint8",
                "internalType": "enum Manager.NodeStatus",
            }
        ],
    },
    {"type": "error", "name": "NodeNotActive", "inputs": []},
    {
        "type": "error",
        "name": "NodeNotRegisterable",
        "inputs": [
            {"name": "node", "type": "address", "internalType": "address"},
            {
                "name": "status",
                "type": "uint8",
                "internalType": "enum Manager.NodeStatus",
            },
        ],
    },
    {"type": "error", "name": "NodeRespondedAlready", "inputs": []},
    {"type": "error", "name": "NotSubscriptionOwner", "inputs": []},
    {"type": "error", "name": "SignatureExpired", "inputs": []},
    {"type": "error", "name": "SignerMismatch", "inputs": []},
    {"type": "error", "name": "SubscriptionCompleted", "inputs": []},
    {"type": "error", "name": "SubscriptionNotActive", "inputs": []},
    {"type": "error", "name": "SubscriptionNotFound", "inputs": []},
]
