# encoding: utf-8
"""
GET /analytics/addresses/distribution-summary

Returns address counts bucketed into KLS tiers, plus a total address count.
Delta values (delta_1d, delta_7d) require a snapshot cronjob; returned as
null until that infrastructure exists — the frontend DeltaBadge renders "—"
gracefully.

Queries the `utxos` table (v20 schema). One sompi = 1e-8 KLS.
"""
from typing import List, Optional

from fastapi import HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from starlette.responses import Response

from dbsession import async_session
from server import app

# ---------------------------------------------------------------------------
# Tier definitions — (tier_id, min_sompi_inclusive, max_sompi_exclusive)
# None means no upper bound.
# ---------------------------------------------------------------------------
_SOMPI_PER_KLS = 100_000_000

_TIERS = [
    ("10M+",      10_000_000 * _SOMPI_PER_KLS, None),
    ("1M-10M",     1_000_000 * _SOMPI_PER_KLS, 10_000_000 * _SOMPI_PER_KLS),
    ("500K-1M",      500_000 * _SOMPI_PER_KLS,  1_000_000 * _SOMPI_PER_KLS),
    ("100K-500K",    100_000 * _SOMPI_PER_KLS,    500_000 * _SOMPI_PER_KLS),
    ("10K-100K",      10_000 * _SOMPI_PER_KLS,    100_000 * _SOMPI_PER_KLS),
    ("1K-10K",         1_000 * _SOMPI_PER_KLS,     10_000 * _SOMPI_PER_KLS),
    ("100-1K",           100 * _SOMPI_PER_KLS,      1_000 * _SOMPI_PER_KLS),
    ("1-100",              1 * _SOMPI_PER_KLS,        100 * _SOMPI_PER_KLS),
]


class TierEntry(BaseModel):
    tier: str
    addresses: int
    delta_1d: Optional[int] = None   # null until snapshot cronjob exists
    delta_7d: Optional[int] = None


class DistributionSummaryResponse(BaseModel):
    total_addresses: int
    total_delta_1d: Optional[int] = None
    total_delta_7d: Optional[int] = None
    tiers: List[TierEntry]


@app.get(
    "/analytics/addresses/distribution-summary",
    response_model=DistributionSummaryResponse,
    tags=["Karlsen addresses"],
    summary="Get address distribution summary by KLS balance tier",
    description=(
        "Returns the number of addresses in each KLS balance tier, computed "
        "live from the utxos table. Delta fields are null until a snapshot "
        "cronjob is configured."
    ),
)
async def get_analytics_distribution_summary(response: Response):
    response.headers["Cache-Control"] = "public, max-age=300"

    # Build a single CASE expression so we scan utxos only once.
    case_clauses = []
    for tier_id, lo, hi in _TIERS:
        if hi is None:
            case_clauses.append(
                f"WHEN addr_balance >= {lo} THEN '{tier_id}'"
            )
        else:
            case_clauses.append(
                f"WHEN addr_balance >= {lo} AND addr_balance < {hi} THEN '{tier_id}'"
            )

    case_expr = "CASE\n            " + "\n            ".join(case_clauses) + "\n        END"

    sql = text(f"""
        WITH address_totals AS (
            SELECT script_public_key_address,
                   SUM(amount) AS addr_balance
            FROM   utxos
            GROUP  BY script_public_key_address
        ),
        bucketed AS (
            SELECT {case_expr} AS tier
            FROM   address_totals
            WHERE  addr_balance >= :min_sompi
        )
        SELECT tier, COUNT(*) AS addresses
        FROM   bucketed
        WHERE  tier IS NOT NULL
        GROUP  BY tier
    """)

    async with async_session() as s:
        result = await s.execute(
            sql,
            {"min_sompi": 1 * _SOMPI_PER_KLS},  # only addresses with >= 1 KLS
        )
        rows = {row.tier: row.addresses for row in result}

    tiers = [
        TierEntry(tier=tier_id, addresses=rows.get(tier_id, 0))
        for tier_id, _, _ in _TIERS
    ]
    total = sum(t.addresses for t in tiers)

    return DistributionSummaryResponse(
        total_addresses=total,
        tiers=tiers,
    )
