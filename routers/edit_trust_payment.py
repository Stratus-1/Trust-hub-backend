# routers/edit_trust_payment.py
import os
import uuid
import httpx
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from dotenv import load_dotenv
import hmac
import hashlib

load_dotenv()
router = APIRouter()

YOCO_SECRET_KEY = os.getenv("YOCO_SECRET_KEY")
YOCO_WEBHOOK_SECRET = os.getenv("YOCO_WEBHOOK_SECRET")


class EditTrustPaymentRequest(BaseModel):
    amount_cents: int
    payload: dict   # accept the edit trust payload so you can save it after payment


@router.post("/edit-trust-payment-session/{trust_number:path}")
async def create_edit_trust_payment_session(trust_number: str, payload: EditTrustPaymentRequest):
    """
    Create a Yoco payment session specifically for trust edits (fixed R165 fee).
    No MongoDB insert, just a payment session.
    """
    if not YOCO_SECRET_KEY:
        raise HTTPException(status_code=500, detail="Yoco secret key not configured")

    url = "https://payments.yoco.com/api/checkouts"
    headers = {
        "Authorization": f"Bearer {YOCO_SECRET_KEY}",
        "Idempotency-Key": str(uuid.uuid4()),
        "Content-Type": "application/json"
    }
    data = {
        "amount": payload.amount_cents,
        "currency": "ZAR",
        "successUrl": f"https://www.trusthub.biz/edit-trust?trust_number={trust_number}",
        "cancelUrl": "https://www.trusthub.biz/edit-cancel",
        "failureUrl": "https://www.trusthub.biz/edit-failure",
        "metadata": {
            "trust_number": trust_number,
            "edit_payload": payload.payload
        }
    }

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(url, headers=headers, json=data)
            response_data = response.json()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Yoco request failed: {e}")

    if response.status_code in [200, 201] and "redirectUrl" in response_data:
        return {
            "status": "success",
            "redirectUrl": response_data["redirectUrl"]
        }
    else:
        raise HTTPException(status_code=400, detail=response_data.get("message", "Failed to create payment session"))


@router.post("/edit-trust-payment-webhook")
async def yoco_edit_trust_webhook(request: Request):
    """
    Handle Yoco webhook for edit-trust payments.
    When payment succeeds, you’ll trigger the edit-trust API on frontend.
    """
    if not YOCO_WEBHOOK_SECRET:
        raise HTTPException(status_code=500, detail="Yoco webhook secret not configured")

    signature = request.headers.get("X-Yoco-Signature")
    body = await request.body()

    if not signature:
        raise HTTPException(status_code=400, detail="Missing X-Yoco-Signature header")

    computed_signature = hmac.new(
        YOCO_WEBHOOK_SECRET.encode(),
        body,
        hashlib.sha256
    ).hexdigest()

    if not hmac.compare_digest(computed_signature, signature):
        raise HTTPException(status_code=400, detail="Invalid signature")

    payload = await request.json()
    event_type = payload.get("type")

    if event_type == "payment.succeeded":
        # You could also log this in DB if needed
        return {"status": "success"}

    return {"status": "ignored"}