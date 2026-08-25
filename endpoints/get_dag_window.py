# encoding: utf-8
import asyncio
import logging
from asyncio import wait_for
from typing import Any

from endpoints.get_blocks import convert_to_legacy_block
from karlsend.KarlsendRpcClient import karlsend_rpc_client
from server import app, karlsend_client

_logger = logging.getLogger(__name__)

WINDOW_SIZE = 200
TRAVERSE_DEPTH = WINDOW_SIZE + 60  # extra buffer for DAG width (parallel blocks)
UPDATE_INTERVAL = 2.0              # seconds between incremental updates

_cache: dict[str, Any] = {"blocks": [], "newestDaa": 0, "count": 0}
_cache_lock = asyncio.Lock()


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _parse_block(block: dict) -> dict:
    """Extract dag-window fields from a normalized (legacy-format) block dict."""
    header = block.get("header", {})
    vd = block.get("verboseData", {})
    parents = [
        h
        for level in header.get("parents", [])
        for h in level.get("parentHashes", [])
    ]
    return {
        "hash":                vd.get("hash", ""),
        "daaScore":            int(header.get("daaScore") or 0),
        "blueScore":           int(vd.get("blueScore") or 0),
        "parents":             parents,
        "isChainBlock":        bool(vd.get("isChainBlock", False)),
        "selectedParentHash":  vd.get("selectedParentHash", ""),
        "mergeSetBluesHashes": list(vd.get("mergeSetBluesHashes") or []),
        "mergeSetRedsHashes":  list(vd.get("mergeSetRedsHashes") or []),
        "blockTime":           int(header.get("timestamp") or 0),
    }


async def _get_single_block(hash_str: str) -> dict:
    """Fetch one block without transactions. Returns normalized block dict."""
    rpc_client = await karlsend_rpc_client()
    request = {"hash": hash_str, "includeTransactions": False}
    if rpc_client:
        try:
            resp = await wait_for(rpc_client.get_block(request), 10)
            block = resp.get("block", {})
            convert_to_legacy_block(block)
            return block
        except Exception:
            pass
    resp = await karlsend_client.request("getBlockRequest", request)
    return resp.get("getBlockResponse", {}).get("block", {})


async def _get_blocks_after(low_hash: str) -> list[dict]:
    """Fetch all blocks after low_hash (inclusive of the next blocks). Returns parsed list."""
    rpc_client = await karlsend_rpc_client()
    request = {"lowHash": low_hash, "includeBlocks": True, "includeTransactions": False}
    if rpc_client:
        try:
            resp = await wait_for(rpc_client.get_blocks(request), 60)
            for b in resp.get("blocks", []):
                convert_to_legacy_block(b)
            return [_parse_block(b) for b in resp.get("blocks", [])]
        except Exception:
            return []
    resp = await karlsend_client.request("getBlocksRequest", request)
    raw = resp.get("getBlocksResponse", {}).get("blocks", [])
    return [_parse_block(b) for b in raw]


async def _get_dag_info() -> dict:
    """Return getBlockDagInfo response dict."""
    rpc_client = await karlsend_rpc_client()
    if rpc_client:
        try:
            return await wait_for(rpc_client.get_block_dag_info(), 10)
        except Exception:
            pass
    resp = await karlsend_client.request("getBlockDagInfoRequest")
    return resp.get("getBlockDagInfoResponse", {})


# ---------------------------------------------------------------------------
# Cache management
# ---------------------------------------------------------------------------

async def _initialize():
    """
    Cold-start: walk selectedParent chain TRAVERSE_DEPTH steps back from the
    current sink, then call getBlocks to populate the window.
    One-time cost of TRAVERSE_DEPTH gRPC round-trips (fast on localhost).
    """
    _logger.info("[dag_window] cold-start initialization...")

    dag_info = await _get_dag_info()
    sink_hash = dag_info.get("sink", "")
    if not sink_hash:
        _logger.warning("[dag_window] no sink hash from dag_info; retrying next cycle")
        return

    # Walk selectedParent chain backwards
    current_hash = sink_hash
    for step in range(TRAVERSE_DEPTH):
        block = await _get_single_block(current_hash)
        parent = block.get("verboseData", {}).get("selectedParentHash", "")
        if not parent:
            _logger.warning(f"[dag_window] selectedParentHash missing at step {step}")
            break
        current_hash = parent

    low_hash = current_hash
    blocks = await _get_blocks_after(low_hash)
    blocks.sort(key=lambda b: b["daaScore"])
    window = blocks[-WINDOW_SIZE:]

    async with _cache_lock:
        _cache["blocks"] = window
        _cache["newestDaa"] = window[-1]["daaScore"] if window else 0
        _cache["count"] = len(window)

    _logger.info(
        f"[dag_window] initialized: {len(window)} blocks, newestDaa={_cache['newestDaa']}"
    )


async def _update():
    """
    Incremental update: fetch only blocks produced since the newest cached block.
    At 1 BPS and 2 s interval this is typically 1-2 new blocks per call.
    """
    async with _cache_lock:
        current_blocks = list(_cache["blocks"])

    if not current_blocks:
        await _initialize()
        return

    newest = max(current_blocks, key=lambda b: b["daaScore"])
    new_blocks = await _get_blocks_after(newest["hash"])

    if not new_blocks:
        return

    # Merge (by hash), sort, trim to window size
    combined = {b["hash"]: b for b in current_blocks}
    for b in new_blocks:
        combined[b["hash"]] = b

    window = sorted(combined.values(), key=lambda b: b["daaScore"])[-WINDOW_SIZE:]

    async with _cache_lock:
        _cache["blocks"] = window
        _cache["newestDaa"] = window[-1]["daaScore"] if window else 0
        _cache["count"] = len(window)


async def dag_window_background_loop():
    """
    Background task: initialize once, then keep the cache fresh every
    UPDATE_INTERVAL seconds. Start with asyncio.create_task() in startup.
    """
    try:
        await _initialize()
    except Exception:
        _logger.exception("[dag_window] initialization failed")

    while True:
        await asyncio.sleep(UPDATE_INTERVAL)
        try:
            await _update()
        except Exception:
            _logger.exception("[dag_window] incremental update failed")


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------

@app.get("/info/dag-window", tags=["Karlsen network info"])
async def get_dag_window():
    """
    Last 200 blocks of the Karlsen DAG for visualization.
    Served from an in-memory cache updated every 2 seconds.
    """
    async with _cache_lock:
        return dict(_cache)
