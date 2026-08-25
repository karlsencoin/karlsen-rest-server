# encoding: utf-8
import logging
import aiocache
import aiohttp
from aiocache import cached

CACHE = None
_logger = logging.getLogger(__name__)
aiocache.logger.setLevel(logging.WARNING)

NONKYC_TICKER_URL = "https://api.nonkyc.io/api/v2/ticker/KLS/USDT"


@cached(ttl=60)
async def get_kls_price():
    """
    Returns last KLS/USDT price as float. Falls back to last cached value on error,
    or 0.0 if never populated.
    """
    market_data = await get_kls_market_data()
    return market_data.get("current_price", {}).get("usd", 0.0)


@cached(ttl=60)
async def get_kls_market_data():
    """
    Fetch KLS ticker from NonKYC and normalize to a CoinGecko-ish shape so any
    legacy caller reading current_price.usd, high_24h.usd, low_24h.usd,
    total_volume.usd, or price_change_percentage_24h keeps working.
    Returns last cached value on network/parse error; empty dict if never populated.
    """
    global CACHE
    try:
        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=10)
        ) as session:
            async with session.get(NONKYC_TICKER_URL) as resp:
                if resp.status != 200:
                    _logger.error(f"NonKYC ticker HTTP {resp.status}")
                    return CACHE or {}
                ticker = await resp.json(content_type=None)
    except aiohttp.ClientError as e:
        _logger.error(f"NonKYC ticker fetch failed: {e}")
        return CACHE or {}

    try:
        last_price = float(ticker["last_price"])
    except (KeyError, ValueError, TypeError):
        _logger.error("NonKYC ticker missing/invalid last_price")
        return CACHE or {}

    CACHE = {
        "current_price":               {"usd": last_price},
        "high_24h":                    {"usd": float(ticker.get("high", 0) or 0)},
        "low_24h":                     {"usd": float(ticker.get("low", 0) or 0)},
        "total_volume":                {"usd": float(ticker.get("usd_volume_est", 0) or 0)},
        "price_change_percentage_24h": float(ticker.get("change_percent", 0) or 0),
    }
    return CACHE


# Backwards-compat aliases — remove after all callers migrated to _kls_ names.
get_kas_price = get_kls_price
get_kas_market_data = get_kls_market_data
