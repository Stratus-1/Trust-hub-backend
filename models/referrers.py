from fastapi.responses import JSONResponse
from fastapi import APIRouter
from pydantic import BaseModel
from typing import List


# Pydantic models
class Referrer(BaseModel):
    Ref_Code: str
    Name: str

class ReferrerListResponse(BaseModel):
    referrers: List[Referrer]


router = APIRouter()


@router.get("/referrers", response_model=ReferrerListResponse)
async def get_all_referrers():
    # Example implementation; replace with actual data retrieval logic
    referrers = [
        Referrer(Ref_Code="ABC123", Name="John Doe"),
        Referrer(Ref_Code="XYZ789", Name="Jane Smith"),
    ]
    return ReferrerListResponse(referrers=referrers)