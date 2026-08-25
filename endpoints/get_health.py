# encoding: utf-8
import hashlib
import logging
import time
from asyncio import wait_for
from typing import List

from pydantic import BaseModel
from sqlalchemy import select
from fastapi.responses import JSONResponse
from karlsend.KarlsendRpcClient import karlsend_rpc_client

from constants import BPS, HEALTH_TOLERANCE_DOWN
from dbsession import async_session_blocks, async_session
from endpoints.get_virtual_chain_blue_score import current_blue_score_data
from models.Block import Block
from models.Transaction import Transaction
from models.TransactionAcceptance import TransactionAcceptance
from server import app, karlsend_client


_logger = logging.getLogger(__name__)


class KarlsendResponse(BaseModel):
    karlsendHost: str | None
    serverVersion: str = "0.12.6"
    isUtxoIndexed: bool = True
    isSynced: bool = True
    p2pId: str = "1231312"
    blueScore: int = 0


class DBCheckStatus(BaseModel):
    isSynced: bool = True
    blueScore: int | None
    blueScoreDiff: int | None
    acceptedTxBlockTime: int | None
    acceptedTxBlockTimeDiff: int | None


class HealthResponse(BaseModel):
    karlsendServers: List[KarlsendResponse]
    database: DBCheckStatus


@app.get("/info/health", response_model=HealthResponse, tags=["Karlsen network info"])
async def health_state():
    """
    Checks node and database health by comparing blue score and sync status.
    Returns health details or 503 if the database lags by ~10min or no nodes are synced.
    """
    current_blue_score_node = current_blue_score_data.get("blue_score")

    try:
        async with async_session_blocks() as s:
            last_blue_score_db = (
                await s.execute(select(Block.blue_score).order_by(Block.blue_score.desc()).limit(1))
            ).scalar()
        if last_blue_score_db is None or current_blue_score_node is None:
            db_check_status = DBCheckStatus(isSynced=False, blueScore=last_blue_score_db)
        else:
            blue_score_diff = abs(current_blue_score_node - last_blue_score_db)
            is_synced = blue_score_diff < HEALTH_TOLERANCE_DOWN * BPS
            db_check_status = DBCheckStatus(
                isSynced=is_synced, blueScore=last_blue_score_db, blueScoreDiff=blue_score_diff
            )
        async with async_session() as s:
            last_accepted_tx_block_time_db = (
                await s.execute(
                    select(Transaction.block_time)
                    .join(TransactionAcceptance, Transaction.transaction_id == TransactionAcceptance.transaction_id)
                    .order_by(Transaction.block_time.desc())
                    .limit(1)
                )
            ).scalar()
            time_diff = abs(int(time.time()) - int(last_accepted_tx_block_time_db) / 1000)
            db_check_status.isSynced = db_check_status.isSynced and time_diff < HEALTH_TOLERANCE_DOWN
            db_check_status.acceptedTxBlockTime = last_accepted_tx_block_time_db
            db_check_status.acceptedTxBlockTimeDiff = time_diff

    except Exception:
        db_check_status = DBCheckStatus(isSynced=False)

    await karlsend_client.initialize_all()
    karlsends = []

    rpc_client = await karlsend_rpc_client()
    if rpc_client:
        karlsend = {
            "karlsendHost": "wrpc",
            "isUtxoIndexed": False,
            "isSynced": False,
        }
        try:
            rpc_client_info = await wait_for(rpc_client.get_info(), 10)
            karlsend["serverVersion"] = rpc_client_info["serverVersion"]
            karlsend["isUtxoIndexed"] = rpc_client_info["isUtxoIndexed"]
            karlsend["isSynced"] = rpc_client_info["isSynced"]
            karlsend["p2pId"] = hashlib.sha256(rpc_client_info["p2pId"].encode()).hexdigest()
            karlsend["blueScore"] = (await wait_for(rpc_client.get_sink_blue_score(), 10))["blueScore"]
        except Exception as err:
            _logger.error("Kaspad health check failed %s", err)
        karlsends.append(karlsend)

    elif karlsend_client.karlsends:
        for i, k in enumerate(karlsend_client.karlsends):
            karlsend = {
                "karlsendHost": f"KARLSEND_HOST_{i + 1}",
                "isUtxoIndexed": False,
                "isSynced": False,
            }
            try:
                karlsend["serverVersion"] = k.server_version
                karlsend["isUtxoIndexed"] = k.is_utxo_indexed
                karlsend["isSynced"] = k.is_synced
                karlsend["p2pId"] = hashlib.sha256(k.p2p_id.encode()).hexdigest()
                karlsend["blueScore"] = current_blue_score_node
            except Exception as err:
                _logger.error("Kaspad health check failed %s", err)
            karlsends.append(karlsend)

    result = {
        "karlsendServers": karlsends,
        "database": db_check_status.dict(),
    }

    if not db_check_status.isSynced or not any(karlsend["isSynced"] for karlsend in karlsends):
        return JSONResponse(status_code=503, content=result)

    return result
