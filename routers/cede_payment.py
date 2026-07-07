from __future__ import annotations

from typing import Optional, Dict

import os
import uuid
import httpx
import json
from datetime import datetime
from database import get_mssql_connection
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from dotenv import load_dotenv
import hmac
import hashlib

load_dotenv()

router = APIRouter(prefix="/cede")

YOCO_SECRET_KEY = os.getenv("YOCO_SECRET_KEY")

TABLE_SQL = """
IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'SaleCedePayments' AND type = 'U')
BEGIN
    CREATE TABLE [dbo].[SaleCedePayments](
        [id]            NVARCHAR(64) NOT NULL PRIMARY KEY,
        [trust_number]  NVARCHAR(128) NULL,
        [amount_cents]  INT NOT NULL,
        [status]        NVARCHAR(32) NOT NULL,
        [yoco_ref]      NVARCHAR(256) NULL,
        [created_at]    DATETIME2 NOT NULL,
        [updated_at]    DATETIME2 NULL,
        [context_json]  NVARCHAR(MAX) NULL
    );
END
"""

def ensure_payments_table():
    try:
        conn = get_mssql_connection()
        cur = conn.cursor()
        cur.execute(TABLE_SQL)
        conn.commit()
        cur.close(); conn.close()
    except Exception as e:
        # Do not hard-fail if we cannot create; subsequent INSERT will error with a clearer message
        print(f"[WARN] ensure_payments_table failed: {e}")


# Optionally add flat columns if your DB has been migrated to store them
ADD_COLS_SQL = """
IF COL_LENGTH('dbo.SaleCedePayments','payment_method') IS NULL
  ALTER TABLE dbo.SaleCedePayments ADD payment_method NVARCHAR(20) NULL;
IF COL_LENGTH('dbo.SaleCedePayments','payment_amount_cents') IS NULL
  ALTER TABLE dbo.SaleCedePayments ADD payment_amount_cents INT NULL;
IF COL_LENGTH('dbo.SaleCedePayments','xrp_amount') IS NULL
  ALTER TABLE dbo.SaleCedePayments ADD xrp_amount DECIMAL(18,8) NULL;
IF COL_LENGTH('dbo.SaleCedePayments','xrp_address') IS NULL
  ALTER TABLE dbo.SaleCedePayments ADD xrp_address VARCHAR(64) NULL;
IF COL_LENGTH('dbo.SaleCedePayments','xrp_tx_hash') IS NULL
  ALTER TABLE dbo.SaleCedePayments ADD xrp_tx_hash CHAR(64) NULL;
"""

def ensure_flat_columns():
    try:
        conn = get_mssql_connection()
        cur = conn.cursor()
        cur.execute(ADD_COLS_SQL)
        conn.commit()
        cur.close(); conn.close()
    except Exception as e:
        # soft-fail; table may already have these or user may not want them
        print(f"[WARN] ensure_flat_columns failed: {e}")


def sync_flat_columns(conn, row_id: str, ctx: dict):
    """Populate flat columns from context_json if those columns exist.
    This builds an UPDATE only with columns that actually exist to avoid SQL errors.
    """
    # probe which columns exist
    cur = conn.cursor()
    cur.execute("""
        SELECT name FROM sys.columns WHERE object_id = OBJECT_ID('dbo.SaleCedePayments')
          AND name IN ('payment_method','payment_amount_cents','xrp_amount','xrp_address','xrp_tx_hash')
    """)
    cols = {r[0] for r in cur.fetchall()}

    sets = []
    params = []
    if 'payment_method' in cols:
        sets.append("payment_method = ?")
        params.append(ctx.get('payment_method'))
    if 'payment_amount_cents' in cols:
        sets.append("payment_amount_cents = ?")
        params.append(int(ctx.get('payment_amount_cents') or 0))
    if 'xrp_amount' in cols:
        sets.append("xrp_amount = ?")
        xrp_amt = ctx.get('xrp_amount')
        params.append(float(xrp_amt) if xrp_amt is not None else None)
    if 'xrp_address' in cols:
        sets.append("xrp_address = ?")
        params.append(ctx.get('xrp_address'))
    if 'xrp_tx_hash' in cols:
        sets.append("xrp_tx_hash = ?")
        params.append(ctx.get('xrp_tx_hash'))

    if sets:
        sql = f"UPDATE dbo.SaleCedePayments SET {', '.join(sets)}, updated_at = ? WHERE id = ?"
        params.append(datetime.utcnow())
        params.append(row_id)
        cur.execute(sql, tuple(params))
        conn.commit()
    cur.close()


