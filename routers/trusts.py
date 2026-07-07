import decimal
from fastapi import APIRouter, HTTPException, Path, Body, UploadFile, File, Form, BackgroundTasks
from fastapi.responses import JSONResponse
from fastapi.encoders import jsonable_encoder
from typing import List, Optional, Union
from pydantic import BaseModel
from datetime import date
import re
import os
import time
import json
from datetime import datetime

def parse_fuzzy_date(date_str):
    try:
        return datetime.strptime(date_str, "%d %B %Y")
    except Exception:
        return None
from database import get_mssql_connection
from utils.document_creator import generate_trust_docx
from utils.formatter import (
    format_establishment_date,
    format_legal_establishment_date,
    generate_trust_name,
)
from utils.email_sender import (
    send_confirmation_email,
    send_admin_email_with_attachments,
    send_admin_email_with_attachments_xrp,
    send_amended_trust_email
)
from utils.pdf_converter import convert_docx_to_pdf_libreoffice

router = APIRouter()

MEMBER_NUMBER_REGEX = re.compile(r"^BB\d{6}$")


def sanitize_filename(name: str) -> str:
    return re.sub(r'[^\w\s-]', '', name).strip().replace(' ', '_')


def wait_for_file(file_path: str, timeout: int = 30, interval: float = 0.5):
    total_wait = 0
    while not os.path.exists(file_path):
        time.sleep(interval)
        total_wait += interval
        if total_wait > timeout:
            raise TimeoutError(f"File {file_path} not found after {timeout} seconds")




# ---- Update Referrers (bulk insert) ----
@router.post("/update-referrers")
async def update_referrers():
    sql = """
    INSERT INTO HKFT_Master.dbo.Referrers (
        Ref_Code,
        Name,
        Role,
        Payment_Method,
        Fee,
        Fee_Date_From
    )
    SELECT DISTINCT
        ea.Number AS Ref_Code,
        RTRIM(LTRIM(e.Name)) + ' ' + RTRIM(LTRIM(e.LastName)) AS Name,
        'Referrer' AS Role,
        NULL AS Payment_Method,
        250 AS Fee,
        CAST('2025-07-01' AS DATE) AS Fee_Date_From
    FROM
        HKFT_Master.dbo.TrustApplication ta
    JOIN
        Bullion_Master.dbo.EntityAccounts ea ON ta.referrer_number = ea.Number
    JOIN
        Bullion_Master.dbo.Entities e ON ea.EntityID = e.ID
    WHERE
        ta.referrer_number IS NOT NULL
        AND LTRIM(RTRIM(ta.referrer_number)) <> ''
        AND NOT EXISTS (
            SELECT 1
            FROM HKFT_Master.dbo.Referrers r
            WHERE r.Ref_Code = ea.Number
        );
    """
    try:
        conn = get_mssql_connection()
        cursor = conn.cursor()
        # Execute the bulk insert
        cursor.execute(sql)
        # Fetch number of rows inserted from @@ROWCOUNT for reliability
        cursor.execute("SELECT @@ROWCOUNT")
        row = cursor.fetchone()
        inserted = int(row[0] or 0)
        conn.commit()
        cursor.close()
        conn.close()
        return JSONResponse(content={"message": "Referrers updated.", "inserted": inserted})
    except Exception as e:
        try:
            if 'conn' in locals() and conn:
                conn.rollback()
        except Exception:
            pass
        raise HTTPException(status_code=500, detail=f"Failed to update referrers: {e}")


# ---- Referrer Payment Endpoint ----
class ReferrerPaymentInput(BaseModel):
    ref_code: str
    amount: float
    payment_date: date
    payment_method: str = "EFT"  # default if not specified

