from fastapi import APIRouter, HTTPException, BackgroundTasks, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel
import os
import time
from datetime import datetime, date
from typing import Optional, Tuple
import json

from database import get_mssql_connection
from docxtpl import DocxTemplate

from utils.email_sender import send_sale_cede_emails
from utils.pdf_converter import convert_docx_to_pdf_libreoffice

from security import get_current_user

router = APIRouter()


# ==========================
# Trusts.py style helpers
# ==========================

def sanitize_filename(name: str) -> str:
    import re
    return re.sub(r'[^\w\s-]', '', (name or '')).strip().replace(' ', '_')


def wait_for_file(file_path: str, timeout: int = 30, interval: float = 0.5):
    total_wait = 0
    while not os.path.exists(file_path):
        time.sleep(interval)
        total_wait += interval
        if total_wait > timeout:
            raise TimeoutError(f"File {file_path} not found after {timeout} seconds")


# ==========================
# Models
# ==========================
class SaleCedeInput(BaseModel):
    # Additional email fields for owner and signer (for notifications)
    owner_email: Optional[str] = None
    signer_email: Optional[str] = None
    # REQUIRED by DB and template merge
    trust_number: str
    trust_name: Optional[str] = None
    trust_date: Optional[str] = None  # yyyy-mm-dd (optional; if absent we’ll try fetch from DB)

    owner_name: str
    owner_id: str

    signer_name: str
    signer_id: str

    list_of_property: str

    place_of_signature: str

    date_sign: Optional[str] = None  # yyyy-mm-dd; defaults to today
    created_at: Optional[str] = None # ISO timestamp; defaults to now

    # Payment meta (optional)
    payment_method: Optional[str] = None            # 'card' | 'xrp' | etc.
    payment_amount: Optional[int] = None            # in ZAR
    payment_amount_cents: Optional[int] = None      # in cents

    # XRP-specific (optional; for crypto payments)
    xrp_amount: Optional[float] = None       # amount of XRP user sent/owes
    xrp_address: Optional[str] = None        # destination address used
    xrp_tx_hash: Optional[str] = None        # 64-char transaction hash

    # Not persisted in table but used for merge if available
    settlor_id: Optional[str] = None
    client_email: Optional[str] = None  # prefer this when emailing the generated docs

    # Establishment dates for DOCX template
    establishment_date_1: Optional[str] = None
    establishment_date_2: Optional[str] = None

    # Additional fields for richer context
    beneficiaries: Optional[str] = None
    payment_currency: Optional[str] = None
    payment_status: Optional[str] = None
    payment_timestamp: Optional[str] = None
    payment_reference: Optional[str] = None
    is_bullion_member: Optional[bool] = None
    member_number: Optional[str] = None
    referrer_number: Optional[str] = None
    phone_number: Optional[str] = None
    trust_email: Optional[str] = None
    source: Optional[str] = None
    status: Optional[str] = None
    submitted_at: Optional[str] = None
    trustee1_id: Optional[str] = None
    trustee1_name: Optional[str] = None
    trustee2_id: Optional[str] = None
    trustee2_name: Optional[str] = None
    trustee3_id: Optional[str] = None
    trustee3_name: Optional[str] = None
    trustee4_id: Optional[str] = None
    trustee4_name: Optional[str] = None
# ==========================
# Helpers
# ==========================

def _table_has_columns(conn, schema: str, table: str, columns: list[str]) -> bool:
    try:
        cur = conn.cursor()
        q = (
            "SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS "
            "WHERE TABLE_SCHEMA = ? AND TABLE_NAME = ?"
        )
        cur.execute(q, (schema, table))
        existing = {row[0].lower() for row in cur.fetchall()}
        cur.close()
        return all(col.lower() in existing for col in columns)
    except Exception:
        return False


# ==========================
# Helpers
# ==========================

