# encoding: utf-8
import asyncio
import aiohttp
from fastapi import HTTPException

from endpoints.get_circulating_supply import get_circulating_coins
from server import app

NONKYC_TICKER_URL = "https://nonkyc.io/api/v2/ticker/KLS_USDT"


@app.get("/info/market-data", tags=["Karlsen network info"])
async def get_market_data():
    """
    KLS market data: NonKYC ticker (price, volume, bid/ask) + circulating supply.
    Fetches ticker and circulating supply in parallel.
    """
    async def _fetch_ticker(session: aiohttp.ClientSession) -> dict:
        async with session.get(NONKYC_TICKER_URL) as resp:
            if resp.status != 200:
                raise HTTPException(status_code=502, detail="NonKYC ticker unavailable")
            return await resp.json(content_type=None)

    try:
        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=10)
        ) as session:
            ticker, circ_str = await asyncio.gather(
                _fetch_ticker(session),
                get_circulating_coins(),
            )
    except aiohttp.ClientError as e:
        raise HTTPException(status_code=503, detail=f"Upstream request failed: {e}")

    try:
        circulating = float(circ_str)
    except (ValueError, TypeError):
        circulating = 0.0

    last_price  = float(ticker["last_price"])
    high        = float(ticker["high"])
    low         = float(ticker["low"])
    bid         = float(ticker["bid"])
    ask         = float(ticker["ask"])
    base_volume = float(ticker["base_volume"])
    usd_volume  = float(ticker["usd_volume_est"])

    spread_percent   = round((ask - bid) / bid * 100, 3) if bid > 0 else 0.0
    yesterday_price  = high  # best available proxy (NonKYC 24h high)
    price_change_pct = (
        round((last_price - yesterday_price) / yesterday_price * 100, 2)
        if yesterday_price > 0 else 0.0
    )
    price_direction = "up" if last_price >= bid else "down"
    market_cap      = round(last_price * circulating, 2)

    return {
        "current_price":               {"usd": last_price},
        "price_change_percentage_24h": price_change_pct,
        "high_24h":                    {"usd": high},
        "low_24h":                     {"usd": low},
        "total_volume":                {"usd": usd_volume},
        "market_cap":                  {"usd": market_cap},
        "circulating_supply":          circulating,
        "best_bid":                    bid,
        "best_ask":                    ask,
        "volume_kls":                  base_volume,
        "yesterday_price":             yesterday_price,
        "price_direction":             price_direction,
        "spread_percent":              spread_percent,
    }
