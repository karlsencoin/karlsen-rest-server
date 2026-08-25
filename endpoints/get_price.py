# encoding: utf-8
import os
from pydantic import BaseModel
from starlette.responses import PlainTextResponse
from endpoints import mainnet_only
from helper import get_kls_price
from server import app

DISABLE_PRICE = os.getenv("DISABLE_PRICE", "false").lower() == "true"


class PriceResponse(BaseModel):
    price: float = 0.025235


@app.get("/info/price", response_model=PriceResponse | str, tags=["Karlsen network info"])
@mainnet_only
async def get_price(stringOnly: bool = False):
    """
    Returns the current KLS price in USD (source: NonKYC ticker).
    """
    price = await get_kls_price() if not DISABLE_PRICE else 0
    if stringOnly:
        return PlainTextResponse(content=str(price))
    return {"price": price}