@router.post("/referrer-payments")
async def create_referrer_payment(payment: ReferrerPaymentInput):
    try:
        conn = get_mssql_connection()
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO ReferrerPayments (Ref_Code, Amount, Payment_Date, Payment_Method)
            VALUES (?, ?, ?, ?)
        """, (payment.ref_code, payment.amount, payment.payment_date, payment.payment_method))

        conn.commit()
        cursor.close()
        conn.close()

        return JSONResponse(content={"message": "Payment recorded successfully."})

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to record payment: {e}")


@router.get("/all-referrer-fee-summaries")
async def get_all_referrer_fee_summaries():
    try:
        import decimal
        conn = get_mssql_connection()
        cursor = conn.cursor()

        # Step 1: Get all referrers
        cursor.execute("SELECT Ref_Code, Role, Fee, Fee1, Fee_Date_From_1, Name FROM Referrers")
        referrers = cursor.fetchall()

        summaries = []

        for ref_code, role, fee, fee1, fee_date_from_1, name in referrers:
            # 2. Get total fees payable
            if role == 'IT Dev':
                # IT Devs: all paid trusts
                cursor.execute("""
                    SELECT submitted_at
                    FROM TrustApplication
                    WHERE payment_status = 'paid'
                """)
            else:
                # Regular referrers
                cursor.execute("""
                    SELECT submitted_at
                    FROM TrustApplication
                    WHERE payment_status = 'paid' AND referrer_number = ?
                """, (ref_code,))

            trusts = cursor.fetchall()
            total_fees = 0
            for (submitted_at,) in trusts:
                use_fee1 = (
                        fee_date_from_1 and fee1 is not None and submitted_at >= fee_date_from_1
                )
                total_fees += float(fee1) if use_fee1 else float(fee or 0)

            # 3. Get total paid
            cursor.execute("""
                SELECT SUM(Amount) FROM ReferrerPayments WHERE Ref_Code = ?
            """, (ref_code,))
            result = cursor.fetchone()
            total_paid = float(result[0] or 0)

            # 4. Compute outstanding
            total_outstanding = total_fees - total_paid

            summaries.append({
                "referrer_name": name,
                "total_fees_payable": total_fees,
                "total_paid": total_paid,
                "total_outstanding": total_outstanding
            })

        cursor.close()
        conn.close()

        return summaries

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate summaries: {e}")


# ---- Referrer Fee Summary Endpoint ----
@router.get("/referrer-fee-summary/{ref_code}")
async def get_referrer_fee_summary(ref_code: str):
    try:
        import decimal
        conn = get_mssql_connection()
        cursor = conn.cursor()

        query = """
        WITH RefData AS (
            -- Trusts referred by referrer
            SELECT
                FORMAT(ta.submitted_at, 'dd MMMM yyyy') AS [Date Established],
                ta.trust_number AS [Trust No],
                ta.trust_name AS [Trust Name],
                r.Role,
                CASE
                    WHEN r.Fee_Date_From IS NOT NULL AND r.Fee1 IS NOT NULL AND ta.submitted_at >= r.Fee_Date_From_1 THEN r.Fee1
                    ELSE r.Fee
                END AS [Fee Payable],
                NULL AS [Payment Date],
                NULL AS [Payment Amount],
                r.Ref_Code
            FROM TrustApplication ta
            INNER JOIN Referrers r ON ta.referrer_number = r.Ref_Code
            WHERE ta.payment_status = 'paid'

            UNION ALL

            -- IT Devs: paid for all paid trusts (no referral code needed)
            SELECT
                FORMAT(ta.submitted_at, 'dd MMMM yyyy'),
                ta.trust_number,
                ta.trust_name,
                r.Role,
                CASE
                    WHEN r.Fee_Date_From IS NOT NULL AND r.Fee1 IS NOT NULL AND ta.submitted_at >= r.Fee_Date_From_1 THEN r.Fee1
                    ELSE r.Fee
                END,
                NULL,
                NULL,
                r.Ref_Code
            FROM TrustApplication ta
            CROSS JOIN Referrers r
            WHERE r.Role = 'IT Dev'
              AND ta.payment_status = 'paid'

            UNION ALL

            -- Payments made to referrer
            SELECT
                NULL,
                NULL,
                'Payment',
                r.Role,
                NULL,
                FORMAT(rp.Payment_Date, 'dd MMMM yyyy'),
                rp.Amount * -1,
                r.Ref_Code
            FROM ReferrerPayments rp
            INNER JOIN Referrers r ON r.Ref_Code = rp.Ref_Code
        )

        SELECT 
            [Date Established],
            [Trust No],
            [Trust Name],
            [Role],
            [Fee Payable],
            [Payment Date],
            [Payment Amount]
        FROM RefData
        WHERE Ref_Code = ?
        ORDER BY ISNULL([Payment Date], [Date Established]);
        """

        cursor.execute(query, (ref_code,))
        rows = cursor.fetchall()
        columns = [column[0] for column in cursor.description]

        data = []
        for row in rows:
            row_dict = dict(zip(columns, row))
            for key, value in row_dict.items():
                if isinstance(value, datetime):
                    row_dict[key] = value.isoformat()
                elif isinstance(value, decimal.Decimal):
                    row_dict[key] = float(value)
            data.append(row_dict)

        # Summary calculations
        fee_rows = [r for r in data if r.get("Fee Payable") is not None]
        payment_rows = [r for r in data if r.get("Payment Amount") is not None]

        total_paid_trusts = len(fee_rows)
        total_fees_payable = sum(r["Fee Payable"] or 0 for r in fee_rows)
        total_paid = sum(abs(r["Payment Amount"]) for r in payment_rows)
        total_outstanding = total_fees_payable - total_paid

        role = data[0]["Role"] if data else None

        cursor.close()
        conn.close()

        return JSONResponse(content={
            "ref_code": ref_code,
            "data": data,
            "summary": {
                "total_paid_trusts": total_paid_trusts,
                "total_fees_payable": total_fees_payable,
                "total_paid": total_paid,
                "total_outstanding": total_outstanding
            },
            "role": role
        })

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate referrer summary: {e}")

@router.get("/signups-per-day")
async def get_signups_per_day():
    try:
        conn = get_mssql_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT
                CONVERT(VARCHAR(10), submitted_at, 120) AS signup_date,
                COUNT(*) AS count
            FROM TrustApplication
            GROUP BY CONVERT(VARCHAR(10), submitted_at, 120)
            ORDER BY signup_date ASC
        """)
        results = [{"date": row[0], "count": row[1]} for row in cursor.fetchall()]
        cursor.close()
        conn.close()
        return JSONResponse(content=results)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch signup data: {e}")

