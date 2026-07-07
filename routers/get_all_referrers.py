from pydantic import BaseModel
from typing import List
from starlette.responses import JSONResponse
from fastapi import APIRouter, HTTPException, Path, Body, UploadFile, File, Form, BackgroundTasks, Query, Depends
from database import get_mssql_connection

from security import get_current_user

class Referrer(BaseModel):
    Ref_Code: str
    Name: str
    Emails: List[str] = []

class ReferrerListResponse(BaseModel):
    referrers: List[Referrer]


# New Pydantic model for emails by referrer name
class ReferrerEmails(BaseModel):
    name: str
    emails: List[str]

router = APIRouter()

@router.get("/get_all_referrers", response_model=ReferrerListResponse)
async def get_all_referrers(
    search: str = Query(None, description="Optional search term to filter by Name or Ref_Code"),
    limit: int = Query(50, description="Maximum number of records to return"),
    user: str = Depends(get_current_user),
):
    try:
        conn = get_mssql_connection()
        cursor = conn.cursor()
        sql = "SELECT Ref_Code, Name FROM Referrers"
        params = []
        if search:
            sql += " WHERE Ref_Code LIKE ? OR Name LIKE ?"
            params.extend([f"%{search}%", f"%{search}%"])
        sql += " ORDER BY Name ASC"
        cursor.execute(sql, params)
        rows = cursor.fetchmany(limit) if limit else cursor.fetchall()

        # Build basic referrer list first
        ref_list = [Referrer(Ref_Code=row[0], Name=row[1]) for row in rows]

        # If we have no referrers, return early
        if not ref_list:
            cursor.close()
            conn.close()
            return ReferrerListResponse(referrers=[])

        # Collect codes for IN clause
        codes = [r.Ref_Code for r in ref_list]
        # Prepare parameter placeholders for IN (...) safely
        placeholders = ",".join(["?"] * len(codes))

        # Query TrustApplication for all possible email columns, flattened
        email_sql = f'''
            SELECT ta.referrer_number AS Ref_Code, e.email
            FROM TrustApplication ta
            CROSS APPLY (VALUES
                (ta.email),
                (ta.trust_email),
                (ta.settlor_email),
                (ta.trustee1_email),
                (ta.trustee2_email),
                (ta.trustee3_email),
                (ta.owner_email),
                (ta.signer_email)
            ) AS e(email)
            WHERE ta.referrer_number IN ({placeholders})
              AND e.email IS NOT NULL
              AND LTRIM(RTRIM(e.email)) <> ''
        '''
        cursor.execute(email_sql, codes)
        email_rows = cursor.fetchall()

        # Build a map of Ref_Code -> set(emails)
        email_map: dict[str, set[str]] = {}
        for ref_code, email in email_rows:
            key = str(ref_code)
            email_map.setdefault(key, set()).add(str(email))

        # Attach emails to ref_list
        for r in ref_list:
            r.Emails = sorted(email_map.get(r.Ref_Code, set()), key=lambda s: s.lower())

        cursor.close()
        conn.close()
        return ReferrerListResponse(referrers=ref_list)

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch referrers: {e}")


# New endpoint: get emails by referrer name
@router.get("/emails_by_name", response_model=ReferrerEmails)
async def get_referrer_emails_by_name(
    name: str = Query(..., description="Exact or partial referrer name, e.g. 'André Sandow'"),
    user: str = Depends(get_current_user),
):
    """
    Returns distinct emails linked to the provided referrer *name* by looking
    them up in TrustApplication. Adjust column names below if your schema differs.
    """
    try:
        conn = get_mssql_connection()
        cursor = conn.cursor()

        # Available columns for emails in TrustApplication:
        #   - email
        #   - trust_email
        #   - settlor_email
        #   - trustee1_email
        #   - trustee2_email
        #   - trustee3_email
        #   - owner_email
        #   - signer_email
        sql = (
            """
            SELECT DISTINCT
                COALESCE(
                    ta.email,
                    ta.trust_email,
                    ta.settlor_email,
                    ta.trustee1_email,
                    ta.trustee2_email,
                    ta.trustee3_email,
                    ta.owner_email,
                    ta.signer_email
                ) AS email
            FROM TrustApplication ta
            WHERE LOWER(LTRIM(RTRIM(ta.full_name))) LIKE LOWER(LTRIM(RTRIM(?)))
              AND COALESCE(
                    ta.email,
                    ta.trust_email,
                    ta.settlor_email,
                    ta.trustee1_email,
                    ta.trustee2_email,
                    ta.trustee3_email,
                    ta.owner_email,
                    ta.signer_email
                ) IS NOT NULL
            """
        )
        cursor.execute(sql, [f"%{name}%"])  # contains search; switch to [name] for exact match
        rows = cursor.fetchall()

        emails = sorted({row[0] for row in rows if row and row[0]})

        cursor.close()
        conn.close()

        return ReferrerEmails(name=name, emails=emails)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch referrer emails: {e}")