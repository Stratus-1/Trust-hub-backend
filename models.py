from typing import Optional, List
from pydantic import BaseModel, EmailStr
from datetime import datetime

class Trustee(BaseModel):
    name: Optional[str]
    id: Optional[str]
    email: Optional[EmailStr]


class TrustApplication(BaseModel):
    trust_number: str
    full_name: str
    id_number: str
    email: EmailStr
    phone_number: str
    trust_email: Optional[EmailStr]
    trust_name: str
    establishment_date: Optional[str] = None  # legacy single date, optional
    establishment_date_1: Optional[str] = None  # formatted date (e.g., "2 January 2025")
    establishment_date_2: Optional[str] = None  # legal format date (e.g., "2025-01-02")
    beneficiaries: Optional[str]
    is_bullion_member: bool
    member_number: Optional[str]
    referrer_number: Optional[str]

    trustees: List[Trustee]  # List of trustees, flexible length

    documents: List[str]  # List of saved file paths
    has_paid: bool = False
    created_at: datetime = datetime.utcnow()

    settlor_email: Optional[EmailStr]
    owner_name: Optional[str]
    owner_id: Optional[str]
    owner_email: Optional[EmailStr]
    signer_name: Optional[str]
    signer_id: Optional[str]
    signer_email: Optional[EmailStr]
    property_address: Optional[str]
