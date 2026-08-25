# encoding: utf-8
import asyncio
import aiohttp
from fastapi import HTTPException
from endpoints.get_circulating_supply import get_circulating_coins
from server import app

NONKYC_TICKER_URL = "https://api.nonkyc.io/api/v2/ticker/KLS/USDT"

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

    last_price      = float(ticker["last_price"])
    high            = float(ticker["high"])
    low             = float(ticker["low"])
    bid             = float(ticker["bid"])
    ask             = float(ticker["ask"])
    base_volume     = float(ticker["base_volume"])
    usd_volume      = float(ticker["usd_volume_est"])
    change_pct      = float(ticker["change_percent"])
    prev_day_price  = float(ticker["previous_day_price"])

    spread_percent  = round((ask - bid) / bid * 100, 3) if bid > 0 else 0.0
    price_direction = "up" if last_price >= prev_day_price else "down"
    market_cap      = round(last_price * circulating, 2)

    return {
        "current_price":               {"usd": last_price},
        "price_change_percentage_24h": change_pct,
        "high_24h":                    {"usd": high},
        "low_24h":                     {"usd": low},
        "total_volume":                {"usd": usd_volume},
        "market_cap":                  {"usd": market_cap},
        "circulating_supply":          circulating,
        "best_bid":                    bid,
        "best_ask":                    ask,
        "volume_kls":                  base_volume,
        "previous_day_price":          prev_day_price,
        "price_direction":             price_direction,
        "spread_percent":              spread_percent,
    }
