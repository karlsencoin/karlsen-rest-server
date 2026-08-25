# encoding: utf-8
from asyncio import wait_for

from fastapi import HTTPException
from typing import List

from karlsend.KarlsendRpcClient import karlsend_rpc_client
from server import app, karlsend_client
from pydantic import BaseModel


class FeeEstimateBucket(BaseModel):
    feerate: int = 1
    estimatedSeconds: float = 0.004


class FeeEstimateResponse(BaseModel):
    priorityBucket: FeeEstimateBucket
    normalBuckets: List[FeeEstimateBucket]
    lowBuckets: List[FeeEstimateBucket]


@app.get("/info/fee-estimate", response_model=FeeEstimateResponse, tags=["Karlsen network info"])
async def get_fee_estimate():
    """
    Get fee estimate from Karlsend.

    For all buckets, feerate values represent fee/mass of a transaction in `sompi/gram` units.<br>
    Given a feerate value recommendation, calculate the required fee by
    taking the transaction mass and multiplying it by feerate: `fee = feerate * mass(tx)`
    """
    rpc_client = await karlsend_rpc_client()
    if rpc_client:
        fee_estimate = await wait_for(rpc_client.get_fee_estimate(), 10)
    else:
        resp = await karlsend_client.request("getFeeEstimateRequest")
        if resp.get("error"):
            raise HTTPException(500, resp["error"])
        fee_estimate = resp["getFeeEstimateResponse"]

    return fee_estimate["estimate"]
