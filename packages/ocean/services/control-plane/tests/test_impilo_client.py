"""Unit tests for Impilo API client (RMA creation)."""
from __future__ import annotations

import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest


class TestCreateRmaValidation:
    """create_rma validates required fields before calling API."""

    @pytest.mark.asyncio
    async def test_raises_on_empty_patient_id(self):
        from src.impilo_client import create_rma

        with pytest.raises(ValueError, match="patient_id"):
            await create_rma(
                api_url="http://impilo.test",
                api_key="key-123",
                patient_id="",
                device_id="dev-1",
                order_id="ord-1",
                reason="defective",
            )

    @pytest.mark.asyncio
    async def test_raises_on_empty_device_id(self):
        from src.impilo_client import create_rma

        with pytest.raises(ValueError, match="device_id"):
            await create_rma(
                api_url="http://impilo.test",
                api_key="key-123",
                patient_id="pat-1",
                device_id="",
                order_id="ord-1",
                reason="defective",
            )

    @pytest.mark.asyncio
    async def test_raises_on_empty_order_id(self):
        from src.impilo_client import create_rma

        with pytest.raises(ValueError, match="order_id"):
            await create_rma(
                api_url="http://impilo.test",
                api_key="key-123",
                patient_id="pat-1",
                device_id="dev-1",
                order_id="",
                reason="defective",
            )


class TestCreateRmaHappyPath:
    """create_rma makes POST to Impilo and returns response."""

    @pytest.mark.asyncio
    async def test_posts_correct_payload(self):
        import httpx
        from src.impilo_client import create_rma

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"id": "ret-001", "status": "initiated"}
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("src.impilo_client.httpx.AsyncClient", return_value=mock_client):
            result = await create_rma(
                api_url="http://impilo.test",
                api_key="key-123",
                patient_id="pat-1",
                device_id="dev-1",
                order_id="ord-1",
                reason="defective",
            )

        assert result == {"id": "ret-001", "status": "initiated"}
        mock_client.post.assert_called_once()
        call_kwargs = mock_client.post.call_args
        assert call_kwargs[0][0] == "http://impilo.test/api/v3/return"
        assert call_kwargs[1]["headers"]["Authorization"] == "Api-Key key-123"
        assert call_kwargs[1]["json"]["patientId"] == "pat-1"
        assert call_kwargs[1]["json"]["deviceId"] == "dev-1"
        assert call_kwargs[1]["json"]["orderId"] == "ord-1"
        assert call_kwargs[1]["json"]["reason"] == "defective"


class TestCreateRmaRetry:
    """create_rma retries on 5xx, does not retry 4xx."""

    @pytest.mark.asyncio
    async def test_retries_on_5xx(self):
        import httpx
        from src.impilo_client import create_rma

        fail_response = MagicMock()
        fail_response.status_code = 502
        fail_response.raise_for_status = MagicMock(
            side_effect=httpx.HTTPStatusError(
                "502", request=MagicMock(), response=fail_response
            )
        )

        success_response = MagicMock()
        success_response.status_code = 200
        success_response.json.return_value = {"id": "ret-002", "status": "initiated"}
        success_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=[fail_response, success_response])
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("src.impilo_client.httpx.AsyncClient", return_value=mock_client):
            with patch("src.impilo_client.asyncio.sleep", new_callable=AsyncMock):
                result = await create_rma(
                    api_url="http://impilo.test",
                    api_key="key-123",
                    patient_id="pat-1",
                    device_id="dev-1",
                    order_id="ord-1",
                    reason="defective",
                )

        assert result == {"id": "ret-002", "status": "initiated"}
        assert mock_client.post.call_count == 2

    @pytest.mark.asyncio
    async def test_no_retry_on_4xx(self):
        import httpx
        from src.impilo_client import create_rma

        fail_response = MagicMock()
        fail_response.status_code = 400
        fail_response.raise_for_status = MagicMock(
            side_effect=httpx.HTTPStatusError(
                "400", request=MagicMock(), response=fail_response
            )
        )

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=fail_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("src.impilo_client.httpx.AsyncClient", return_value=mock_client):
            with pytest.raises(httpx.HTTPStatusError):
                await create_rma(
                    api_url="http://impilo.test",
                    api_key="key-123",
                    patient_id="pat-1",
                    device_id="dev-1",
                    order_id="ord-1",
                    reason="defective",
                )

        assert mock_client.post.call_count == 1

    @pytest.mark.asyncio
    async def test_raises_after_3_retries_exhausted(self):
        import httpx
        from src.impilo_client import create_rma

        fail_response = MagicMock()
        fail_response.status_code = 503
        fail_response.raise_for_status = MagicMock(
            side_effect=httpx.HTTPStatusError(
                "503", request=MagicMock(), response=fail_response
            )
        )

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=fail_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("src.impilo_client.httpx.AsyncClient", return_value=mock_client):
            with patch("src.impilo_client.asyncio.sleep", new_callable=AsyncMock):
                with pytest.raises(httpx.HTTPStatusError):
                    await create_rma(
                        api_url="http://impilo.test",
                        api_key="key-123",
                        patient_id="pat-1",
                        device_id="dev-1",
                        order_id="ord-1",
                        reason="defective",
                    )

        # 1 initial + 3 retries = 4 attempts
        assert mock_client.post.call_count == 4