class CedePaymentSessionRequest(BaseModel):
    amount_cents: int
    trust_data: dict            # trust record from lookup (should include email, trust_number, etc.)
    sale_cede_context: Optional[Dict] = None  # the agreement payload (owner/signer/witness/etc.)
    payment_method: Optional[str] = None


@router.post("/payment-session")
async def create_cede_payment_session(
    payload: CedePaymentSessionRequest,
):
    """Create a Yoco checkout for the Sale & Cede Agreement.

    - Stores a record in Mongo (sale_cede_collection) with flow metadata
    - Creates a Yoco checkout and returns `redirectUrl`
    """
    ensure_payments_table()
    ensure_flat_columns()

    # 1) Generate a session ID
    session_id = str(uuid.uuid4())

    sale_cede_context = payload.sale_cede_context.copy() if payload.sale_cede_context else {}
    # Ensure trust_number in sale_cede_context
    if "trust_number" not in sale_cede_context:
        trust_num = payload.trust_data.get("trust_number") or payload.trust_data.get("trustNumber")
        if trust_num:
            sale_cede_context["trust_number"] = trust_num

    # XRP passthrough from sale_cede_context (if user chose crypto flow)
    xrp_amount  = sale_cede_context.get("xrp_amount")
    xrp_address = sale_cede_context.get("xrp_address")
    xrp_tx_hash = sale_cede_context.get("xrp_tx_hash")

    # Decide payment_method with XRP auto-detection if not explicitly set
    computed_method = (payload.payment_method or sale_cede_context.get("payment_method") or "").strip()
    if not computed_method and (xrp_amount or xrp_tx_hash):
        computed_method = "xrp"
    if not computed_method:
        computed_method = "card"

    # Prepare context dict
    context = {
        "trust_data": payload.trust_data,
        "sale_cede_context": sale_cede_context,
        "flow": "sale_cede",
        "payment_method": computed_method,
        "payment_amount_cents": payload.amount_cents if "payment_amount_cents" not in sale_cede_context else sale_cede_context.get("payment_amount_cents"),
        "payment_amount": (payload.amount_cents // 100) if "payment_amount" not in sale_cede_context else sale_cede_context.get("payment_amount"),
        # XRP (optional)
        "xrp_amount": xrp_amount,
        "xrp_address": xrp_address,
        "xrp_tx_hash": xrp_tx_hash,
    }

    # 1b) Persist pending session in MSSQL
    try:
        conn = get_mssql_connection()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO dbo.SaleCedePayments (id, trust_number, amount_cents, status, yoco_ref, created_at, context_json)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session_id,
                payload.trust_data.get("trust_number") or payload.trust_data.get("trustNumber"),
                int(payload.amount_cents),
                "pending",
                None,
                datetime.utcnow(),
                json.dumps(context),
            ),
        )
        conn.commit()
        # also sync flat columns so DataGrip shows values in dedicated fields
        sync_flat_columns(conn, session_id, context)
        cur.close(); conn.close()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to persist payment session: {e}")

    # If XRP is the selected method, do not create a Yoco checkout – return an XRP status and session id
    if context.get("payment_method") == "xrp":
        return {
            "status": "xrp",
            "cede_session_id": session_id,
            "payment_method": "xrp",
            "payment_amount_cents": context.get("payment_amount_cents"),
            "xrp_amount": context.get("xrp_amount"),
            "xrp_address": context.get("xrp_address"),
            "xrp_tx_hash": context.get("xrp_tx_hash"),
        }

    # 2) Build Yoco request
    url = "https://payments.yoco.com/api/checkouts"
    headers = {
        "Authorization": f"Bearer {YOCO_SECRET_KEY}",
        "Idempotency-Key": str(uuid.uuid4()),
        "Content-Type": "application/json",
    }

    # Return URLs – tailor to your Sale & Cede frontend routes
    success_url = f"https://hongkongtrust.vercel.app/agreements/sale-cede/success?sid={session_id}"  # include session id for success page retrieval
    cancel_url = "https://hongkongtrust.vercel.app/sale-cede/cancel"
    failure_url = "https://hongkongtrust.vercel.app/sale-cede/failure"

    data = {
        "amount": payload.amount_cents,
        "currency": "ZAR",
        "successUrl": success_url,
        "cancelUrl": cancel_url,
        "failureUrl": failure_url,
        "reference": session_id,
        "metadata": {
            "cede_session_id": session_id,
            "flow": "sale_cede",
            # Include trust_number for easier reconciliation in Yoco dashboard
            "trust_number": payload.trust_data.get("trust_number")
            or payload.trust_data.get("trustNumber")
        },
        "customer": {
            "email": payload.trust_data.get("email") or payload.trust_data.get("trustEmail")
        },
    }

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(url, headers=headers, json=data)
            response_data = response.json()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Yoco request failed: {e}")

    if response.status_code in [200, 201] and "redirectUrl" in response_data:
        try:
            conn = get_mssql_connection()
            cur = conn.cursor()
            cur.execute(
                "UPDATE dbo.SaleCedePayments SET yoco_ref = ?, updated_at = ? WHERE id = ?",
                (response_data.get("id") or response_data.get("reference"), datetime.utcnow(), session_id)
            )
            conn.commit()
            cur.close(); conn.close()
        except Exception as e:
            print(f"[WARN] Failed to update Yoco ref: {e}")

        return {
            "status": "success",
            "redirectUrl": response_data["redirectUrl"],
            "cede_session_id": session_id,
        }
    else:
        raise HTTPException(status_code=400, detail=response_data.get("message", "Failed to create payment session"))