def _pick_template() -> str:
    # 1) Environment variable override (e.g., SALE_CEDE_TEMPLATE_PATH)
    env_path = os.getenv("SALE_CEDE_TEMPLATE_PATH")
    if env_path and os.path.exists(env_path):
        return env_path

    # 2) Absolute path provided by developer
    abs_path = "/Users/user/PycharmProjects/hongkongbackend/templates/Agreement of Sale and Cession of Claims and Rights.docx"
    if os.path.exists(abs_path):
        return abs_path

    # 3) Project-relative defaults
    primary = "Agreement of Sale and Cession of Claims and Rights.docx"
    fallback = os.path.join("templates", "Agreement of Sale and Cession of Claims and Rights.docx")
    if os.path.exists(primary):
        return primary
    if os.path.exists(fallback):
        return fallback

    raise HTTPException(status_code=500, detail=(
        "Template not found. Checked: SALE_CEDE_TEMPLATE_PATH, '" + abs_path + "', '" + primary + "', and '" + fallback + "'"
    ))


def _prefer_trust_meta(trust_number: str, given_trust_name: Optional[str]) -> tuple[str, Optional[str], Optional[str], str, str]:
    """Return (trust_name, trust_date, email, establishment_date_1, establishment_date_2) from TrustApplication if present.
    trust_date prefers establishment_date_2 then establishment_date_1.
    establishment_date_1 and establishment_date_2 are returned as strings (formatted if possible).
    """
    trust_name = (given_trust_name or '').strip()
    email: Optional[str] = None
    establishment_date_1 = ''
    establishment_date_2 = ''
    try:
        conn = get_mssql_connection()
        cur = conn.cursor()
        cur.execute(
            """
            SELECT trust_name, email, establishment_date_2, establishment_date_1
            FROM TrustApplication
            WHERE trust_number = ?
            """,
            (trust_number,)
        )
        row = cur.fetchone()
        cur.close(); conn.close()
        if row:
            if not trust_name:
                trust_name = row[0] or trust_name
            email = row[1]
            # establishment_date_1 (row[3]), establishment_date_2 (row[2])
            establishment_date_1_val = row[3]
            establishment_date_2_val = row[2]
            if hasattr(establishment_date_1_val, 'strftime'):
                establishment_date_1 = establishment_date_1_val.strftime('%-d %B %Y')
            elif establishment_date_1_val:
                try:
                    establishment_date_1 = datetime.strptime(establishment_date_1_val, '%Y-%m-%d').strftime('%-d %B %Y')
                except Exception:
                    establishment_date_1 = str(establishment_date_1_val)
            else:
                establishment_date_1 = ''
            if hasattr(establishment_date_2_val, 'strftime'):
                establishment_date_2 = establishment_date_2_val.strftime('%-d %B %Y')
            elif establishment_date_2_val:
                try:
                    establishment_date_2 = datetime.strptime(establishment_date_2_val, '%Y-%m-%d').strftime('%-d %B %Y')
                except Exception:
                    establishment_date_2 = str(establishment_date_2_val)
            else:
                establishment_date_2 = ''
    except Exception:
        pass
    return trust_name, email, str(establishment_date_1 or ''), str(establishment_date_2 or '')


from typing import Optional, Tuple

def _render_docx(context: dict, out_dir: Optional[str] = None) -> Tuple[str, Optional[str]]:
    template_path = _pick_template()

    trust_name = context.get('trust_name') or ''
    trust_number = context.get('trust_number') or ''
    safe_folder = sanitize_filename(trust_name or trust_number or 'agreement')
    base_dir = out_dir or os.path.join('uploads', safe_folder)
    os.makedirs(base_dir, exist_ok=True)

    # Render DOCX
    doc = DocxTemplate(template_path)
    # Format trust_date for template if it's a YYYY-MM-DD string
    if 'trust_date' in context:
        try:
            context['trust_date'] = datetime.strptime(context['trust_date'], '%Y-%m-%d').strftime('%-d %B %Y')
        except Exception:
            pass
    doc.render(context)

    docx_name = f"{safe_folder}_SALE_CEDE.docx"
    output_docx = os.path.join(base_dir, docx_name)
    doc.save(output_docx)

    # Ensure file is written before conversion
    wait_for_file(output_docx, timeout=15)

    # Convert to PDF using the same util as trusts.py
    try:
        output_pdf = convert_docx_to_pdf_libreoffice(output_docx, base_dir)
    except Exception:
        output_pdf = None

    return output_docx, output_pdf


