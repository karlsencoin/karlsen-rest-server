# encoding: utf-8
import re
from asyncio import wait_for
from typing import List

from fastapi import HTTPException
from kaspa_script_address import to_script
from pydantic import BaseModel

from constants import ADDRESS_EXAMPLE, REGEX_KARLSEN_ADDRESS
from karlsend.KarlsendRpcClient import karlsend_rpc_client
from server import app, karlsend_client


class BalancesByAddressEntry(BaseModel):
    address: str = ADDRESS_EXAMPLE
    balance: int = 12451591699


class BalanceRequest(BaseModel):
    addresses: list[str] = [ADDRESS_EXAMPLE]


@app.post("/addresses/balances", response_model=List[BalancesByAddressEntry], tags=["Karlsen addresses"])
async def get_balances_from_karlsen_addresses(body: BalanceRequest):
    """
    Get balances for multiple karlsen addresses
    """
    if not body.addresses:
        return []

    for karlsenAddress in body.addresses:
        if not re.search(REGEX_KARLSEN_ADDRESS, karlsenAddress):
            raise HTTPException(status_code=400, detail=f"Invalid address: {karlsenAddress}")

    rpc_client = await karlsend_rpc_client()
    request = {"addresses": body.addresses}
    if rpc_client:
        balances = await wait_for(rpc_client.get_balances_by_addresses(request), 10)
    else:
        resp = await karlsend_client.request("getBalancesByAddressesRequest", request)
        if resp.get("error"):
            raise HTTPException(500, resp["error"])
        balances = resp["getBalancesByAddressesResponse"]

    return balances["entries"]
