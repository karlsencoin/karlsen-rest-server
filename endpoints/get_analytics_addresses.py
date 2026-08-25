# encoding: utf-8
"""
Analytics endpoints consumed by explorer.karlsencoin.org.

All four endpoints query the `utxos` table live.
- min_amount / max_amount query params are in KLS (not sompi).
- amount fields in responses are in KLS (float, 8 decimal places).
- percent fields are share of total circulating supply (%).
"""
from typing import List, Optional

from fastapi import Query
from pydantic import BaseModel
from sqlalchemy import text
from starlette.responses import Response

from dbsession import async_session
from server import app

_SOMPI_PER_KLS = 100_000_000


# ---------------------------------------------------------------------------
# Shared models
# ---------------------------------------------------------------------------

class AddressEntry(BaseModel):
    address: str
    amount: float   # KLS
    percent: float  # % of circulating supply


# ---------------------------------------------------------------------------
# /analytics/addresses/top
# ---------------------------------------------------------------------------

class TopAddressesResponse(BaseModel):
    top_addresses: List[AddressEntry]


@app.get(
    "/analytics/addresses/top",
    response_model=TopAddressesResponse,
    tags=["Karlsen analytics"],
    summary="Get top Karlsen addresses by balance (rich list)",
)
async def get_analytics_top_addresses(
    response: Response,
    limit: int = Query(default=100, ge=1, le=100_000),
    offset: int = Query(default=0, ge=0),
):
    response.headers["Cache-Control"] = "public, max-age=300"

    sql = text("""
        WITH address_totals AS (
            SELECT script_public_key_address,
                   SUM(amount) AS balance_sompi
            FROM   utxos
            GROUP  BY script_public_key_address
            ORDER  BY balance_sompi DESC
            LIMIT  :limit OFFSET :offset
        ),
        total_supply AS (
            SELECT COALESCE(SUM(amount), 1) AS total_sompi FROM utxos
        )
        SELECT  at.script_public_key_address AS address,
                at.balance_sompi,
                ts.total_sompi
        FROM    address_totals at, total_supply ts
        ORDER   BY at.balance_sompi DESC
    """)

    async with async_session() as s:
        rows = (await s.execute(sql, {"limit": limit, "offset": offset})).all()

    return TopAddressesResponse(
        top_addresses=[
            AddressEntry(
                address=row.address,
                amount=round(row.balance_sompi / _SOMPI_PER_KLS, 8),
                percent=round(row.balance_sompi / row.total_sompi * 100, 6),
            )
            for row in rows
        ]
    )


# ---------------------------------------------------------------------------
# /analytics/addresses/total
# ---------------------------------------------------------------------------

class TotalAddressesResponse(BaseModel):
    total_addresses: int


@app.get(
    "/analytics/addresses/total",
    response_model=TotalAddressesResponse,
    tags=["Karlsen analytics"],
    summary="Get total number of addresses with a non-zero balance",
)
async def get_analytics_total_addresses(response: Response):
    response.headers["Cache-Control"] = "public, max-age=120"

    sql = text("""
        SELECT COUNT(DISTINCT script_public_key_address) AS total
        FROM   utxos
    """)

    async with async_session() as s:
        result = await s.execute(sql)
        total = result.scalar_one()

    return TotalAddressesResponse(total_addresses=total)


# ---------------------------------------------------------------------------
# /analytics/addresses/distribution
# ---------------------------------------------------------------------------

class DistributionResponse(BaseModel):
    from_addresses_total: int


@app.get(
    "/analytics/addresses/distribution",
    response_model=DistributionResponse,
    tags=["Karlsen analytics"],
    summary="Count addresses whose total balance falls within [min_amount, max_amount) KLS",
)
async def get_analytics_address_distribution(
    response: Response,
    min_amount: float = Query(..., ge=0),
    max_amount: float = Query(default=-1),
):
    response.headers["Cache-Control"] = "public, max-age=120"

    min_sompi = int(min_amount * _SOMPI_PER_KLS)
    # max_amount == -1 means no upper bound (matches explorer convention)
    if max_amount < 0:
        sql = text("""
            SELECT COUNT(*) AS total
            FROM (
                SELECT script_public_key_address
                FROM   utxos
                GROUP  BY script_public_key_address
                HAVING SUM(amount) >= :min_sompi
            ) sub
        """)
        params: dict = {"min_sompi": min_sompi}
    else:
        max_sompi = int(max_amount * _SOMPI_PER_KLS)
        sql = text("""
            SELECT COUNT(*) AS total
            FROM (
                SELECT script_public_key_address
                FROM   utxos
                GROUP  BY script_public_key_address
                HAVING SUM(amount) >= :min_sompi
                   AND SUM(amount) <  :max_sompi
            ) sub
        """)
        params = {"min_sompi": min_sompi, "max_sompi": max_sompi}

    async with async_session() as s:
        result = await s.execute(sql, params)
        total = result.scalar_one()

    return DistributionResponse(from_addresses_total=total)


# ---------------------------------------------------------------------------
# /analytics/addresses/range
# ---------------------------------------------------------------------------

@app.get(
    "/analytics/addresses/range",
    response_model=List[AddressEntry],
    tags=["Karlsen analytics"],
    summary="List addresses whose total balance falls within [min_amount, max_amount) KLS",
)
async def get_analytics_address_range(
    response: Response,
    min_amount: float = Query(..., ge=0),
    max_amount: float = Query(default=-1),
):
    response.headers["Cache-Control"] = "public, max-age=120"

    min_sompi = int(min_amount * _SOMPI_PER_KLS)

    if max_amount < 0:
        having_clause = "HAVING SUM(amount) >= :min_sompi"
        params: dict = {"min_sompi": min_sompi}
    else:
        max_sompi = int(max_amount * _SOMPI_PER_KLS)
        having_clause = "HAVING SUM(amount) >= :min_sompi AND SUM(amount) < :max_sompi"
        params = {"min_sompi": min_sompi, "max_sompi": max_sompi}

    sql = text(f"""
        WITH address_totals AS (
            SELECT script_public_key_address,
                   SUM(amount) AS balance_sompi
            FROM   utxos
            GROUP  BY script_public_key_address
            {having_clause}
        ),
        total_supply AS (
            SELECT COALESCE(SUM(amount), 1) AS total_sompi FROM utxos
        )
        SELECT  at.script_public_key_address AS address,
                at.balance_sompi,
                ts.total_sompi
        FROM    address_totals at, total_supply ts
        ORDER   BY at.balance_sompi DESC
    """)

    async with async_session() as s:
        rows = (await s.execute(sql, params)).all()

    return [
        AddressEntry(
            address=row.address,
            amount=round(row.balance_sompi / _SOMPI_PER_KLS, 8),
            percent=round(row.balance_sompi / row.total_sompi * 100, 6),
        )
        for row in rows
    ]