@router.post("/xrp-payment")
async def record_xrp_payment(
    payload: dict,
):
    """
    Record an XRP payment intent for Sale & Cede.
    Mirrors /payment-session behaviour but without creating a Yoco checkout.
    Stores a row in dbo.SaleCedePayments with method=xrp inside context_json.
    """
    ensure_payments_table()
    ensure_flat_columns()
    try:
        # tolerate both shapes: sale_cede_context at root or nested in trust_data
        trust_data = payload.get("trust_data") or {}
        cede_ctx = payload.get("sale_cede_context") or trust_data.get("sale_cede_context") or {}

        # Resolve trust number
        trust_number = (
            cede_ctx.get("trust_number")
            or trust_data.get("trust_number")
            or trust_data.get("trustNumber")
        )

        # Extract XRP fields + amounts
        xrp_amount = cede_ctx.get("xrp_amount")
        xrp_address = cede_ctx.get("xrp_address")
        xrp_tx_hash = cede_ctx.get("xrp_tx_hash")

        # Amounts (default R500 if missing)
        pm_amount_cents = cede_ctx.get("payment_amount_cents")
        pm_amount = cede_ctx.get("payment_amount")
        if isinstance(pm_amount_cents, (int, float)) and pm_amount_cents:
            amount_cents = int(pm_amount_cents)
        elif isinstance(pm_amount, (int, float)) and pm_amount:
            amount_cents = int(round(pm_amount * 100))
        else:
            amount_cents = 50000

        session_id = str(uuid.uuid4())

        context = {
            "trust_data": trust_data,
            "sale_cede_context": cede_ctx,
            "flow": "sale_cede",
            "payment_method": "xrp",
            "payment_amount_cents": amount_cents,
            "payment_amount": amount_cents // 100,
            # XRP (optional)
            "xrp_amount": xrp_amount,
            "xrp_address": xrp_address,
            "xrp_tx_hash": xrp_tx_hash,
        }

        conn = get_mssql_connection()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO dbo.SaleCedePayments (id, trust_number, amount_cents, status, yoco_ref, created_at, context_json)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session_id,
                trust_number,
                int(amount_cents),
                "pending",
                None,
                datetime.utcnow(),
                json.dumps(context),
            ),
        )
        conn.commit()
        # also sync flat columns so DataGrip shows values in dedicated fields
        sync_flat_columns(conn, session_id, context)
        cur.close(); conn.close()

        return {"status": "xrp", "cede_session_id": session_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to persist XRP payment: {e}")


@router.post("/payment-webhook")
async def cede_yoco_webhook(request: Request):
    """Webhook for Yoco payment events for Sale & Cede flow.
    Marks the cede session `has_paid=True` by metadata `cede_session_id`.
    Implements signature verification using YOCO_WEBHOOK_SECRET.
    """
    # Signature verification
    YOCO_WEBHOOK_SECRET = os.getenv("YOCO_WEBHOOK_SECRET")
    if not YOCO_WEBHOOK_SECRET:
        raise HTTPException(status_code=500, detail="YOCO_WEBHOOK_SECRET env not set")
    signature = request.headers.get("X-Yoco-Signature")
    raw_body = await request.body()
    expected_sig = hmac.new(
        YOCO_WEBHOOK_SECRET.encode("utf-8"),
        raw_body,
        hashlib.sha256
    ).hexdigest()
    if not signature or not hmac.compare_digest(signature, expected_sig):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")

    payload = await request.json()
    event_type = payload.get("type")
    data = payload.get("data", {})

    if event_type == "payment.succeeded":
        metadata = data.get("metadata", {})
        cede_id = metadata.get("cede_session_id")
        if cede_id:
            try:
                conn = get_mssql_connection()
                cur = conn.cursor()
                cur.execute(
                    """
                    UPDATE dbo.SaleCedePayments
                    SET status = ?, yoco_ref = ISNULL(?, yoco_ref), updated_at = ?, context_json = ?
                    WHERE id = ?
                    """,
                    (
                        "paid",
                        data.get("id") or data.get("reference"),
                        datetime.utcnow(),
                        json.dumps({"webhook": payload}),
                        cede_id,
                    )
                )
                conn.commit()
                cur.close(); conn.close()
            except Exception as e:
                print(f"[WARN] Failed to mark cede session paid: {e}")
            return {"status": "success"}

    return {"status": "ignored"}


# New endpoint: fetch stored context by session id
@router.get("/session/{session_id}")
async def get_cede_session(
    session_id: str,
):
    """Return stored context for a Sale & Cede payment session from MSSQL."""
    try:
        conn = get_mssql_connection()
        cur = conn.cursor()
        cur.execute(
            "SELECT id, trust_number, amount_cents, status, yoco_ref, created_at, updated_at, context_json FROM dbo.SaleCedePayments WHERE id = ?",
            (session_id,)
        )
        row = cur.fetchone()
        cur.close(); conn.close()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read session: {e}")

    if not row:
        raise HTTPException(status_code=404, detail="Session not found")

    try:
        context = json.loads(row[7]) if row[7] else {}
    except Exception:
        context = {}

    return {
        "id": row[0],
        "trust_number": row[1],
        "amount_cents": row[2],
        "status": row[3],
        "yoco_ref": row[4],
        "created_at": row[5].isoformat() if row[5] else None,
        "updated_at": row[6].isoformat() if row[6] else None,
        "context": context,
        "has_sale_cede_context": bool(context.get("sale_cede_context")),
    }