@router.get("")
async def get_all_trusts():
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
                payment_reference, 
                CAST(payment_amount AS FLOAT) AS payment_amount,
                payment_currency,
                payment_method, 
                CAST(payment_xrp_qty AS FLOAT) AS payment_xrp_qty,
                payment_xrp_trans_id,
                payment_status, payment_timestamp,
                submitted_at, source, status,
                CAST(has_paid AS NVARCHAR(10)) AS has_paid
            FROM TrustApplication
            ORDER BY submitted_at DESC
        """)
        columns = [column[0] for column in cursor.description]
        results = [dict(zip(columns, row)) for row in cursor.fetchall()]
        cursor.close()
        conn.close()
        return JSONResponse(content=jsonable_encoder(results))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch trusts from MSSQL: {e}")

@router.get("/sql-documents/{trust_number:path}")
async def get_sql_documents(trust_number: str):
    try:
        conn = get_mssql_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT  trust_deed_doc_binary, trust_deed_pdf_binary
            FROM TrustApplication
            WHERE trust_number = ?
        """, (trust_number,))

        row = cursor.fetchone()
        cursor.close()
        conn.close()

        if not row:
            raise HTTPException(status_code=404, detail="Trust not found in SQL database.")

        import base64

        return {
            "trust_number": trust_number,
            "trust_deed_doc_binary": base64.b64encode(row[0]).decode("utf-8") if row[0] else None,
            "trust_deed_pdf_binary": base64.b64encode(row[1]).decode("utf-8") if row[1] else None,
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch documents: {e}")

# ---- New endpoints for PDF and DOCX download ----
from fastapi.responses import Response

@router.get("/sql-documents/{trust_number:path}/pdf")
async def download_pdf(trust_number: str):
    try:
        conn = get_mssql_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT trust_deed_pdf_binary
            FROM TrustApplication
            WHERE trust_number = ?
        """, (trust_number,))
        row = cursor.fetchone()
        cursor.close()
        conn.close()

        if not row or not row[0]:
            raise HTTPException(status_code=404, detail="PDF not found.")

        return Response(
            content=row[0],
            media_type="application/pdf",
            headers={
                "Content-Disposition": f"inline; filename={trust_number}.pdf"
            }
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to load PDF: {e}")


@router.get("/sql-documents/{trust_number:path}/doc")
async def download_docx(trust_number: str):
    try:
        conn = get_mssql_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT trust_deed_doc_binary
            FROM TrustApplication
            WHERE trust_number = ?
        """, (trust_number,))
        row = cursor.fetchone()
        cursor.close()
        conn.close()

        if not row or not row[0]:
            raise HTTPException(status_code=404, detail="DOCX not found.")

        return Response(
            content=row[0],
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            headers={
                "Content-Disposition": f"attachment; filename={trust_number}.docx"
            }
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to load DOCX: {e}")


@router.get("/{trust_number:path}")
async def get_trust_by_number(trust_number: str = Path(..., description="The trust number of the trust")):
    try:
        conn = get_mssql_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT
                ID,
                trust_number,
                trust_name,
                full_name,
                id_number,
                email,
                phone_number,
                trust_email,
                establishment_date_1,
                establishment_date_2,
                beneficiaries,
                is_bullion_member,
                member_number,
                referrer_number,
                settlor_name,
                settlor_id,
                trustee1_name,
                trustee1_id,
                trustee2_name,
                trustee2_id,
                trustee3_name,
                trustee3_id,
                trustee4_name,
                trustee4_id,
                payment_reference,
                payment_amount,
                payment_currency,
                payment_method,
                payment_xrp_qty,
                payment_xrp_trans_id,
                payment_status,
                payment_timestamp,
                submitted_at,
                source,
                status,
                has_paid,
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
        """, (trust_number,))
        row = cursor.fetchone()
        columns = [column[0] for column in cursor.description]
        cursor.close()
        conn.close()
        if not row:
            return JSONResponse(status_code=404, content={"detail": "Trust not found."})

        # Convert Decimal values to float to avoid JSON serialization issues
        import decimal
        row_dict = {}
        for idx, value in enumerate(row):
            if isinstance(value, decimal.Decimal):
                row_dict[columns[idx]] = float(value)
            else:
                row_dict[columns[idx]] = value

        return JSONResponse(content=jsonable_encoder(row_dict))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch trust: {e}")

@router.put("/{trust_number}/update-paid")
async def update_has_paid(trust_number: str, has_paid: str = Body(...)):
    allowed_values = ["xrp", "card", "eft"]
    has_paid_lower = has_paid.lower()
    if has_paid_lower not in allowed_values:
        raise HTTPException(status_code=400, detail=f"Invalid value for has_paid. Allowed values: {allowed_values}")

    db_value = has_paid_lower

    try:
        conn = get_mssql_connection()
        cursor = conn.cursor()
        result = cursor.execute(
            "UPDATE TrustApplication SET has_paid = ? WHERE trust_number = ?",
            (db_value, trust_number)
        )
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="Trust not found.")
        conn.commit()
        cursor.close()
        conn.close()
        return {"message": "Payment status updated successfully."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update trust: {e}")


@router.put("/{trust_number}/update-member")
async def update_member_number(trust_number: str, member_number: str = Body(...)):
    if not MEMBER_NUMBER_REGEX.match(member_number):
        raise HTTPException(
            status_code=400,
            detail="Member number must start with 'BB' followed by 6 digits (e.g., BB123456)."
        )
    try:
        conn = get_mssql_connection()
        cursor = conn.cursor()

        # Check for existing trust
        cursor.execute("SELECT member_number FROM TrustApplication WHERE trust_number = ?", (trust_number,))
        row = cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Trust not found.")
        current_member_number = row[0]

        if member_number == current_member_number:
            return {"message": "Member number unchanged."}

        # Check for duplicate member number
        cursor.execute(
            "SELECT trust_number, full_name FROM TrustApplication WHERE member_number = ?",
            (member_number,)
        )
        existing = cursor.fetchone()
        if existing and existing[0] != trust_number:
            raise HTTPException(status_code=400, detail=f"Member number already belongs to {existing[1]}.")

        # Update member number
        cursor.execute(
            "UPDATE TrustApplication SET member_number = ? WHERE trust_number = ?",
            (member_number, trust_number)
        )
        conn.commit()
        cursor.close()
        conn.close()
        return {"message": "Member number updated successfully."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update member number: {e}")


def parse_and_validate_trustees(trustees_str: str) -> List[dict]:
    try:
        trustees_list = json.loads(trustees_str)
        if not isinstance(trustees_list, list):
            raise ValueError("Invalid trustee list format")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid trustees format: {str(e)}")

    if not 2 <= len(trustees_list) <= 4:
        raise HTTPException(status_code=400, detail="Only 2 to 4 trustees are supported.")

    return trustees_list

def parse_has_paid_value(has_paid: str) -> str:
    allowed = ["xrp", "card", "eft"]
    lowered = has_paid.lower()
    if lowered not in allowed:
        raise HTTPException(status_code=400, detail=f"Invalid value for has_paid. Allowed values: {allowed}")
    return lowered

# ---- Referrer Payment Endpoint ----
class ReferrerPaymentInput(BaseModel):
    ref_code: str
    amount: float
    payment_date: date
    payment_method: str = "EFT"  # default if not specified

@router.post("/referrer-payments")
async def create_referrer_payment(payment: ReferrerPaymentInput):
    try:
        conn = get_mssql_connection()
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO ReferrerPayments (Ref_Code, Amount, Payment_Date, Payment_Method)
            VALUES (?, ?, ?, ?)
        """, (payment.ref_code, payment.amount, payment.payment_date, payment.payment_method))

        conn.commit()
        cursor.close()
        conn.close()

        return JSONResponse(content={"message": "Payment recorded successfully."})

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to record payment: {e}")


