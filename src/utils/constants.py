from typing import cast

from eth_typing import ChecksumAddress

ZERO_ADDRESS: ChecksumAddress = cast(
    ChecksumAddress, "0x0000000000000000000000000000000000000000"
)

DELEGATED_SIGNER_ABI = [
    {
        "type": "function",
        "name": "getSigner",
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
        "type": "constructor",
        "inputs": [
            {
                "name": "registry",
                "type": "address",
                "internalType": "contract Registry",
            }
        ],
        "stateMutability": "nonpayable",
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
        "name": "cancelSubscription",
        "inputs": [
            {"name": "subscriptionId", "type": "uint32", "internalType": "uint32"}
        ],
        "outputs": [],
        "stateMutability": "nonpayable",
    },
    {
        "type": "function",
        "name": "createSubscription",
        "inputs": [
            {"name": "containerId", "type": "string", "internalType": "string"},
            {"name": "frequency", "type": "uint32", "internalType": "uint32"},
            {"name": "period", "type": "uint32", "internalType": "uint32"},
            {"name": "redundancy", "type": "uint16", "internalType": "uint16"},
            {"name": "lazy", "type": "bool", "internalType": "bool"},
            {"name": "paymentToken", "type": "address", "internalType": "address"},
            {"name": "paymentAmount", "type": "uint256", "internalType": "uint256"},
            {"name": "wallet", "type": "address", "internalType": "address"},
            {"name": "verifier", "type": "address", "internalType": "address"},
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
                "internalType": "struct Subscription",
                "components": [
                    {"name": "owner", "type": "address", "internalType": "address"},
                    {"name": "activeAt", "type": "uint32", "internalType": "uint32"},
                    {"name": "period", "type": "uint32", "internalType": "uint32"},
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
                        "name": "containerId",
                        "type": "bytes32",
                        "internalType": "bytes32",
                    },
                    {"name": "lazy", "type": "bool", "internalType": "bool"},
                    {
                        "name": "verifier",
                        "type": "address",
                        "internalType": "address payable",
                    },
                    {
                        "name": "paymentAmount",
                        "type": "uint256",
                        "internalType": "uint256",
                    },
                    {
                        "name": "paymentToken",
                        "type": "address",
                        "internalType": "address",
                    },
                    {
                        "name": "wallet",
                        "type": "address",
                        "internalType": "address payable",
                    },
                ],
            },
            {"name": "v", "type": "uint8", "internalType": "uint8"},
            {"name": "r", "type": "bytes32", "internalType": "bytes32"},
            {"name": "s", "type": "bytes32", "internalType": "bytes32"},
        ],
        "outputs": [{"name": "", "type": "uint32", "internalType": "uint32"}],
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
            {"name": "subscriptionId", "type": "uint32", "internalType": "uint32"},
            {"name": "deliveryInterval", "type": "uint32", "internalType": "uint32"},
            {"name": "input", "type": "bytes", "internalType": "bytes"},
            {"name": "output", "type": "bytes", "internalType": "bytes"},
            {"name": "proof", "type": "bytes", "internalType": "bytes"},
            {"name": "nodeWallet", "type": "address", "internalType": "address"},
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
                "internalType": "struct Subscription",
                "components": [
                    {"name": "owner", "type": "address", "internalType": "address"},
                    {"name": "activeAt", "type": "uint32", "internalType": "uint32"},
                    {"name": "period", "type": "uint32", "internalType": "uint32"},
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
                        "name": "containerId",
                        "type": "bytes32",
                        "internalType": "bytes32",
                    },
                    {"name": "lazy", "type": "bool", "internalType": "bool"},
                    {
                        "name": "verifier",
                        "type": "address",
                        "internalType": "address payable",
                    },
                    {
                        "name": "paymentAmount",
                        "type": "uint256",
                        "internalType": "uint256",
                    },
                    {
                        "name": "paymentToken",
                        "type": "address",
                        "internalType": "address",
                    },
                    {
                        "name": "wallet",
                        "type": "address",
                        "internalType": "address payable",
                    },
                ],
            },
            {"name": "v", "type": "uint8", "internalType": "uint8"},
            {"name": "r", "type": "bytes32", "internalType": "bytes32"},
            {"name": "s", "type": "bytes32", "internalType": "bytes32"},
            {"name": "deliveryInterval", "type": "uint32", "internalType": "uint32"},
            {"name": "input", "type": "bytes", "internalType": "bytes"},
            {"name": "output", "type": "bytes", "internalType": "bytes"},
            {"name": "proof", "type": "bytes", "internalType": "bytes"},
            {"name": "nodeWallet", "type": "address", "internalType": "address"},
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
            {"name": "extensions", "type": "uint256[]", "internalType": "uint256[]"},
        ],
        "stateMutability": "view",
    },
    {
        "type": "function",
        "name": "finalizeProofValidation",
        "inputs": [
            {"name": "subscriptionId", "type": "uint32", "internalType": "uint32"},
            {"name": "interval", "type": "uint32", "internalType": "uint32"},
            {"name": "node", "type": "address", "internalType": "address"},
            {"name": "valid", "type": "bool", "internalType": "bool"},
        ],
        "outputs": [],
        "stateMutability": "nonpayable",
    },
    {
        "type": "function",
        "name": "getSubscription",
        "inputs": [
            {"name": "subscriptionId", "type": "uint32", "internalType": "uint32"}
        ],
        "outputs": [
            {
                "name": "",
                "type": "tuple",
                "internalType": "struct Subscription",
                "components": [
                    {"name": "owner", "type": "address", "internalType": "address"},
                    {"name": "activeAt", "type": "uint32", "internalType": "uint32"},
                    {"name": "period", "type": "uint32", "internalType": "uint32"},
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
                        "name": "containerId",
                        "type": "bytes32",
                        "internalType": "bytes32",
                    },
                    {"name": "lazy", "type": "bool", "internalType": "bool"},
                    {
                        "name": "verifier",
                        "type": "address",
                        "internalType": "address payable",
                    },
                    {
                        "name": "paymentAmount",
                        "type": "uint256",
                        "internalType": "uint256",
                    },
                    {
                        "name": "paymentToken",
                        "type": "address",
                        "internalType": "address",
                    },
                    {
                        "name": "wallet",
                        "type": "address",
                        "internalType": "address payable",
                    },
                ],
            }
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
        "name": "nodeResponded",
        "inputs": [{"name": "", "type": "bytes32", "internalType": "bytes32"}],
        "outputs": [{"name": "", "type": "bool", "internalType": "bool"}],
        "stateMutability": "view",
    },
    {
        "type": "function",
        "name": "proofRequests",
        "inputs": [{"name": "", "type": "bytes32", "internalType": "bytes32"}],
        "outputs": [
            {"name": "expiry", "type": "uint32", "internalType": "uint32"},
            {
                "name": "nodeWallet",
                "type": "address",
                "internalType": "contract Wallet",
            },
            {
                "name": "consumerEscrowed",
                "type": "uint256",
                "internalType": "uint256",
            },
        ],
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
    {"type": "error", "name": "IntervalCompleted", "inputs": []},
    {"type": "error", "name": "IntervalMismatch", "inputs": []},
    {"type": "error", "name": "InvalidWallet", "inputs": []},
    {"type": "error", "name": "NodeRespondedAlready", "inputs": []},
    {"type": "error", "name": "NotSubscriptionOwner", "inputs": []},
    {"type": "error", "name": "ProofRequestNotFound", "inputs": []},
    {"type": "error", "name": "Reentrancy", "inputs": []},
    {"type": "error", "name": "SignatureExpired", "inputs": []},
    {"type": "error", "name": "SignerMismatch", "inputs": []},
    {"type": "error", "name": "SubscriptionCompleted", "inputs": []},
    {"type": "error", "name": "SubscriptionNotActive", "inputs": []},
    {"type": "error", "name": "SubscriptionNotFound", "inputs": []},
    {"type": "error", "name": "UnauthorizedVerifier", "inputs": []},
    {"type": "error", "name": "UnsupportedVerifierToken", "inputs": []},
]

