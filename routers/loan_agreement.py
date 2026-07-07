# loan_agreement.py
from typing import List, Optional
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
import pyodbc
import logging
from datetime import date
from fastapi.responses import StreamingResponse
from docxtpl import DocxTemplate
from jinja2.exceptions import UndefinedError
import io
from database import get_mssql_connection
from pathlib import Path
import os
import re
import time
import zipfile

logger = logging.getLogger(__name__)

# Helpers to mirror trust.py behaviour for file-based DOCX generation

def sanitize_filename(name: str) -> str:
    return re.sub(r'[^\w\s-]', '', name).strip().replace(' ', '_')




def wait_for_file(file_path: str, timeout: int = 30, interval: float = 0.5):
    total_wait = 0.0
    while not Path(file_path).exists():
        time.sleep(interval)
        total_wait += interval
        if total_wait > timeout:
            raise TimeoutError(f"File {file_path} not found after {timeout} seconds")

# Ordinal date helper (e.g., "15th of August 2025")
def format_long_ordinal(d: date) -> str:
    day = d.day
    # 11,12,13 are special cases
    if 11 <= day % 100 <= 13:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")
    month = d.strftime("%B")
    year = d.strftime("%Y")
    return f"{day}{suffix} of {month} {year}"

# Diagnostics helpers

def template_is_valid_docx(path: str) -> bool:
    p = Path(path)
    if not p.exists():
        return False
    try:
        with open(p, 'rb') as f:
            data = f.read(4)
        # Quick ZIP signature check; fuller check is in zipfile.is_zipfile
        if data != b'PK\x03\x04':
            return False
        return zipfile.is_zipfile(str(p))
    except Exception:
        return False


def can_write_to_dir(directory: Path) -> bool:
    try:
        directory.mkdir(parents=True, exist_ok=True)
        test_file = directory / "__write_test__.tmp"
        test_file.write_text("ok")
        test_file.unlink(missing_ok=True)
        return True
    except Exception:
        return False

# Resolve template path robustly (works in Docker and local dev)
_DEFAULT_TEMPLATE = "_Loan_Agreement_Template.docx"
_CANDIDATE_DIRS = [
    Path(__file__).resolve().parent / "templates",
    Path(__file__).resolve().parent.parent / "templates",
    Path("/app/templates"),
    Path("/app/routers/templates"),
    Path("templates"),
]
ENV_TEMPLATE = os.getenv("LOAN_TEMPLATE_PATH")
if ENV_TEMPLATE:
    TEMPLATE_PATH = ENV_TEMPLATE
else:
    TEMPLATE_PATH = None
    for d in _CANDIDATE_DIRS:
        p = d / _DEFAULT_TEMPLATE
        if p.exists():
            TEMPLATE_PATH = str(p)
            break
    if TEMPLATE_PATH is None:
        # Fall back to a reasonable default but let render step raise a helpful error
        TEMPLATE_PATH = str(_CANDIDATE_DIRS[0] / _DEFAULT_TEMPLATE)

def get_conn():
    # Reuse the central DB connector (database.py)
    conn = get_mssql_connection()
    try:
        # Set a statement timeout if supported; otherwise just return the connection
        # pyodbc doesn't expose a universal per-connection timeout beyond connect timeout,
        # but we keep this wrapper in case you later swap drivers.
        return conn
    except Exception:
        # If anything odd happens, ensure we close before re-raising
        try:
            conn.close()
        except Exception:
            pass
        raise

def render_loan_agreement_docx(body: "LoanAgreementCreate", loan_id: Optional[int] = None) -> bytes:
    items = (body.Items or [])[:6] + [LoanItem()] * (6 - len(body.Items or []))

    def fmt(val): return f"{val:,.2f}" if val is not None else ""

    context = {
        "loan_agreement_id": loan_id or "",
        "Loan_Date": body.Loan_Date.strftime("%d %B %Y"),
        "Lender_Name": body.Lender_Name,
        "Lender_ID": body.Lender_ID,
        "trust_name": body.Trust_Name,
        "trust_number": body.Trust_Number,
        "Trustee_Name": body.Trustee_Name,
        "Country": body.Country,
        "Witness_Name": body.Witness_Name or "",
        "currency": body.CurrencyCode,
        "sum_of_loan_item_values": fmt(sum(i.Val or 0 for i in items)),
        "total_value_of_loan": f"{body.CurrencyCode} {fmt(sum(i.Val or 0 for i in items))}",
        "Loan_Item_1_Description": items[0].Desc or "",
        "Loan_Item_1_Type": items[0].Type or "",
        "Loan_Item_1_Value": fmt(items[0].Val),
        "Loan_Item_2_Description": items[1].Desc or "",
        "Loan_Item_2_Type": items[1].Type or "",
        "Loan_Item_2_Value": fmt(items[1].Val),
        "Loan_Item_3_Description": items[2].Desc or "",
        "Loan_Item_3_Type": items[2].Type or "",
        "Loan_Item_3_Value": fmt(items[2].Val),
        "Item4_Desc": items[3].Desc or "", "Item4_Type": items[3].Type or "", "Item4_Val": fmt(items[3].Val),
        "Item5_Desc": items[4].Desc or "", "Item5_Type": items[4].Type or "", "Item5_Val": fmt(items[4].Val),
        "Item6_Desc": items[5].Desc or "", "Item6_Type": items[5].Type or "", "Item6_Val": fmt(items[5].Val),
    }

    try:
        if not Path(TEMPLATE_PATH).exists():
            raise HTTPException(status_code=500, detail=f"Template not found at {TEMPLATE_PATH}")

        doc = DocxTemplate(TEMPLATE_PATH)
        doc.render(context)
        buffer = io.BytesIO()
        doc.save(buffer)
        buffer.seek(0)
        return buffer.read()
    except UndefinedError as e:
        logger.exception("Template variable missing while rendering loan agreement: %s", e)
        raise HTTPException(status_code=500, detail=f"Template variable missing: {e}")
    except Exception as e:
        logger.exception("Error rendering loan agreement DOCX: %s", e)
        raise HTTPException(status_code=500, detail=f"Failed to render loan agreement document: {e}")

