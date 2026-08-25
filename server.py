# encoding: utf-8
import asyncio
import logging
import os
from asyncio import wait_for
from typing import Optional

import fastapi.logger
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from pydantic import BaseModel
from sqlalchemy import text
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from constants import KARLSEND_WRPC_URL
from dbsession import async_session
from helper.StrictRoute import StrictRoute
from helper.LimitUploadSize import LimitUploadSize
from karlsend.KarlsendMultiClient import KarlsendMultiClient
from karlsend.KarlsendRpcClient import karlsend_rpc_client

fastapi.logger.logger.setLevel(logging.WARNING)

_logger = logging.getLogger(__name__)

app = FastAPI(
    title="Karlsen REST-API server",
    description="REST-API server supporting block, tx and address search, using Karlsend and the indexer db.\n\n"
    "[https://github.com/karlsencoin/karlsen-rest-server](https://github.com/karlsencoin/karlsen-rest-server) "
    "(fork of [karlsencoin/karlsen-rest-server](https://github.com/karlsencoin/karlsen-rest-server))",
    version=os.getenv("VERSION") or "dev",
    contact={"name": "lAmeR1 / supertypo"},
    license_info={"name": "MIT LICENSE"},
    swagger_ui_parameters={"tryItOutEnabled": True},
)
app.router.route_class = StrictRoute


class CacheControlMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        if request.method in ("GET", "HEAD") and "cache-control" not in response.headers:
            response.headers["Cache-Control"] = "public, max-age=8"
        return response


app.add_middleware(GZipMiddleware, minimum_size=500)
app.add_middleware(LimitUploadSize, max_upload_size=200_000)  # ~1MB

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Data-Source", "X-Page-Count", "X-Next-Page-After", "X-Next-Page-Before"],
)

app.add_middleware(CacheControlMiddleware)


class KarlsendStatus(BaseModel):
    is_online: bool = False
    is_wrpc: bool = False
    server_version: Optional[str] = None
    is_utxo_indexed: Optional[bool] = None
    is_synced: Optional[bool] = None


class DatabaseStatus(BaseModel):
    is_online: bool = False


class PingResponse(BaseModel):
    karlsend: KarlsendStatus = KarlsendStatus()
    database: DatabaseStatus = DatabaseStatus()


@app.get("/ping", include_in_schema=False, response_model=PingResponse)
async def ping_server():
    """
    Ping Pong
    """
    result = PingResponse()

    rpc_client = await karlsend_rpc_client()
    if rpc_client:
        result.karlsend.is_wrpc = True
        try:
            info = await wait_for(rpc_client.get_info(), 10)
            result.karlsend.is_online = True
            result.karlsend.server_version = info["serverVersion"]
            result.karlsend.is_utxo_indexed = info["isUtxoIndexed"]
            result.karlsend.is_synced = info["isSynced"]
        except Exception as err:
            _logger.error(f"Kaspad health check failed {str(err)}")

    elif karlsend_client.karlsends:
        try:
            info = await karlsend_client.karlsends[0].request("getInfoRequest")
            result.karlsend.is_online = True
            result.karlsend.server_version = info["getInfoResponse"]["serverVersion"]
            result.karlsend.is_utxo_indexed = info["getInfoResponse"]["isUtxoIndexed"]
            result.karlsend.is_synced = info["getInfoResponse"]["isSynced"]
        except Exception as err:
            _logger.error("Kaspad health check failed %s", err)

    if os.getenv("SQL_URI") is not None:
        async with async_session() as session:
            try:
                await session.execute(text("SELECT 1"))
                result.database.is_online = True
            except Exception as err:
                _logger.error("Database health check failed %s", err)

    if not result.database.is_online or not result.karlsend.is_synced:
        return JSONResponse(status_code=503, content=result.dict())

    return result


karlsend_hosts = []

for i in range(100):
    try:
        karlsend_hosts.append(os.environ[f"KARLSEND_HOST_{i + 1}"].strip())
    except KeyError:
        break

if not karlsend_hosts and not KARLSEND_WRPC_URL:
    raise Exception("Please set KARLSEND_WRPC_URL or KARLSEND_HOST_1 environment variable.")

karlsend_client = KarlsendMultiClient(karlsend_hosts)


@app.exception_handler(Exception)
async def unicorn_exception_handler(request: Request, exc: Exception):
    await karlsend_client.initialize_all()
    return JSONResponse(
        status_code=500,
        content={
            "message": "Internal server error"
            # "traceback": f"{traceback.format_exception(exc)}"
        },
    )


@app.on_event("startup")
async def periodical_blockdag():
    async def loop():
        while True:
            try:
                await karlsend_client.initialize_all()
            except Exception as e:
                logging.exception(f"Error initializing karlsend_client: {e}")
            await asyncio.sleep(60)

    asyncio.create_task(loop())
