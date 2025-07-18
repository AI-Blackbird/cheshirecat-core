from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel
from typing import Dict, Any
from datetime import datetime

from cat.discovery.model.update_message import UpdateMessage
from cat.log import log

router = APIRouter()


class UpdateRequest(BaseModel):
    update_id: str
    update_type: str
    payload: Dict[str, Any]
    timestamp: str
    source_node: str


@router.post("/api/updates")
async def receive_network_update(request: Request, update_request: UpdateRequest):
    """
    Receive network updates from other CheshireCat nodes.
    This endpoint is used by the NetworkDiscovery system to propagate updates.
    """
    try:
        # Convert request to UpdateMessage
        update_message = UpdateMessage(
            update_id=update_request.update_id,
            update_type=update_request.update_type,
            payload=update_request.payload,
            timestamp=datetime.fromisoformat(update_request.timestamp),
            source_node=update_request.source_node
        )
        
        # Get the network discovery instance from Bill the Lizard
        lizard = request.app.state.lizard
        if not lizard.network_discovery:
            raise HTTPException(status_code=503, detail="Network discovery not available")
        
        # Handle the update
        processed = await lizard.network_discovery.handle_received_update(update_message)
        
        log.info(f"Processed network update {update_message.update_id} of type {update_message.update_type}")
        
        return {"status": "success", "processed": processed}
        
    except Exception as e:
        log.error(f"Error processing network update: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/network/nodes")
async def get_network_nodes(request: Request):
    """
    Get the list of currently active nodes in the network.
    """
    try:
        lizard = request.app.state.lizard
        if not lizard.network_discovery:
            raise HTTPException(status_code=503, detail="Network discovery not available")
        
        nodes = lizard.network_discovery.get_active_nodes()
        
        return {
            "nodes": [node.to_dict() for node in nodes],
            "total": len(nodes)
        }
        
    except Exception as e:
        log.error(f"Error getting network nodes: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/network/status")
async def get_network_status(request: Request):
    """
    Get the current network discovery status.
    """
    try:
        lizard = request.app.state.lizard
        if not lizard.network_discovery:
            return {"status": "disabled", "running": False}
        
        return {
            "status": "enabled",
            "running": lizard.network_discovery.running,
            "node_id": lizard.network_discovery.node_id,
            "host": lizard.network_discovery.host,
            "port": lizard.network_discovery.port,
            "active_nodes": len(lizard.network_discovery.nodes)
        }
        
    except Exception as e:
        log.error(f"Error getting network status: {e}")
        raise HTTPException(status_code=500, detail=str(e))