"""
Evolution API service layer.
All HTTP communication with the Evolution API is encapsulated here.
This keeps the router code clean and makes testing easier.
"""

import httpx
import logging
from typing import Optional

logger = logging.getLogger(__name__)


class EvolutionAPIService:
    """
    Client wrapper for the Evolution API.
    Handles instance management, QR code retrieval, and message sending.
    """

    def __init__(self, base_url: str, api_key: str):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        # Shared async HTTP client with timeout configuration
        self._client = httpx.AsyncClient(
            headers={
                "apikey": self.api_key,
                "Content-Type": "application/json",
            },
            timeout=httpx.Timeout(30.0, connect=10.0),
        )

    async def close(self):
        """Close the HTTP client. Call on app shutdown."""
        await self._client.aclose()

    async def create_instance(self, instance_name: str) -> dict:
        """
        Create a new WhatsApp instance in Evolution API.
        This triggers QR code generation for the user to scan.
        """
        payload = {
            "instanceName": instance_name,
            "qrcode": True,
            "integration": "WHATSAPP-BAILEYS",
        }
        response = await self._client.post(
            f"{self.base_url}/instance/create",
            json=payload,
        )
        response.raise_for_status()
        return response.json()

    async def get_instance_info(self, instance_name: str) -> dict:
        """
        Fetch current state of an instance.
        Returns connection status and phone info if connected.
        """
        response = await self._client.get(
            f"{self.base_url}/instance/fetchInstances",
            params={"instanceName": instance_name},
        )
        response.raise_for_status()
        data = response.json()
        # fetchInstances returns a list; find our instance
        if isinstance(data, list):
            for inst in data:
                # Handle v1 and v2 API differences
                name = inst.get("instance", {}).get("instanceName") or inst.get("name") or inst.get("instanceName")
                if name == instance_name:
                    return inst
        return data

    async def get_instances(self) -> list[dict]:
        """Fetch all WhatsApp instances in Evolution API."""
        response = await self._client.get(
            f"{self.base_url}/instance/fetchInstances",
        )
        response.raise_for_status()
        data = response.json()
        return data if isinstance(data, list) else []

    async def get_qr_code(self, instance_name: str) -> dict:
        """
        Retrieve the current QR code for an instance.
        Returns base64 encoded QR code image.
        """
        response = await self._client.get(
            f"{self.base_url}/instance/connect/{instance_name}",
        )
        response.raise_for_status()
        return response.json()

    async def get_connection_state(self, instance_name: str) -> dict:
        """
        Poll the connection state of an instance.
        States: open (connected), close (disconnected), connecting
        """
        response = await self._client.get(
            f"{self.base_url}/instance/connectionState/{instance_name}",
        )
        response.raise_for_status()
        return response.json()

    async def logout_instance(self, instance_name: str) -> dict:
        """Disconnect and logout a WhatsApp instance."""
        response = await self._client.delete(
            f"{self.base_url}/instance/logout/{instance_name}",
        )
        response.raise_for_status()
        return response.json()

    async def delete_instance(self, instance_name: str) -> dict:
        """Completely delete a WhatsApp instance."""
        response = await self._client.delete(
            f"{self.base_url}/instance/delete/{instance_name}",
        )
        response.raise_for_status()
        return response.json()

    async def send_text_message(
        self,
        instance_name: str,
        phone: str,
        message: str,
    ) -> dict:
        """
        Send a text message via WhatsApp.

        Args:
            instance_name: The Evolution API instance to use
            phone: Phone number in international format (e.g., "15551234567")
            message: The text message content

        Returns:
            Evolution API response with message ID
        """
        # Evolution API expects number without + prefix
        clean_phone = phone.lstrip("+").strip()

        payload = {
            "number": clean_phone,
            "text": message,
            "delay": 1000,  # 1 second delay before sending (anti-spam)
        }

        response = await self._client.post(
            f"{self.base_url}/message/sendText/{instance_name}",
            json=payload,
        )
        response.raise_for_status()
        return response.json()

    async def send_media_message(
        self,
        instance_name: str,
        phone: str,
        caption: str,
        base64_data: str,
        media_type: str,
        mime_type: str
    ) -> dict:
        """
        Send a media message (image/video) via WhatsApp.

        Args:
            instance_name: The Evolution API instance to use
            phone: Phone number in international format
            caption: The text message content (caption)
            base64_data: The file content as a base64 string
            media_type: "image", "video", "document", etc.
            mime_type: "image/jpeg", "video/mp4", etc.

        Returns:
            Evolution API response with message ID
        """
        clean_phone = phone.lstrip("+").strip()

        payload = {
            "number": clean_phone,
            "options": {
                "delay": 1200,
                "presence": "composing"
            },
            "mediatype": media_type,
            "caption": caption,
            "media": base64_data,
            "fileName": f"media.{mime_type.split('/')[-1] if '/' in mime_type else 'bin'}"
        }

        response = await self._client.post(
            f"{self.base_url}/message/sendMedia/{instance_name}",
            json=payload,
        )
        response.raise_for_status()
        return response.json()

    async def check_number_exists(
        self, instance_name: str, phone: str
    ) -> bool:
        """
        Check if a WhatsApp number exists before sending.
        Helps avoid failed sends to invalid numbers.
        """
        try:
            response = await self._client.get(
                f"{self.base_url}/chat/whatsappNumbers/{instance_name}",
                params={"numbers": phone},
            )
            data = response.json()
            if isinstance(data, list) and data:
                return data[0].get("exists", False)
            return False
        except Exception:
            # If check fails, proceed with send anyway
            return True

    async def get_groups(self, instance_name: str) -> list[dict]:
        """
        Fetch all WhatsApp groups the instance account belongs to.
        Uses a long timeout because Evolution API's fetchAllGroups can be slow.
        """
        import time
        url = f"{self.base_url}/group/fetchAllGroups/{instance_name}"
        # Use a dedicated client with a much longer timeout for this slow endpoint
        long_timeout = httpx.Timeout(120.0, connect=10.0)

        async with httpx.AsyncClient(
            headers={"apikey": self.api_key, "Content-Type": "application/json"},
            timeout=long_timeout,
        ) as client:
            try:
                t0 = time.time()
                logger.info(f"[get_groups] Fetching groups from {url} ...")
                # NOTE: getParticipants=false hangs in Evolution API v2.x — use true instead
                response = await client.get(url, params={"getParticipants": "true"})
                elapsed = round(time.time() - t0, 2)
                logger.info(f"[get_groups] HTTP {response.status_code} in {elapsed}s from {url}")
                raw_text = response.text
                logger.info(f"[get_groups] Raw response (first 1000 chars): {raw_text[:1000]}")
                response.raise_for_status()
                data = response.json()

                return self._parse_groups_response(data)

            except httpx.ReadTimeout:
                logger.warning("[get_groups] ReadTimeout – retrying without getParticipants param...")
                # Some Evolution API versions hang on getParticipants=false, retry plain
                try:
                    response = await client.get(url)
                    response.raise_for_status()
                    data = response.json()
                    return self._parse_groups_response(data)
                except Exception as e2:
                    logger.error(f"[get_groups] Retry also failed: {type(e2).__name__}: {e2}")
                    raise
            except Exception as e:
                logger.error(f"[get_groups] Failed: {type(e).__name__}: {e}")
                raise

    def _parse_groups_response(self, data) -> list[dict]:
        """Parse all known Evolution API group response shapes."""
        if isinstance(data, list):
            logger.info(f"[get_groups] Got list with {len(data)} items")
            return data
        if isinstance(data, dict):
            if "groups" in data and isinstance(data["groups"], list):
                return data["groups"]
            if "data" in data and isinstance(data["data"], list):
                return data["data"]
            for key, val in data.items():
                if isinstance(val, list) and len(val) > 0:
                    logger.info(f"[get_groups] Found list under key '{key}' with {len(val)} items")
                    return val
            logger.warning(f"[get_groups] Unexpected dict shape: {list(data.keys())}")
        return []

    async def get_groups_raw(self, instance_name: str) -> dict:
        """Return the raw JSON from the groups endpoint for debugging."""
        url = f"{self.base_url}/group/fetchAllGroups/{instance_name}"
        try:
            async with httpx.AsyncClient(
                headers={"apikey": self.api_key, "Content-Type": "application/json"},
                timeout=httpx.Timeout(120.0, connect=10.0),
            ) as client:
                response = await client.get(url, params={"getParticipants": "true"})
                return {
                    "status_code": response.status_code,
                    "url": url,
                    "body": response.json() if response.text else None,
                }
        except Exception as e:
            return {"error": str(e), "url": url}

    async def get_group_members(self, instance_name: str, group_id: str) -> list[dict]:
        """
        Fetch all participants of a specific WhatsApp group.
        Returns list of participant dicts with phone/admin info.
        """
        url = f"{self.base_url}/group/participants/{instance_name}"
        try:
            response = await self._client.get(url, params={"groupJid": group_id})
            logger.info(f"[get_group_members] HTTP {response.status_code} for group {group_id}")
            raw_text = response.text
            logger.info(f"[get_group_members] Raw (first 500): {raw_text[:500]}")

            response.raise_for_status()
            data = response.json()

            # Handle multiple possible response shapes
            if isinstance(data, list):
                return data
            if isinstance(data, dict):
                if "participants" in data:
                    return data["participants"]
                if "data" in data and isinstance(data["data"], list):
                    return data["data"]
                for key, val in data.items():
                    if isinstance(val, list):
                        return val

            return []
        except Exception as e:
            logger.error(f"[get_group_members] Failed for {group_id}: {type(e).__name__}: {e}")
            return []

    async def set_webhook(
        self,
        instance_name: str,
        webhook_url: str,
        events: list[str] | None = None,
    ) -> dict:
        """
        Register a webhook on the Evolution API instance.
        Evolution API will POST to webhook_url for each matching event.
        """
        if events is None:
            events = ["MESSAGES_UPSERT"]

        payload = {
            "url": webhook_url,
            "webhook_by_events": False,
            "webhook_base64": False,
            "events": events,
        }
        response = await self._client.post(
            f"{self.base_url}/webhook/set/{instance_name}",
            json=payload,
        )
        response.raise_for_status()
        return response.json()
