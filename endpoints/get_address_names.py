# encoding: utf-8
from typing import List

from fastapi import Path, HTTPException
from kaspa_script_address import to_script
from pydantic import BaseModel
from sqlalchemy.future import select
from starlette.responses import Response

from constants import REGEX_KARLSEN_ADDRESS
from dbsession import async_session
from endpoints import sql_db_only
from models.AddressKnown import AddressKnown
from server import app


class AddressName(BaseModel):
    address: str
    name: str


@app.get(
    "/addresses/names",
    response_model=List[AddressName],
    tags=["Karlsen addresses"],
    openapi_extra={"strict_query_params": True},
)
@sql_db_only
async def get_addresses_names(response: Response):
    """
    Get the name for an address
    """
    response.headers["Cache-Control"] = "public, max-age=60"
    async with async_session() as s:
        rows = (await s.execute(select(AddressKnown))).scalars().all()
        return [{"name": r.name, "address": r.address} for r in rows]


@app.get(
    "/addresses/{karlsenAddress}/name",
    response_model=AddressName | None,
    tags=["Karlsen addresses"],
    openapi_extra={"strict_query_params": True},
)
@sql_db_only
async def get_name_for_address(
    response: Response,
    karlsen_address: str = Path(
        alias="karlsenAddress",
        description="Karlsen address as string e.g. karlsen:qqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqkx9awp4e",
        regex=REGEX_KARLSEN_ADDRESS,
    ),
):
    """
    Get the name for an address
    """
    # Address validated by FastAPI Path regex; karlsend RPC checks checksum canonically.
    async with async_session() as s:
        r = (await s.execute(select(AddressKnown).filter(AddressKnown.address == karlsen_address))).first()

    response.headers["Cache-Control"] = "public, max-age=600"
    if r:
        return AddressName(address=r.AddressKnown.address, name=r.AddressKnown.name)
    else:
        raise HTTPException(
            status_code=404, detail="Address name not found", headers={"Cache-Control": "public, max-age=600"}
        )