# ==========================
# Endpoint
# ==========================
@router.post('/agreements/sale-cede/generate')
async def generate_sale_cede_agreement(
    payload: SaleCedeInput,
    background_tasks: BackgroundTasks,
    user: str = Depends(get_current_user),
):
    """Generate DOCX/PDF for Sale & Cede and insert a row into HKFT_Master.dbo.SaleCedeAgree."""
    # Helper to convert string to date object
    def to_date(val):
        if not val:
            return None
        if isinstance(val, date) and not isinstance(val, datetime):
            return val
        if isinstance(val, datetime):
            return val.date()
        try:
            # Try full datetime string, e.g., "2025-07-27 00:00:00.0000000"
            return datetime.strptime(val[:10], "%Y-%m-%d").date()
        except Exception:
            try:
                return datetime.strptime(val, "%Y-%m-%d").date()
            except Exception:
                return None
    # 1) Normalize timings
    now = datetime.utcnow()
    # Compute date_sign_dt (date object)
    raw_date_sign = payload.date_sign or None
    if raw_date_sign:
        date_sign_dt = to_date(raw_date_sign)
        if not date_sign_dt:
            try:
                date_sign_dt = datetime.strptime(raw_date_sign, '%d %B %Y').date()
            except Exception:
                raise HTTPException(status_code=400, detail=f"Invalid date_sign format: {raw_date_sign}")
    else:
        date_sign_dt = now.date()
    # Compute created_at_dt (datetime object)
    created_at_iso = payload.created_at or now.isoformat()
    try:
        created_at_dt = datetime.fromisoformat(created_at_iso)
    except Exception:
        created_at_dt = now

    # 2) Pull trust meta if missing
    trust_name, email, establishment_date_1, establishment_date_2 = _prefer_trust_meta(payload.trust_number, payload.trust_name)
    to_email = payload.client_email or email
    # Set establishment_date_1 and establishment_date_2 from DB if missing in payload
    if not payload.establishment_date_1:
        payload.establishment_date_1 = establishment_date_1
    if not payload.establishment_date_2:
        payload.establishment_date_2 = establishment_date_2
    # Prepare est_date_1 as date object (for DB insert)
    est_date_1 = to_date(payload.establishment_date_1 or establishment_date_1)

    # 2a) If XRP indicators exist but method not set, default to 'xrp'
    if (payload.xrp_amount or payload.xrp_tx_hash) and not (payload.payment_method or '').strip():
        payload.payment_method = 'xrp'

    # 3) Insert DB row
    try:
        conn = get_mssql_connection()
        cur = conn.cursor()

        schema = 'HKFT_Master'
        table = 'SaleCedeAgree'
        # Actual schema columns, in order:
        # trust_number, trust_name, establishment_date_1, owner_name, owner_id, signer_name, signer_id,
        # list_of_property, place_of_signature, date_sign, created_at, payment_amount, payment_method, owner_email, signer_email
        cur.execute(
            f"""
            INSERT INTO {schema}.dbo.{table} (
                trust_number, trust_name, establishment_date_1,
                owner_name, owner_id,
                signer_name, signer_id,
                list_of_property,
                place_of_signature, date_sign,
                created_at,
                payment_amount, payment_method,
                owner_email, signer_email
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                payload.trust_number,
                trust_name,
                est_date_1,
                payload.owner_name,
                payload.owner_id,
                payload.signer_name,
                payload.signer_id,
                payload.list_of_property,
                payload.place_of_signature,
                date_sign_dt,
                created_at_dt,
                str(payload.payment_amount or ''),
                payload.payment_method or '',
                payload.owner_email or '',
                payload.signer_email or '',
            )
        )
        conn.commit()
        cur.close(); conn.close()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database error while inserting SaleCedeAgree: {e}")

    # 4) Build DOCX context and render
    # Format list_of_property as bullet list string for DOCX template
    raw_list = payload.list_of_property or ''
    if raw_list.strip():
        import re
        items = [item.strip() for item in re.split(r'[;,]', raw_list) if item.strip()]
        formatted_list = '• ' + '\n• '.join(items) if items else ''
    else:
        formatted_list = ''

    context = {
        'trust_number': payload.trust_number,
        'trust_name': trust_name,
        'owner_name': payload.owner_name,
        'owner_id': payload.owner_id,
        'signer_name': payload.signer_name,
        'signer_id': payload.signer_id,
        'xrp_amount': payload.xrp_amount,
        'xrp_address': payload.xrp_address,
        'xrp_tx_hash': payload.xrp_tx_hash,
        'list_of_property': formatted_list,
        'place_of_signature': payload.place_of_signature,
        'date_sign': payload.date_sign,
        'payment_method': payload.payment_method or '',
        'payment_amount': (payload.payment_amount if payload.payment_amount is not None else (int(payload.payment_amount_cents or 0) // 100)),
        'payment_amount_cents': (payload.payment_amount_cents if payload.payment_amount_cents is not None else ((payload.payment_amount or 0) * 100)),
        'settlor_id': payload.settlor_id or '',
        # Fall back to the values from DB if payload fields are missing
        'establishment_date_1': payload.establishment_date_1 or establishment_date_1 or '',
        'establishment_date_2': payload.establishment_date_2 or establishment_date_2 or '',
        # Additional context fields
        'client_email': to_email or '',
        'created_at': created_at_iso,
        'payment_currency': payload.payment_currency or '',
        'payment_status': payload.payment_status or '',
        'payment_timestamp': payload.payment_timestamp or '',
        'payment_reference': payload.payment_reference or '',
        'is_bullion_member': payload.is_bullion_member if hasattr(payload, 'is_bullion_member') else False,
        'member_number': payload.member_number or '',
        'referrer_number': payload.referrer_number or '',
        'phone_number': payload.phone_number or '',
        'trust_email': payload.trust_email or '',
        'source': payload.source or '',
        'status': payload.status or '',
        'submitted_at': payload.submitted_at or '',
        'beneficiaries': payload.beneficiaries or '',
        'trustee1_name': payload.trustee1_name or '',
        'trustee1_id': payload.trustee1_id or '',
        'trustee2_name': payload.trustee2_name or '',
        'trustee2_id': payload.trustee2_id or '',
        'trustee3_name': payload.trustee3_name or '',
        'trustee3_id': payload.trustee3_id or '',
        'trustee4_name': payload.trustee4_name or '',
        'trustee4_id': payload.trustee4_id or '',
        # New: include owner and signer emails in context for downstream use
        'owner_email': payload.owner_email or '',
        'signer_email': payload.signer_email or '',
    }

    output_docx, output_pdf = _render_docx(context)

    # Persist payment info into SaleCedePayments table
    try:
        session_id = f"salecede_{datetime.utcnow().strftime('%Y%m%d%H%M%S%f')}"
        trust_number = payload.trust_number
        payment_amount_cents = int((context.get('payment_amount_cents') or 0))
        payment_amount = int(context.get('payment_amount') or (payment_amount_cents // 100))
        payment_method = (context.get('payment_method') or '').strip()
        xrp_tx_hash = (payload.xrp_tx_hash or '') if hasattr(payload, 'xrp_tx_hash') else ''
        xrp_amount = payload.xrp_amount
        xrp_address = payload.xrp_address

        conn = get_mssql_connection()
        cur = conn.cursor()
        schema = 'dbo'
        table = 'SaleCedePayments'

        # Check available columns to avoid insert failures on older schemas
        has_pay_cols = _table_has_columns(conn, schema, table, ['payment_method', 'payment_amount'])
        has_xrp_cols = _table_has_columns(conn, schema, table, ['xrp_tx_hash', 'xrp_amount', 'xrp_address'])

        if has_pay_cols and has_xrp_cols:
            cur.execute(
                f"""
                INSERT INTO {schema}.{table} (id, trust_number, amount_cents, status, yoco_ref, created_at, context_json, payment_method, payment_amount, xrp_tx_hash, xrp_amount, xrp_address)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    trust_number,
                    int(payment_amount_cents),
                    "pending",
                    None,
                    datetime.utcnow(),
                    json.dumps(context),
                    payment_method,
                    payment_amount,
                    xrp_tx_hash,
                    xrp_amount,
                    xrp_address,
                ),
            )
        elif has_pay_cols:
            cur.execute(
                f"""
                INSERT INTO {schema}.{table} (id, trust_number, amount_cents, status, yoco_ref, created_at, context_json, payment_method, payment_amount)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    trust_number,
                    int(payment_amount_cents),
                    "pending",
                    None,
                    datetime.utcnow(),
                    json.dumps(context),
                    payment_method,
                    payment_amount,
                ),
            )
        else:
            cur.execute(
                f"""
                INSERT INTO {schema}.{table} (id, trust_number, amount_cents, status, yoco_ref, created_at, context_json)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    trust_number,
                    int(payment_amount_cents),
                    "pending",
                    None,
                    datetime.utcnow(),
                    json.dumps(context),
                ),
            )

        conn.commit()
        cur.close(); conn.close()
    except Exception as e:
        print(f"[WARN] Failed to insert SaleCedePayments record: {e}")

    # 5) Email the generated documents: send ONLY ONE email to the client (no CC/BCC).
    # Admin is referenced inside the template data and receives a separate admin-only email via the util.

    # Parties are for template rendering only; do not include emails to avoid accidental CC via templates
    parties = {
        'owner_name': payload.owner_name or '',
        'signer_name': payload.signer_name or '',
        'trustee1_name': payload.trustee1_name or '',
        'trustee2_name': payload.trustee2_name or '',
        'trustee3_name': payload.trustee3_name or '',
        'trustee4_name': payload.trustee4_name or '',
    }

    # Choose a single client recipient in priority order
    recipient_email = (
        payload.client_email
        or payload.owner_email
        or payload.signer_email
        or to_email
    )

    # Friendly name for personalization
    def _norm(s: Optional[str]):
        return (s or '').strip().lower()

    recipient_name = (
        (payload.owner_name if recipient_email and _norm(recipient_email) == _norm(payload.owner_email) else None)
        or (payload.signer_name if recipient_email and _norm(recipient_email) == _norm(payload.signer_email) else None)
        or payload.owner_name
        or payload.signer_name
        or (trust_name or 'Client')
    )

    # Trust emails for template content only (NOT routing)
    trust_emails = {
        'email': recipient_email or '',
        'admin_email': 'info@trusthub.biz',
    }

    def _send_emails():
        try:
            if recipient_email:
                send_sale_cede_emails(
                    client_email=recipient_email,
                    owner_full_name=recipient_name,
                    trust_name=trust_name,
                    docx_path=output_docx,
                    pdf_path=output_pdf,
                    admin_email='info@trusthub.biz',
                    parties=parties,
                    trust_emails=trust_emails,
                )
        except Exception as e:
            print(f"[WARN] Sale & Cede email send failed: {e}")

    background_tasks.add_task(_send_emails)

    # 6) Response: Only return a success message and trust/payment details, not file paths
    return JSONResponse(content={
        'message': 'Sale & Cede Agreement generated successfully',
        'trust_number': payload.trust_number,
        'trust_name': trust_name,
        'payment_method': payload.payment_method or '',
        'payment_amount': (payload.payment_amount if payload.payment_amount is not None else (int(payload.payment_amount_cents or 0) // 100)),
        'payment_amount_cents': (payload.payment_amount_cents if payload.payment_amount_cents is not None else ((payload.payment_amount or 0) * 100)),
        'xrp_amount': payload.xrp_amount,
        'xrp_address': payload.xrp_address,
        'xrp_tx_hash': payload.xrp_tx_hash,
    })

# ==========================
# Trust details endpoint
# ==========================

# Return all fields from TrustApplication by trust_number
@router.get('/trusts/{trust_number}')
async def get_trust_details(trust_number: str, user: str = Depends(get_current_user)):
    """Fetch full trust application data by trust_number."""
    try:
        conn = get_mssql_connection()
        cur = conn.cursor()
        cur.execute("SELECT * FROM TrustApplication WHERE trust_number = ?", (trust_number,))
        row = cur.fetchone()
        columns = [col[0] for col in cur.description]
        cur.close(); conn.close()

        if not row:
            raise HTTPException(status_code=404, detail="Trust not found")

        trust_data = dict(zip(columns, row))
        return JSONResponse(content=trust_data)

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching trust: {e}")