# ---- Edit Existing Trust: Models ----
class TrusteeInput(BaseModel):
    name: str
    id: str

class TrustLookupInput(BaseModel):
    trust_number: str
    id_or_passport: str  # settlor or original applicant's ID/passport

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
    # --- Extra fields for backend capture ---
    settlor_email: Optional[str] = None
    trustee1_email: Optional[str] = None
    trustee2_email: Optional[str] = None
    trustee3_email: Optional[str] = None
    owner_name: Optional[str] = None
    owner_id: Optional[str] = None
    owner_email: Optional[str] = None
    signer_name: Optional[str] = None
    signer_id: Optional[str] = None
    signer_email: Optional[str] = None
    Property_Address: Optional[str] = None


@router.post("/edit-trust/lookup")
async def lookup_trust(payload: TrustLookupInput):
    """
    Verify the settlor/applicant via trust_number + ID/Passport and return the existing record for editing.
    Only returns fields that are editable on the front-end. Trust name & number are returned for display but are immutable.
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
                submitted_at, source, status, has_paid
            FROM TrustApplication
            WHERE trust_number = ?
              AND (
                  id_number = ? OR settlor_id = ?
              )
        """, (payload.trust_number, payload.id_or_passport, payload.id_or_passport))
        row = cursor.fetchone()
        columns = [c[0] for c in cursor.description] if cursor.description else []
        cursor.close()
        conn.close()

        if not row:
            raise HTTPException(status_code=404, detail="No matching trust found for the provided details.")

        record = dict(zip(columns, row))

        # Convert problematic types into JSON-safe formats
        import decimal
        from datetime import datetime
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
            "establishment_date": record["establishment_date_2"] or record["establishment_date_1"],  # prefer legal format if present
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
        })
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to lookup trust: {e}")