WALLET_FACTORY_ABI = [
    {
        "type": "function",
        "name": "isValidWallet",
        "inputs": [{"name": "wallet", "type": "address", "internalType": "address"}],
        "outputs": [{"name": "", "type": "bool", "internalType": "bool"}],
        "stateMutability": "view",
    }
]

REGISTRY_ABI = [
    {
        "type": "function",
        "name": "COORDINATOR",
        "inputs": [],
        "outputs": [{"name": "", "type": "address", "internalType": "address"}],
        "stateMutability": "view",
    },
    {
        "type": "function",
        "name": "FEE",
        "inputs": [],
        "outputs": [{"name": "", "type": "address", "internalType": "address"}],
        "stateMutability": "view",
    },
    {
        "type": "function",
        "name": "INBOX",
        "inputs": [],
        "outputs": [{"name": "", "type": "address", "internalType": "address"}],
        "stateMutability": "view",
    },
    {
        "type": "function",
        "name": "READER",
        "inputs": [],
        "outputs": [{"name": "", "type": "address", "internalType": "address"}],
        "stateMutability": "view",
    },
    {
        "type": "function",
        "name": "WALLET_FACTORY",
        "inputs": [],
        "outputs": [{"name": "", "type": "address", "internalType": "address"}],
        "stateMutability": "view",
    },
]

