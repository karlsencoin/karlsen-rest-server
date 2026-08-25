# Thin wrapper around the upstream wRPC SDK package.
# All application code imports from here — never import the SDK package directly.
from kaspa import (
    RpcClient,
    Resolver,
    Address,
    ScriptPublicKey,
    PublicKey,
    pay_to_address_script,
    address_from_script_public_key,
)

# kaspa_script_address is a low-level C extension; re-export here so application
# code never imports it directly.
from kaspa_script_address import to_address, to_script

# Transaction-related types — required by submit_transaction_request.py
from kaspa import (
    Transaction,
    TransactionInput,
    TransactionOutpoint,
    TransactionOutput,
    Hash,
)
