# routers/submit_trust.py
import os
import json
from datetime import datetime
from typing import List, Optional, Union
from fastapi import APIRouter, HTTPException, Body, UploadFile, File, Form, BackgroundTasks
from fastapi.responses import JSONResponse
from pydantic import BaseModel

# Pydantic model for request parameters
class SubmitTrustRequest(BaseModel):
    full_name: str
    id_number: str
    email: str
    phone_number: str
    trust_email: Optional[str] = None
    trust_name: str
    establishment_date: Optional[str] = None
    beneficiaries: Optional[str] = None
    is_bullion_member: bool
    member_number: Optional[str] = None
    referrer_number: Optional[str] = None
    settlor_name: str
    settlor_id: str
    settlor_email: Optional[str] = None
    owner_name: Optional[str] = None
    owner_id: Optional[str] = None
    owner_email: Optional[str] = None
    property_address: Optional[str] = None
    trustee1_name: Optional[str] = None
    trustee1_id: Optional[str] = None
    trustee1_email: Optional[str] = None
    trustee2_name: Optional[str] = None
    trustee2_id: Optional[str] = None
    trustee2_email: Optional[str] = None
    trustee3_name: Optional[str] = None
    trustee3_id: Optional[str] = None
    trustee3_email: Optional[str] = None
    has_paid: str = "false"
    payment_amount: Optional[float] = None
    payment_method: Optional[str] = None
    payment_xrp_qty: Optional[float] = None
    payment_xrp_trans_id: Optional[str] = None
    was_referred_by_member: bool = False

from database import get_mssql_connection
from utils.document_creator import generate_trust_docx
from utils.formatter import (
    format_establishment_date,
    format_legal_establishment_date,
    generate_trust_name,
)
from utils.pdf_converter import convert_docx_to_pdf_libreoffice
from utils.email_sender import (
    send_confirmation_email,
    send_admin_email_with_attachments,
    send_admin_email_with_attachments_xrp,
)

# Import helpers already in trusts.py
from routers.trusts import sanitize_filename, wait_for_file, parse_has_paid_value

router = APIRouter()