ERC20_ABI = [
    {
        "type": "function",
        "name": "balanceOf",
        "inputs": [{"name": "owner", "type": "address", "internalType": "address"}],
        "outputs": [{"name": "result", "type": "uint256", "internalType": "uint256"}],
        "stateMutability": "view",
    },
]

PAYMENT_WALLET_ABI = [
    {
        "type": "function",
        "name": "approve",
        "inputs": [
            {"name": "spender", "type": "address", "internalType": "address"},
            {"name": "token", "type": "address", "internalType": "address"},
            {"name": "amount", "type": "uint256", "internalType": "uint256"},
        ],
        "outputs": [],
        "stateMutability": "nonpayable",
    },
    {
        "type": "function",
        "name": "allowance",
        "inputs": [
            {"name": "", "type": "address", "internalType": "address"},
            {"name": "", "type": "address", "internalType": "address"},
        ],
        "outputs": [{"name": "", "type": "uint256", "internalType": "uint256"}],
        "stateMutability": "view",
    },
    {
        "type": "function",
        "name": "owner",
        "inputs": [],
        "outputs": [{"name": "result", "type": "address", "internalType": "address"}],
        "stateMutability": "view",
    },
]

READER_ABI = [
    {
        "inputs": [{"internalType": "contract Registry", "name": "registry", "type": "address"}],
        "stateMutability": "nonpayable",
        "type": "constructor"
    },
    {
        "inputs": [
            {"internalType": "uint32[]", "name": "ids", "type": "uint32[]"},
            {"internalType": "uint32[]", "name": "intervals", "type": "uint32[]"}
        ],
        "name": "readRedundancyCountBatch",
        "outputs": [{"internalType": "uint16[]", "name": "", "type": "uint16[]"}],
        "stateMutability": "view",
        "type": "function"
    },
    {
        "inputs": [
            {"internalType": "uint32", "name": "startId", "type": "uint32"},
            {"internalType": "uint32", "name": "endId", "type": "uint32"}
        ],
        "name": "readSubscriptionBatch",
        "outputs": [
            {
                "components": [
                    {"internalType": "address", "name": "owner", "type": "address"},
                    {"internalType": "uint32", "name": "activeAt", "type": "uint32"},
                    {"internalType": "uint32", "name": "period", "type": "uint32"},
                    {"internalType": "uint32", "name": "frequency", "type": "uint32"},
                    {"internalType": "uint16", "name": "redundancy", "type": "uint16"},
                    {"internalType": "bytes32", "name": "containerId", "type": "bytes32"},
                    {"internalType": "bool", "name": "lazy", "type": "bool"},
                    {"internalType": "address payable", "name": "verifier", "type": "address"},
                    {"internalType": "uint256", "name": "paymentAmount", "type": "uint256"},
                    {"internalType": "address", "name": "paymentToken", "type": "address"},
                    {"internalType": "address payable", "name": "wallet", "type": "address"}
                ],
                "internalType": "struct Subscription[]",
                "name": "",
                "type": "tuple[]"
            }
        ],
        "stateMutability": "view",
        "type": "function"
    }
]