# -------- Schemas ----------
class TrustCore(BaseModel):
    trust_number: str
    trust_name: Optional[str] = None
    full_name: Optional[str] = None
    id_number: Optional[str] = None
    email: Optional[str] = None
    phone_number: Optional[str] = None
    trust_email: Optional[str] = None
    member_number: Optional[str] = None
    referrer_number: Optional[str] = None
    submitted_at: Optional[str] = None
    status: Optional[str] = None
    payment_status: Optional[str] = None
    payment_method: Optional[str] = None
    payment_amount: Optional[float] = None
    payment_currency: Optional[str] = None
    payment_timestamp: Optional[str] = None

class TrusteeRow(BaseModel):
    Trustee_Seq: int
    Trustee_Name: str
    Trustee_ID: Optional[str] = None

class TrustLookupResponse(BaseModel):
    core: TrustCore
    trustees: List[TrusteeRow] = []

class LoanItem(BaseModel):
    Desc: Optional[str] = None
    Type: Optional[str] = None
    Val: Optional[float] = None

class LoanAgreementCreate(BaseModel):
    Trust_Number: str
    User_Id: Optional[str] = None
    Trust_Name: str
    Country: str
    Lender_Name: str
    Lender_ID: str
    Trustee_Name: str           # signing trustee
    Witness_Name: Optional[str] = None
    Loan_Date: date
    CurrencyCode: str
    Items: List[LoanItem] = Field(default_factory=list)

class CreateLoanAgreementResponse(BaseModel):
    Loan_Agreement_ID: int

# -------- Router ----------
router = APIRouter(prefix="/api", tags=["Loan Agreements"])

@router.get("/trusts/{trust_number}", response_model=TrustLookupResponse)
def get_trust(trust_number: str, user_id: Optional[str] = Query(default=None)):
    """
    Calls dbo.sp_GetTrustFromApplication to fetch:
      - Trust core (first result set)
      - Normalized trustees (second result set)
    """
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("{CALL dbo.sp_GetTrustFromApplication(?,?)}", (trust_number, user_id))
                row = cur.fetchone()
                if not row:
                    raise HTTPException(status_code=404, detail="Trust application not found or not authorised.")

                columns = [d[0] for d in cur.description]
                core = TrustCore(**dict(zip(columns, row)))

                trustees: List[TrusteeRow] = []
                if cur.nextset():
                    for trow in cur.fetchall():
                        trustees.append(TrusteeRow(
                            Trustee_Seq=int(getattr(trow, "Trustee_Seq")),
                            Trustee_Name=str(getattr(trow, "Trustee_Name")),
                            Trustee_ID=getattr(trow, "Trustee_ID", None)
                        ))

                return TrustLookupResponse(core=core, trustees=trustees)
    except pyodbc.Error as e:
        logger.exception("Database error")
        raise HTTPException(status_code=400, detail="Database error while processing request.")

