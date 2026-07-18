from fastapi import APIRouter, Request, HTTPException
from typing import Dict, Any
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/instances", tags=["instances"])

@router.get("/")
async def get_instances(request: Request) -> Dict[str, Any]:
    """Fetch all connected WhatsApp instances."""
    try:
        evo = request.app.state.evolution_api
        instances = await evo.get_instances()
        return {"instances": instances}
    except Exception as e:
        logger.error(f"Failed to fetch instances: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/")
async def create_instance(request: Request, payload: Dict[str, str]) -> Dict[str, Any]:
    """Create a new WhatsApp instance and return the QR code."""
    instance_name = payload.get("instanceName")
    if not instance_name:
        raise HTTPException(status_code=400, detail="instanceName is required")
        
    try:
        evo = request.app.state.evolution_api
        result = await evo.create_instance(instance_name)
        return {"success": True, "result": result}
    except Exception as e:
        logger.error(f"Failed to create instance {instance_name}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/{instance_name}")
async def delete_instance(instance_name: str, request: Request) -> Dict[str, Any]:
    """Delete a WhatsApp instance."""
    try:
        evo = request.app.state.evolution_api
        result = await evo.delete_instance(instance_name)
        return {"success": True, "result": result}
    except Exception as e:
        logger.error(f"Failed to delete instance {instance_name}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/{instance_name}/connection")
async def get_connection_state(instance_name: str, request: Request) -> Dict[str, Any]:
    """Get the connection state of an instance."""
    try:
        evo = request.app.state.evolution_api
        result = await evo.get_connection_state(instance_name)
        return result
    except Exception as e:
        logger.error(f"Failed to get connection state for {instance_name}: {e}")
        raise HTTPException(status_code=500, detail=str(e))