@router.post("/submit-trust", response_model=dict)
async def submit_trust(
    background_tasks: BackgroundTasks,
    full_name: str = Form(...),
    id_number: str = Form(...),
    email: str = Form(...),
    phone_number: str = Form(...),
    trust_email: Optional[str] = Form(None),
    trust_name: str = Form(...),
    establishment_date: Optional[str] = Form(None),
    establishmentDate: Optional[str] = Form(None),
    establishment_date_1: Optional[str] = Form(None),
    establishment_date_2: Optional[str] = Form(None),
    beneficiaries: Optional[str] = Form(None),
    is_bullion_member: bool = Form(...),
    member_number: Optional[str] = Form(None),
    referrer_number: Optional[str] = Form(None),
    settlor_name: str = Form(...),
    settlor_id: str = Form(...),
    settlor_email: Optional[str] = Form(None),
    owner_name: Optional[str] = Form(None),
    owner_id: Optional[str] = Form(None),
    owner_email: Optional[str] = Form(None),
    property_address: Optional[str] = Form(None),
    Property_Address: Optional[str] = Form(None),
    trustee1_name: Optional[str] = Form(None),
    trustee1_id: Optional[str] = Form(None),
    trustee1_email: Optional[str] = Form(None),
    trustee2_name: Optional[str] = Form(None),
    trustee2_id: Optional[str] = Form(None),
    trustee2_email: Optional[str] = Form(None),
    trustee3_name: Optional[str] = Form(None),
    trustee3_id: Optional[str] = Form(None),
    trustee3_email: Optional[str] = Form(None),
    signer_name: Optional[str] = Form(None),
    signer_id: Optional[str] = Form(None),
    signer_email: Optional[str] = Form(None),
    has_paid: str = Form("false"),
    payment_amount: Union[str, float, None] = Form(None),
    payment_method: Optional[str] = Form(None),
    payment_xrp_qty: Union[str, float, None] = Form(None),
    payment_xrp_trans_id: Optional[str] = Form(None),
    documents: List[UploadFile] = File(default=[]),
    was_referred_by_member: bool = Form(False),
):

    trust_prefix = 3200
    year_suffix = datetime.utcnow().strftime("%y")

    # Normalize establishment date: prefer canonical raw (snake/camel), else infer from _1/_2 if ISO-like
    def _looks_iso(d: Optional[str]) -> bool:
        if not isinstance(d, str):
            return False
        s = d.strip()
        if len(s) != 10:
            return False
        try:
            datetime.strptime(s, "%Y-%m-%d")
            return True
        except Exception:
            return False

    _raw_est_date = ""
    if isinstance(establishment_date, str) and establishment_date.strip():
        _raw_est_date = establishment_date.strip()
    elif isinstance(establishmentDate, str) and establishmentDate.strip():
        _raw_est_date = establishmentDate.strip()
    elif _looks_iso(establishment_date_1):
        _raw_est_date = establishment_date_1.strip()
    elif _looks_iso(establishment_date_2):
        _raw_est_date = establishment_date_2.strip()

    # Always format using helpers so both the doc and DB get the correct representations
    formatted_date_1 = format_establishment_date(_raw_est_date) if _raw_est_date else None
    formatted_date_2 = format_legal_establishment_date(_raw_est_date) if _raw_est_date else None

    print(
        f"[DEBUG] establishment fields -> raw='{_raw_est_date}', d1_in='{establishment_date_1}', d2_in='{establishment_date_2}', d1='{formatted_date_1}', d2='{formatted_date_2}'"
    )

    try:
        conn = get_mssql_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT TOP 1 trust_number
            FROM TrustApplication
            WHERE trust_number LIKE '[0-9][0-9][0-9][0-9]/%'
            ORDER BY trust_number DESC
        """)
        row = cursor.fetchone()
        cursor.close()
        conn.close()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch last trust number: {e}")

    if row:
        last_number = row[0].split('/')[0]
        try:
            latest_number = int(last_number)
        except ValueError:
            latest_number = trust_prefix
        new_number = latest_number + 1
    else:
        new_number = trust_prefix + 1

    trust_number = f"{new_number}/{year_suffix}"

    formatted_trust_name = generate_trust_name(trust_name)
    safe_folder_name = sanitize_filename(formatted_trust_name)

    upload_dir = f"uploads/{safe_folder_name}"
    os.makedirs(upload_dir, exist_ok=True)

    file_paths = []
    for file in documents:
        file_path = os.path.join(upload_dir, file.filename)
        with open(file_path, "wb") as f:
            f.write(await file.read())
        file_paths.append(file_path)

    has_paid_val = parse_has_paid_value(has_paid)

    # Coalesce property address from either key
    property_address_final = property_address or Property_Address

    allowed_values = ["xrp", "card", "eft"]
    if payment_method and payment_method.lower() not in allowed_values:
        raise HTTPException(status_code=400, detail=f"Invalid payment_method. Allowed values: {allowed_values}")

    try:
        parsed_amount = float(payment_amount) if payment_amount not in [None, ""] else None
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid payment_amount: must be a valid number")

    try:
        parsed_xrp_qty = float(payment_xrp_qty) if payment_xrp_qty not in [None, ""] else None
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid payment_xrp_qty: must be a valid number")

    trust_data = {
        "trust_number": trust_number,
        "full_name": full_name,
        "id_number": id_number,
        "email": email,
        "phone_number": phone_number,
        "trust_email": trust_email,
        "trust_name": formatted_trust_name,
        "establishment_date_1": formatted_date_1,
        "establishment_date_2": formatted_date_2,
        "beneficiaries": beneficiaries,
        "is_bullion_member": is_bullion_member,
        "member_number": member_number,
        "referrer_number": referrer_number,
        "settlor_name": settlor_name,
        "settlor_id": settlor_id,
        "settlor_email": settlor_email,
        "owner_name": owner_name,
        "owner_id": owner_id,
        "owner_email": owner_email,
        "trustee1_name": trustee1_name,
        "trustee1_id": trustee1_id,
        "trustee1_email": trustee1_email,
        "trustee2_name": trustee2_name,
        "trustee2_id": trustee2_id,
        "trustee2_email": trustee2_email,
        "trustee3_name": trustee3_name,
        "trustee3_id": trustee3_id,
        "trustee3_email": trustee3_email,
        "signer_name": signer_name,
        "signer_id": signer_id,
        "signer_email": signer_email,
        "property_address": property_address_final,
        "has_paid": has_paid_val,
        "created_at": datetime.utcnow(),
        "email_sent": False,
        "documents": file_paths[:],
        "was_referred_by_member": was_referred_by_member,
    }

    if payment_method and payment_method.lower() == "xrp":
        trust_data["payment_method"] = "xrp"
        trust_data["payment_amount_xrp"] = round(parsed_xrp_qty or 0, 4)
        trust_data["payment_amount_cents"] = None
        trust_data["payment_xrp_trans_id"] = payment_xrp_trans_id
    else:
        trust_data["payment_method"] = payment_method.lower() if payment_method else None
        trust_data["payment_amount_cents"] = int(parsed_amount * 100) if parsed_amount else None
        trust_data["payment_amount_xrp"] = None
        trust_data["payment_xrp_trans_id"] = None

    # No trustee parsing or template selection logic needed.
    docx_path = os.path.join(upload_dir, f"{safe_folder_name}.docx")
    # Use a default template (since template selection logic is now removed)
    template = "_HKGFT Deed 3 Trustees.docx"
    generate_trust_docx(trust_data, template_path=f"templates/{template}", output_path=docx_path)
    wait_for_file(docx_path, timeout=10)

    try:
        pdf_path = convert_docx_to_pdf_libreoffice(docx_path, upload_dir)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"❌ Failed to convert DOCX to PDF: {str(e)}")

    trust_data["documents"].extend([docx_path, pdf_path])

    with open(docx_path, "rb") as docx_file:
        docx_binary = docx_file.read()
    with open(pdf_path, "rb") as pdf_file:
        pdf_binary = pdf_file.read()

    try:
        conn = get_mssql_connection()
        cursor = conn.cursor()
        # Debug: log current DB and schema before insert
        cursor.execute("SELECT DB_NAME(), SCHEMA_NAME()")
        print("[DEBUG] Inserting into:", cursor.fetchone())
        # Insert only columns that exist in TrustApplication schema (now 45 columns, establishment_date and trustee4_email removed)
        cursor.execute("""
            INSERT INTO dbo.TrustApplication (
                trust_number, trust_name, full_name, id_number, email, phone_number, trust_email,
                establishment_date_1, establishment_date_2, beneficiaries,
                is_bullion_member, member_number, referrer_number,
                settlor_name, settlor_id, settlor_email,
                trustee1_name, trustee1_id, trustee1_email,
                trustee2_name, trustee2_id, trustee2_email,
                trustee3_name, trustee3_id, trustee3_email,
                trustee4_name, trustee4_id,
                owner_name, owner_id, owner_email,
                signer_name, signer_id, signer_email,
                Property_Address,
                payment_reference, payment_amount, payment_currency,
                payment_method, payment_xrp_qty, payment_xrp_trans_id,
                payment_status, trust_deed_doc_binary, trust_deed_pdf_binary,
                submitted_at, source, status, has_paid
            )
            VALUES (
                ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?,
                ?, ?, ?,
                ?, ?, ?,
                ?, ?, 
                ?, ?, ?, -- owner_name, owner_id, owner_email
                ?, ?, ?, -- signer_name, signer_id, signer_email
                ?, -- Property_Address
                ?, ?, ?,  -- payment_reference, payment_amount, payment_currency
                ?, ?, ?,  -- payment_method, payment_xrp_qty, payment_xrp_trans_id
                ?, ?, ?,  -- payment_status, trust_deed_doc_binary, trust_deed_pdf_binary
                ?, ?, ?, ? -- submitted_at, source, status, has_paid
            )
        """, (
            trust_number,                     # trust_number
            formatted_trust_name,             # trust_name
            full_name,                        # full_name
            id_number,                        # id_number
            email,                            # email
            phone_number,                     # phone_number
            trust_email,                      # trust_email
            formatted_date_1,                 # establishment_date_1
            formatted_date_2,                 # establishment_date_2
            beneficiaries,                    # beneficiaries
            is_bullion_member,                # is_bullion_member
            member_number,                    # member_number
            referrer_number,                  # referrer_number
            settlor_name,                     # settlor_name
            settlor_id,                       # settlor_id
            trust_data.get("settlor_email"),  # settlor_email
            trust_data.get("trustee1_name"),  # trustee1_name
            trust_data.get("trustee1_id"),    # trustee1_id
            trust_data.get("trustee1_email"), # trustee1_email
            trust_data.get("trustee2_name"),  # trustee2_name
            trust_data.get("trustee2_id"),    # trustee2_id
            trust_data.get("trustee2_email"), # trustee2_email
            trust_data.get("trustee3_name"),  # trustee3_name
            trust_data.get("trustee3_id"),    # trustee3_id
            trust_data.get("trustee3_email"), # trustee3_email
            trust_data.get("trustee4_name"),  # trustee4_name
            trust_data.get("trustee4_id"),    # trustee4_id
            trust_data.get("owner_name"),     # owner_name
            trust_data.get("owner_id"),       # owner_id
            trust_data.get("owner_email"),    # owner_email
            trust_data.get("signer_name"),    # signer_name
            trust_data.get("signer_id"),      # signer_id
            trust_data.get("signer_email"),   # signer_email
            trust_data.get("property_address"), # Property_Address
            None,                             # payment_reference (not provided in input)
            (trust_data.get("payment_amount_cents", 0) or 0) / 100 if trust_data.get("payment_method") != "xrp" else None, # payment_amount
            "ZAR" if trust_data.get("payment_method") != "xrp" else "XRP", # payment_currency
            trust_data.get("payment_method"), # payment_method
            trust_data.get("payment_amount_xrp") if trust_data.get("payment_method") == "xrp" else None, # payment_xrp_qty
            trust_data.get("payment_xrp_trans_id"), # payment_xrp_trans_id
            "paid" if has_paid_val else "unpaid", # payment_status
            docx_binary,                      # trust_deed_doc_binary
            pdf_binary,                       # trust_deed_pdf_binary
            trust_data["created_at"],         # submitted_at
            "web",                            # source
            "pending",                        # status
            has_paid_val                      # has_paid
        ))
        conn.commit()
        cursor.close()
        conn.close()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to insert into MSSQL: {e}")

    def  send_email_sync():
        # Parties dictionary used by admin email templates (values may be empty; template omits blank lines)
        parties = {
            "settlor_name": settlor_name,
            "settlor_email": settlor_email or "",
            "trustee1_name": trustee1_name or "",
            "trustee1_email": trustee1_email or "",
            "trustee2_name": trustee2_name or "",
            "trustee2_email": trustee2_email or "",
            "trustee3_name": trustee3_name or "",
            "trustee3_email": trustee3_email or "",
            "trustee4_name": trust_data.get("trustee4_name") or "",
            "trustee4_email": "",  # schema currently has no trustee4_email input
            "owner_name": owner_name or "",
            "owner_email": owner_email or "",
            "signer_name": signer_name or "",
            "signer_email": signer_email or "",
        }
        try:
            print(f"[DEBUG] has_paid_val: {has_paid_val}")
            if has_paid_val == "xrp":
                send_admin_email_with_attachments_xrp(
                    admin_email="info@trusthub.biz",
                    full_name=full_name,
                    trust_name=formatted_trust_name,
                    docx_path=docx_path,
                    pdf_path=pdf_path,
                    parties=parties,
                )
            elif has_paid_val in ["card", "eft"]:
                # Build trust_emails for CC (send_confirmation_email dedupes and excludes primary recipient)
                trust_emails = {
                    "email": email,
                    "trust_email": trust_email,
                    "settlor_email": settlor_email,
                    "trustee1_email": trustee1_email,
                    "trustee2_email": trustee2_email,
                    "trustee3_email": trustee3_email,
                    "owner_email": owner_email,
                    "signer_email": signer_email,
                }
                send_confirmation_email(
                    to_email=email,
                    full_name=full_name,
                    trust_name=formatted_trust_name,
                    pdf_path=pdf_path,
                    trust_emails=trust_emails,
                )
                send_admin_email_with_attachments(
                    admin_email="info@trusthub.biz",
                    trust_name=formatted_trust_name,
                    docx_path=docx_path,
                    pdf_path=pdf_path,
                    parties=parties,
                )
            else:
                print(f"[WARNING] Unknown has_paid_val received: {has_paid_val}")
        except Exception as e:
            print(f"[ERROR] Failed sending email: {e}")

    background_tasks.add_task(send_email_sync)

    return JSONResponse(
        status_code=200,
        content={
            "message": "Trust submitted successfully",
            "trust_number": trust_number,
            "document_path": pdf_path,
            "uploaded_files": file_paths
        }
    )