@router.post("/loan-agreements", response_model=CreateLoanAgreementResponse)
def create_loan_agreement(body: LoanAgreementCreate):
    """
    Calls dbo.sp_CreateLoanAgreement_FromApp to insert a new agreement.
    Fans out up to 6 items into the proc parameters.
    """
    items = (body.Items or [])[:6] + [LoanItem()] * (6 - len(body.Items or []))
    if not any(((i.Val or 0) > 0) for i in items):
        raise HTTPException(
            status_code=422,
            detail={
                "message": "At least one loan item value must be greater than zero.",
                "item_values": [i.Val for i in items]
            }
        )
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                params = (
                    # Match proc signature exactly (Option A):
                    # @Lender_Name, @Lender_ID, @Trust_Name, @Trust_Number,
                    # @Trustee_Name, @Country, @Witness_Name, @Loan_Date, @CurrencyCode,
                    # then Item1..Item6 (Desc, Type, Val)
                    body.Lender_Name,
                    body.Lender_ID,
                    body.Trust_Name,
                    body.Trust_Number,
                    body.Trustee_Name,
                    body.Country,
                    body.Witness_Name,
                    body.Loan_Date.isoformat(),
                    body.CurrencyCode,
                    # Item1..Item6 triples
                    items[0].Desc, items[0].Type, items[0].Val,
                    items[1].Desc, items[1].Type, items[1].Val,
                    items[2].Desc, items[2].Type, items[2].Val,
                    items[3].Desc, items[3].Type, items[3].Val,
                    items[4].Desc, items[4].Type, items[4].Val,
                    items[5].Desc, items[5].Type, items[5].Val,
                )
                logger.debug("Loan items values: %s", [i.Val for i in items])
                placeholders = ",".join(["?"] * len(params))
                cur.execute(
                    f"{{CALL dbo.sp_CreateLoanAgreement_FromApp({placeholders})}}",
                    params
                )
                row = cur.fetchone()
                if not row:
                    raise HTTPException(status_code=500, detail="No ID returned from create procedure.")
                conn.commit()

                return CreateLoanAgreementResponse(Loan_Agreement_ID=int(row.Loan_Agreement_ID))
    except pyodbc.Error as e:
        logger.exception("Database error")
        raise HTTPException(status_code=400, detail="Database error while processing request.")

@router.post("/loan-agreements/create-and-docx")
def create_and_generate_docx(body: LoanAgreementCreate):
    """Insert a new loan agreement, then render and return the DOCX with the created ID."""
    # Reuse the create logic to insert and obtain the new ID
    items = (body.Items or [])[:6] + [LoanItem()] * (6 - len(body.Items or []))
    if not any(((i.Val or 0) > 0) for i in items):
        raise HTTPException(
            status_code=422,
            detail={
                "message": "At least one loan item value must be greater than zero.",
                "item_values": [i.Val for i in items]
            }
        )
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                params = (
                    body.Lender_Name,
                    body.Lender_ID,
                    body.Trust_Name,
                    body.Trust_Number,
                    body.Trustee_Name,
                    body.Country,
                    body.Witness_Name,
                    body.Loan_Date.isoformat(),
                    body.CurrencyCode,
                    items[0].Desc, items[0].Type, items[0].Val,
                    items[1].Desc, items[1].Type, items[1].Val,
                    items[2].Desc, items[2].Type, items[2].Val,
                    items[3].Desc, items[3].Type, items[3].Val,
                    items[4].Desc, items[4].Type, items[4].Val,
                    items[5].Desc, items[5].Type, items[5].Val,
                )
                placeholders = ",".join(["?"] * len(params))
                cur.execute(f"{{CALL dbo.sp_CreateLoanAgreement_FromApp({placeholders})}}", params)
                row = cur.fetchone()
                if not row:
                    raise HTTPException(status_code=500, detail="No ID returned from create procedure.")
                new_id = int(row.Loan_Agreement_ID)
                conn.commit()
    except pyodbc.Error:
        logger.exception("Database error during create-and-docx")
        raise HTTPException(status_code=400, detail="Database error while processing request.")

    # Now render the document including the created ID
    doc_bytes = render_loan_agreement_docx(body, loan_id=new_id)
    filename = f"Loan_Agreement_{body.Trust_Number.replace('/', '-')}.docx"
    headers = {
        "Content-Disposition": f"attachment; filename=\"{filename}\"",
        "X-Docx-Size": str(len(doc_bytes)),
    }
    return StreamingResponse(
        io.BytesIO(doc_bytes),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers=headers,
    )


@router.get("/loan-agreements/docx/diagnostics")
def docx_diagnostics():
    safe_trust = sanitize_filename("diagnostic")
    base_dir = Path(os.getenv("DOCX_OUT_DIR", "/tmp"))
    out_dir = base_dir / "uploads" / "LoanAgreements" / safe_trust
    info = {
        "template_path": TEMPLATE_PATH,
        "template_exists": Path(TEMPLATE_PATH).exists(),
        "template_is_docx": template_is_valid_docx(TEMPLATE_PATH),
        "docx_out_base": str(base_dir),
        "out_dir": str(out_dir),
        "can_write_out_dir": can_write_to_dir(out_dir),
        "cwd": str(Path.cwd()),
        "env": {
            "LOAN_TEMPLATE_PATH": os.getenv("LOAN_TEMPLATE_PATH"),
            "DOCX_OUT_DIR": os.getenv("DOCX_OUT_DIR"),
        },
    }
    return info


@router.post("/loan-agreements/docx")
def generate_loan_agreement_docx(body: LoanAgreementCreate):
    # Render the document using the provided payload (does not insert into DB)
    doc_bytes = render_loan_agreement_docx(body, loan_id=None)
    filename = f"Loan_Agreement_{body.Trust_Number.replace('/', '-')}.docx"
    headers = {
        "Content-Disposition": f"attachment; filename=\"{filename}\"",
        "X-Docx-Size": str(len(doc_bytes)),
    }
    return StreamingResponse(
        io.BytesIO(doc_bytes),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers=headers,
    )