"""
WhatsApp session management router.
Handles instance creation, QR code retrieval, and connection status polling.
"""

import logging
from fastapi import APIRouter, HTTPException, Request
from models.schemas import SessionResponse, ConnectionStatus

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/whatsapp", tags=["WhatsApp Session"])

# Default instance name (single-tenant app)
DEFAULT_INSTANCE = "bulk-sender-main"


@router.post("/session/create", response_model=SessionResponse)
async def create_session(request: Request):
    """
    Initialize a new WhatsApp session.
    Creates an Evolution API instance and returns the QR code.
    """
    evo = request.app.state.evolution_api

    try:
        # Attempt to create a new instance
        result = await evo.create_instance(DEFAULT_INSTANCE)
        logger.info(f"Instance creation result: {result}")

        # Extract QR code from response
        # Evolution API response structure varies by version
        qr_code = None
        if "qrcode" in result:
            qr_data = result["qrcode"]
            if isinstance(qr_data, dict):
                qr_code = qr_data.get("base64") or qr_data.get("qrcode")
            elif isinstance(qr_data, str):
                qr_code = qr_data

        return SessionResponse(
            instance_name=DEFAULT_INSTANCE,
            status=ConnectionStatus.QR_CODE if qr_code else ConnectionStatus.CONNECTING,
            qr_code=qr_code,
            message="QR Code ready. Scan with WhatsApp to connect.",
        )

    except Exception as e:
        error_msg = str(e)

        # Instance might already exist - try to get QR code directly
        if "already" in error_msg.lower() or "409" in error_msg or "403" in error_msg:
            logger.info("Instance exists, fetching QR code...")
            return await get_qr_code(request)

        logger.error(f"Failed to create session: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to initialize WhatsApp session: {error_msg}"
        )


@router.get("/session/qr", response_model=SessionResponse)
async def get_qr_code(request: Request):
    """
    Retrieve the current QR code for the WhatsApp session.
    Called by the frontend for QR refresh.
    """
    evo = request.app.state.evolution_api

    try:
        result = await evo.get_qr_code(DEFAULT_INSTANCE)
        logger.debug(f"QR response: {result}")

        qr_code = None
        if "base64" in result:
            qr_code = result["base64"]
        elif "qrcode" in result:
            qr_code = result["qrcode"]

        if not qr_code:
            # Check if already connected
            state = await evo.get_connection_state(DEFAULT_INSTANCE)
            state_data = state.get("instance", state) if isinstance(state, dict) else state
            if isinstance(state_data, dict) and state_data.get("state") == "open":
                return await get_status(request)

        return SessionResponse(
            instance_name=DEFAULT_INSTANCE,
            status=ConnectionStatus.QR_CODE if qr_code else ConnectionStatus.CONNECTING,
            qr_code=qr_code,
            message="Scan the QR code with WhatsApp",
        )

    except Exception as e:
        logger.error(f"Failed to get QR code: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to retrieve QR code: {str(e)}"
        )


@router.get("/session/status", response_model=SessionResponse)
async def get_status(request: Request):
    """
    Poll the current connection status of the WhatsApp session.
    Frontend polls this every 3 seconds to detect successful QR scan.
    """
    evo = request.app.state.evolution_api

    try:
        state_response = await evo.get_connection_state(DEFAULT_INSTANCE)
        instance_data = state_response.get("instance", state_response) if isinstance(state_response, dict) else state_response
        connection_state = instance_data.get("state", "close") if isinstance(instance_data, dict) else "close"

        if connection_state == "open":
            # Fetch full instance info to get phone number
            info = await evo.get_instance_info(DEFAULT_INSTANCE)
            instance_info = info.get("instance", info) if isinstance(info, dict) else info

            phone = instance_info.get("ownerJid", "").replace("@s.whatsapp.net", "") if isinstance(instance_info, dict) else ""
            profile_name = instance_info.get("profileName", "") if isinstance(instance_info, dict) else ""

            return SessionResponse(
                instance_name=DEFAULT_INSTANCE,
                status=ConnectionStatus.CONNECTED,
                phone_number=phone,
                profile_name=profile_name,
                message=f"Connected as {profile_name or phone}",
            )

        elif connection_state == "connecting":
            return SessionResponse(
                instance_name=DEFAULT_INSTANCE,
                status=ConnectionStatus.CONNECTING,
                message="Connecting to WhatsApp...",
            )

        else:
            return SessionResponse(
                instance_name=DEFAULT_INSTANCE,
                status=ConnectionStatus.DISCONNECTED,
                message="Not connected. Please scan QR code.",
            )

    except Exception as e:
        logger.warning(f"Status check failed (instance may not exist): {e}")
        return SessionResponse(
            instance_name=DEFAULT_INSTANCE,
            status=ConnectionStatus.DISCONNECTED,
            message="Session not initialized.",
        )


@router.delete("/session/logout")
async def logout_session(request: Request):
    """Disconnect the current WhatsApp session."""
    evo = request.app.state.evolution_api
    try:
        await evo.logout_instance(DEFAULT_INSTANCE)
        return {"message": "Successfully logged out"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
