# encoding: utf-8
import logging
from asyncio import wait_for

from karlsend.karlsen_sdk import RpcClient, Resolver

from constants import KARLSEND_WRPC_URL, NETWORK_TYPE

_logger = logging.getLogger(__name__)


async def karlsend_rpc_client() -> RpcClient:
    if KARLSEND_WRPC_URL:
        use_resolver = KARLSEND_WRPC_URL == "resolver"
        if not hasattr(karlsend_rpc_client, "client"):
            network_id = "testnet-10" if NETWORK_TYPE == "testnet" else "mainnet"
            if use_resolver:
                karlsend_rpc_client.client = RpcClient(resolver=Resolver(), network_id=network_id)
            else:
                karlsend_rpc_client.client = RpcClient(url=KARLSEND_WRPC_URL)

        if not karlsend_rpc_client.client.is_connected:
            try:
                await wait_for(karlsend_rpc_client.client.connect(), 10 if use_resolver else 5)
                if karlsend_rpc_client.client.is_connected:
                    info = await wait_for(karlsend_rpc_client.client.get_block_dag_info(), 10)
                    logging.info(f"Successfully connected to Kaspad {info['network']} ({KARLSEND_WRPC_URL})")
            except Exception:
                pass
            if not karlsend_rpc_client.client.is_connected:
                logging.warning(f"Connection to Kaspad ({KARLSEND_WRPC_URL}) failed.")

        return karlsend_rpc_client.client
