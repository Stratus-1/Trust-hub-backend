import os
import uuid
import httpx
import hmac
import hashlib
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from dotenv import load_dotenv
from bson import ObjectId
from database import trusts_collection  # Your MongoDB collection

load_dotenv()

router = APIRouter()

YOCO_SECRET_KEY = os.getenv("YOCO_SECRET_KEY")
YOCO_WEBHOOK_SECRET = os.getenv("YOCO_WEBHOOK_SECRET")


class PaymentRequest(BaseModel):
    amount_cents: int
    trust_data: dict  # Full trust form data


from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from bson import ObjectId
import httpx
import uuid
import os

# If you're using MongoDB directly
from database import trusts_collection

router = APIRouter()

YOCO_SECRET_KEY = os.getenv("YOCO_SECRET_KEY")


class TrustData(BaseModel):
    email: str
    fullName: str
    idNumber: str
    phoneNumber: str
    trustEmail: str
    trustName: str
    establishmentDate: str
    memberNumber: str
    isBullionMember: bool
    isSettlor: bool
    isTrustee: bool
    wasReferredByMember: bool
    referrerNumber: str = ""
    altSettlorName: str = ""
    beneficiaries: str = ""
    settlor: dict
    trustee1: dict
    trustee2: dict
    trustee3: dict
    propertyOwner: str = ""
    propertyAddress: str = ""


class PaymentSessionRequest(BaseModel):
    amount_cents: int
    trust_data: TrustData


@router.post("/payment-session")
async def create_payment_session(
    payload: PaymentSessionRequest
):
    if not YOCO_SECRET_KEY:
        raise HTTPException(status_code=500, detail="Yoco secret key not configured")

    # 1. Insert trust into MongoDB
    trust_doc = payload.trust_data.dict()
    result = await trusts_collection.insert_one(trust_doc)
    trust_id = str(result.inserted_id)

    # 2. Build Yoco request
    url = "https://payments.yoco.com/api/checkouts"
    headers = {
        "Authorization": f"Bearer {YOCO_SECRET_KEY}",
        "Idempotency-Key": str(uuid.uuid4()),
        "Content-Type": "application/json"
    }
    data = {
        "amount": payload.amount_cents,
        "currency": "ZAR",
        "successUrl": "https://www.trusthub.biz/success",
        "cancelUrl": "https://www.trusthub.biz/cancel",
        "failureUrl": "https://www.trusthub.biz/failure",
        "metadata": {
            "trust_id": trust_id
        }
    }

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(url, headers=headers, json=data)
            response_data = response.json()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Yoco request failed: {e}")

    if response.status_code in [200, 201] and 'redirectUrl' in response_data:
        return {
            "status": "success",
            "redirectUrl": response_data["redirectUrl"],
            "trust_id": trust_id
        }
    else:
        raise HTTPException(status_code=400, detail=response_data.get("message", "Failed to create payment session"))



@router.post("/payment-webhook")
async def yoco_webhook(request: Request):
    # Verify Yoco webhook signature
    if not YOCO_WEBHOOK_SECRET:
        raise HTTPException(status_code=500, detail="Yoco webhook secret not configured")

    # Read raw body for HMAC calculation
    raw_body = await request.body()
    signature_header = request.headers.get("X-Yoco-Signature")
    if not signature_header:
        raise HTTPException(status_code=401, detail="Missing Yoco webhook signature")

    expected_signature = hmac.new(
        YOCO_WEBHOOK_SECRET.encode(),
        raw_body,
        hashlib.sha256
    ).hexdigest()

    if not hmac.compare_digest(expected_signature, signature_header):
        raise HTTPException(status_code=401, detail="Invalid Yoco webhook signature")

    payload = await request.json()
    event_type = payload.get("type")
    data = payload.get("data", {})

    if event_type == "payment.succeeded":
        metadata = data.get("metadata", {})
        trust_id = metadata.get("trust_id")

        if trust_id:
            await trusts_collection.update_one(
                {"_id": ObjectId(trust_id)},
                {"$set": {"has_paid": True}}
            )
            return {"status": "success"}

    return {"status": "ignored"}