@router.put("/edit-trust/{trust_number:path}")
async def update_trust_and_regenerate_deed(
    trust_number: str,
    payload: TrustEditPayload,
    background_tasks: BackgroundTasks
):
    """
    Update editable fields for an existing trust (trust_number & trust_name remain unchanged),
    regenerate the deed (DOCX + PDF), store binaries, and email the amended deed to the client and admin.
    """
    try:
        # 1) Load the existing record and verify existence
        conn = get_mssql_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT
                trust_number, trust_name, full_name, id_number, email,
                establishment_date_2, settlor_name, settlor_id
            FROM TrustApplication
            WHERE trust_number = ?
        """, (trust_number,))
        base_row = cursor.fetchone()
        if not base_row:
            cursor.close()
            conn.close()
            raise HTTPException(status_code=404, detail="Trust not found.")

        # Keep immutable fields from DB
        existing_trust_name = base_row[1]
        existing_full_name = base_row[2]  # original applicant, used for email greeting

        # 2) Validate trustees list (2–4)
        trustees_list = payload.trustees or []
        if not 2 <= len(trustees_list) <= 4:
            cursor.close()
            conn.close()
            raise HTTPException(status_code=400, detail="Only 2 to 4 trustees are supported.")

        # 3) Recompute formatted dates
        formatted_date_1 = format_establishment_date(payload.establishment_date)
        formatted_date_2 = format_legal_establishment_date(payload.establishment_date)
        # Convert for SQL (datetime or None)
        establishment_date_1_sql = parse_fuzzy_date(formatted_date_1)
        establishment_date_2_sql = parse_fuzzy_date(formatted_date_2)

        # 4) Prepare doc generation values
        trust_data = {"trust_number": trust_number, "trust_name": existing_trust_name, "full_name": existing_full_name,
                      "id_number": payload.id_number, "email": payload.email, "phone_number": payload.phone_number,
                      "trust_email": payload.trust_email, "establishment_date_1": formatted_date_1,
                      "establishment_date_2": formatted_date_2, "beneficiaries": payload.beneficiaries,
                      "is_bullion_member": payload.is_bullion_member, "member_number": payload.member_number,
                      "referrer_number": payload.referrer_number, "settlor_name": payload.settlor_name,
                      "settlor_id": payload.settlor_id, "settlor_email": getattr(payload, "settlor_email", None),
                      "trustee1_email": getattr(payload, "trustee1_email", None),
                      "trustee2_email": getattr(payload, "trustee2_email", None),
                      "trustee3_email": getattr(payload, "trustee3_email", None),
                      "owner_name": getattr(payload, "owner_name", None),
                      "owner_id": getattr(payload, "owner_id", None),
                      "owner_email": getattr(payload, "owner_email", None),
                      "signer_name": getattr(payload, "signer_name", None),
                      "signer_id": getattr(payload, "signer_id", None),
                      "signer_email": getattr(payload, "signer_email", None),
                      "Property_Address": getattr(payload, "Property_Address", None)}

        # Add extra optional fields if present

        # Add trustees to dict (support Pydantic models or plain dicts)
        for idx, tr in enumerate(trustees_list, start=1):
            name = getattr(tr, "name", None)
            tid = getattr(tr, "id", None)
            if name is None and isinstance(tr, dict):
                name = tr.get("name", "")
            if tid is None and isinstance(tr, dict):
                tid = tr.get("id", "")
            trust_data[f"trustee{idx}_name"] = name or ""
            trust_data[f"trustee{idx}_id"] = tid or ""
        # Ensure empty slots exist up to 4
        for idx in range(len(trustees_list) + 1, 5):
            trust_data[f"trustee{idx}_name"] = ""
            trust_data[f"trustee{idx}_id"] = ""

        # Determine if first trustee is the same as the settlor (supports model or dict)
        first_trustee = trustees_list[0] if trustees_list else None
        ft_name = getattr(first_trustee, "name", None)
        ft_id = getattr(first_trustee, "id", None)
        if (ft_name is None or ft_id is None) and isinstance(first_trustee, dict):
            ft_name = first_trustee.get("name")
            ft_id = first_trustee.get("id")
        same_as_settlor = (
            ((payload.settlor_name or "").strip().lower() == (ft_name or "").strip().lower()) and
            ((payload.settlor_id or "").strip() == (ft_id or "").strip())
        )
        tcount = len(trustees_list)
        if tcount == 2:
            template = "_HKGFT Deed 2 Trustees Same settlor.docx" if same_as_settlor else "_HKGFT Deed 2 Trustees.docx"
        elif tcount == 3:
            template = "_HKGFT Deed 3 Trustees same Settlor.docx" if same_as_settlor else "_HKGFT Deed 3 Trustees.docx"
        elif tcount == 4:
            template = "_HKGFT Deed 4 Trustees Same settlor.docx" if same_as_settlor else "_HKGFT Deed 4 Trustees.docx"
        else:
            cursor.close()
            conn.close()
            raise HTTPException(status_code=400, detail="Unsupported number of trustees.")

        # 5) Generate new DOCX & PDF into a stable folder based on trust name
        safe_folder_name = sanitize_filename(existing_trust_name)
        upload_dir = f"uploads/{safe_folder_name}"
        os.makedirs(upload_dir, exist_ok=True)
        docx_path = os.path.join(upload_dir, f"{safe_folder_name}_AMENDED.docx")
        generate_trust_docx(trust_data, template_path=f"templates/{template}", output_path=docx_path)
        wait_for_file(docx_path, timeout=15)

        try:
            pdf_path = convert_docx_to_pdf_libreoffice(docx_path, upload_dir)
        except Exception as e:
            cursor.close()
            conn.close()
            raise HTTPException(status_code=500, detail=f"❌ Failed to convert amended DOCX to PDF: {str(e)}")

        # 6) Read binaries
        with open(docx_path, "rb") as f:
            docx_binary = f.read()
        with open(pdf_path, "rb") as f:
            pdf_binary = f.read()

        # 7) Persist updates to DB (immutable: trust_number, trust_name)
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE TrustApplication
            SET
                id_number = ?,
                email = ?,
                phone_number = ?,
                trust_email = ?,
                establishment_date_1 = ?,
                establishment_date_2 = ?,
                beneficiaries = ?,
                is_bullion_member = ?,
                member_number = ?,
                referrer_number = ?,
                settlor_name = ?,
                settlor_id = ?,
                settlor_email = ?,
                trustee1_name = ?,
                trustee1_id = ?,
                trustee1_email = ?,
                trustee2_name = ?,
                trustee2_id = ?,
                trustee2_email = ?,
                trustee3_name = ?,
                trustee3_id = ?,
                trustee3_email = ?,
                trustee4_name = ?,
                trustee4_id = ?,
                owner_name = ?,
                owner_id = ?,
                owner_email = ?,
                signer_name = ?,
                signer_id = ?,
                signer_email = ?,
                Property_Address = ?,
                trust_deed_doc_binary = ?,
                trust_deed_pdf_binary = ?
            WHERE trust_number = ?
        """, (
            trust_data["id_number"],
            trust_data["email"],
            trust_data["phone_number"],
            trust_data["trust_email"],
            establishment_date_1_sql,
            establishment_date_2_sql,
            trust_data["beneficiaries"],
            trust_data["is_bullion_member"],
            trust_data["member_number"],
            trust_data["referrer_number"],
            trust_data["settlor_name"],
            trust_data["settlor_id"],
            trust_data.get("settlor_email"),
            trust_data.get("trustee1_name"), trust_data.get("trustee1_id"), trust_data.get("trustee1_email"),
            trust_data.get("trustee2_name"), trust_data.get("trustee2_id"), trust_data.get("trustee2_email"),
            trust_data.get("trustee3_name"), trust_data.get("trustee3_id"), trust_data.get("trustee3_email"),
            trust_data.get("trustee4_name"), trust_data.get("trustee4_id"),
            trust_data.get("owner_name"),
            trust_data.get("owner_id"),
            trust_data.get("owner_email"),
            trust_data.get("signer_name"),
            trust_data.get("signer_id"),
            trust_data.get("signer_email"),
            trust_data.get("Property_Address"),
            docx_binary,
            pdf_binary,
            trust_number
        ))
        conn.commit()
        cursor.close()
        conn.close()


        # 8) Email the amended deed (user + admin)
        def send_amended():
            try:
                # 1) Send amended-deed notice to the client (no attachments; attachments are policy-disabled in email_sender)
                send_amended_trust_email(
                    to_email=trust_data["email"],
                    full_name=existing_full_name,
                    trust_name=existing_trust_name,
                    pdf_path=pdf_path  # kept for signature compatibility; attachment skipped by policy
                )
            except Exception as e:
                print(f"[ERROR] Failed sending amended deed user email: {e}")

            try:
                # 2) Send admin email WITH attachments (DOCX + PDF)
                parties = {
                    "settlor_name": trust_data.get("settlor_name"),
                    "settlor_email": trust_data.get("settlor_email"),
                    "trustee1_name": trust_data.get("trustee1_name"),
                    "trustee1_email": trust_data.get("trustee1_email"),
                    "trustee2_name": trust_data.get("trustee2_name"),
                    "trustee2_email": trust_data.get("trustee2_email"),
                    "trustee3_name": trust_data.get("trustee3_name"),
                    "trustee3_email": trust_data.get("trustee3_email"),
                    "trustee4_name": trust_data.get("trustee4_name"),
                    "trustee4_email": trust_data.get("trustee4_email"),
                    "owner_name": trust_data.get("owner_name"),
                    "owner_email": trust_data.get("owner_email"),
                    "signer_name": trust_data.get("signer_name"),
                    "signer_email": trust_data.get("signer_email"),
                }
                send_admin_email_with_attachments(
                    admin_email="info@trusthub.biz",
                    trust_name=existing_trust_name,
                    docx_path=docx_path,
                    pdf_path=pdf_path,
                    parties=parties,
                )
            except Exception as e:
                print(f"[ERROR] Failed sending amended deed admin email: {e}")

        background_tasks.add_task(send_amended)

        return JSONResponse(content={
            "message": "Trust updated, amended deed generated; user notified and documents emailed to admin.",
            "trust_number": trust_number,
            "trust_name": existing_trust_name
        })
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update trust: {e}")