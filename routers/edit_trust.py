# routers/edit_trust.py
import os
from typing import List, Optional
from fastapi import APIRouter, HTTPException, Query, BackgroundTasks
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from database import get_mssql_connection
import decimal
from datetime import datetime
import json

from routers.trusts import wait_for_file, sanitize_filename, parse_fuzzy_date
from utils.document_creator import generate_trust_docx
from utils.email_sender import send_amended_trust_email
from utils.formatter import format_establishment_date, format_legal_establishment_date
from utils.pdf_converter import convert_docx_to_pdf_libreoffice

router = APIRouter()

# ---- Edit Existing Trust: Models ----
class TrusteeInput(BaseModel):
    name: str
    id: str

class TrustEditPayload(BaseModel):
    # NOTE: trust_number and trust_name are immutable and are NOT part of this payload
    id_number: str
    email: str
    phone_number: str
    trust_email: Optional[str] = None
    establishment_date: str
    beneficiaries: Optional[str] = None
    is_bullion_member: bool
    member_number: Optional[str] = None
    referrer_number: Optional[str] = None
    settlor_name: str
    settlor_id: str
    trustees: List[TrusteeInput]

# ---- Response Model for Trust Lookup ----
class TrustLookupResponse(BaseModel):
    trust_number: str
    trust_name: str
    full_name: str
    id_number: str
    email: str
    phone_number: str
    trust_email: Optional[str]
    establishment_date: Optional[str]
    beneficiaries: Optional[str]
    is_bullion_member: Optional[bool]
    member_number: Optional[str]
    referrer_number: Optional[str]
    settlor_name: Optional[str]
    settlor_id: Optional[str]
    trustees: List[TrusteeInput]
    payment_reference: Optional[str]
    payment_amount: Optional[float]
    payment_currency: Optional[str]
    payment_method: Optional[str]
    payment_xrp_qty: Optional[float]
    payment_xrp_trans_id: Optional[str]
    payment_status: Optional[str]
    payment_timestamp: Optional[str]
    submitted_at: Optional[str]
    source: Optional[str]
    status: Optional[str]
    has_paid: Optional[str]

    settlor_email: Optional[str]
    trustee1_email: Optional[str]
    trustee2_email: Optional[str]
    trustee3_email: Optional[str]
    owner_name: Optional[str]
    owner_id: Optional[str]
    owner_email: Optional[str]
    signer_name: Optional[str]
    signer_id: Optional[str]
    signer_email: Optional[str]
    Property_Address: Optional[str]


@router.get(
    "/lookup",
    summary="Lookup a trust for editing",
    description="Provide a trust_number and settlor/applicant ID or passport number to fetch the trust details for editing.",
    response_description="Trust details with editable fields",
    response_model=TrustLookupResponse
)
async def lookup_trust(
    trust_number: str = Query(..., description="The unique trust number to look up", example="HKFT-12345"),
    id_or_passport: str = Query(..., description="The settlor or applicant's ID/passport number", example="9501015009087"),
):
    """
    Lookup an existing trust for editing.

    **Request body parameters:**
    - `trust_number`: The trust’s unique number.
    - `id_or_passport`: The settlor or applicant’s ID/passport number.
    """
    try:
        conn = get_mssql_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT
                trust_number, trust_name, full_name, id_number, email, phone_number, trust_email,
                establishment_date_1, establishment_date_2, beneficiaries,
                is_bullion_member, member_number, referrer_number,
                settlor_name, settlor_id,
                trustee1_name, trustee1_id,
                trustee2_name, trustee2_id,
                trustee3_name, trustee3_id,
                trustee4_name, trustee4_id,
                payment_reference, payment_amount, payment_currency, payment_method,
                payment_xrp_qty, payment_xrp_trans_id, payment_status, payment_timestamp,
                submitted_at, source, status, has_paid,
                settlor_email,
                trustee1_email,
                trustee2_email,
                trustee3_email,
                owner_name,
                owner_id,
                owner_email,
                signer_name,
                signer_id,
                signer_email,
                Property_Address
            FROM TrustApplication
            WHERE trust_number = ?
              AND (
                  id_number = ? OR settlor_id = ?
              )
        """, (trust_number, id_or_passport, id_or_passport))
        row = cursor.fetchone()
        columns = [c[0] for c in cursor.description] if cursor.description else []
        cursor.close()
        conn.close()

        if not row:
            raise HTTPException(status_code=404, detail="No matching trust found for the provided details.")

        record = dict(zip(columns, row))

        # Convert problematic types into JSON-safe formats
        for key, value in record.items():
            if isinstance(value, decimal.Decimal):
                record[key] = float(value)
            elif isinstance(value, datetime):
                record[key] = value.isoformat()

        # Build trustees array from columns
        trustees = []
        for i in range(1, 5):
            nm = record.get(f"trustee{i}_name")
            idv = record.get(f"trustee{i}_id")
            if (nm or idv) and (str(nm).strip() or str(idv).strip()):
                trustees.append({"name": nm or "", "id": idv or ""})

        return JSONResponse(content={
            "trust_number": record["trust_number"],
            "trust_name": record["trust_name"],
            "full_name": record["full_name"],
            "id_number": record["id_number"],
            "email": record["email"],
            "phone_number": record["phone_number"],
            "trust_email": record["trust_email"],
            "establishment_date": record["establishment_date_2"] or record["establishment_date_1"],
            "beneficiaries": record["beneficiaries"],
            "is_bullion_member": record["is_bullion_member"],
            "member_number": record["member_number"],
            "referrer_number": record["referrer_number"],
            "settlor_name": record["settlor_name"],
            "settlor_id": record["settlor_id"],
            "trustees": trustees,
            "payment_reference": record.get("payment_reference"),
            "payment_amount": record.get("payment_amount"),
            "payment_currency": record.get("payment_currency"),
            "payment_method": record.get("payment_method"),
            "payment_xrp_qty": record.get("payment_xrp_qty"),
            "payment_xrp_trans_id": record.get("payment_xrp_trans_id"),
            "payment_status": record.get("payment_status"),
            "payment_timestamp": record.get("payment_timestamp"),
            "submitted_at": record.get("submitted_at"),
            "source": record.get("source"),
            "status": record.get("status"),
            "has_paid": record.get("has_paid"),
            "settlor_email": record.get("settlor_email"),
            "trustee1_email": record.get("trustee1_email"),
            "trustee2_email": record.get("trustee2_email"),
            "trustee3_email": record.get("trustee3_email"),
            "owner_name": record.get("owner_name"),
            "owner_id": record.get("owner_id"),
            "owner_email": record.get("owner_email"),
            "signer_name": record.get("signer_name"),
            "signer_id": record.get("signer_id"),
            "signer_email": record.get("signer_email"),
            "Property_Address": record.get("Property_Address"),
        })
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to lookup trust: {e}")
