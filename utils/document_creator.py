from docxtpl import DocxTemplate
from io import BytesIO

def generate_trust_docx(
    data: dict,
    template_path: str = None,
    output_path: str = None
) -> BytesIO:

    # Base context with uppercased fields where needed
    context = {
        "trust_number": data.get("trust_number") or "",
        "trust_name": (data.get("trust_name") or "").upper(),
        "full_name": data.get("full_name") or "",
        "id_number": data.get("id_number") or "",
        "email": data.get("email") or "",
        "phone_number": data.get("phone_number") or "",
        "trust_email": data.get("trust_email") or "N/A",
        "establishment_date_1": data.get("establishment_date_1") or "",
        "establishment_date_2": data.get("establishment_date_2") or "",
        "beneficiaries": data.get("beneficiaries") or "N/A",
        "is_bullion_member": "Yes" if data.get("is_bullion_member") else "No",
        "member_number": data.get("member_number") or "N/A",
        "referrer_number": data.get("referrer_number") or "N/A",
        "settlor_name": (data.get("settlor_name") or "").upper(),
        "settlor_id": data.get("settlor_id") or "",
        "settlor_email": data.get("settlor_email") or "",
        "trustee1_email": data.get("trustee1_email") or "",
        "trustee2_email": data.get("trustee2_email") or "",
        "trustee3_email": data.get("trustee3_email") or "",
        "owner_name": (data.get("owner_name") or "").upper(),
        "owner_id": data.get("owner_id") or "",
        "owner_email": data.get("owner_email") or "",
        "signer_name": (data.get("signer_name") or "").upper(),
        "signer_id": data.get("signer_id") or "",
        "signer_email": data.get("signer_email") or "",
        "property_address": data.get("property_address") or "",
        # Some templates use capitalized key
        "Property_Address": data.get("Property_Address") or data.get("property_address") or "",
    }


    # Determine which template to use
    trustees = [(data.get(f"trustee{i}_name") or "").strip().upper() for i in range(1, 5) if data.get(f"trustee{i}_name")]
    settlor_name = (data.get("settlor_name") or "").strip().upper()

    if len(trustees) == 2:
        # 2 Trustees: choose based on whether settlor is one of the trustees
        if settlor_name in trustees:
            template_path = "templates/_HKGFT Deed 2 Trustees Same settlor.docx"
        else:
            template_path = "templates/_HKGFT Deed 2 Trustees.docx"
    elif len(trustees) == 3:
        # 3 Trustees: choose based on whether settlor is one of the trustees
        if settlor_name in trustees:
            template_path = "templates/_HKGFT Deed 3 Trustees same Settlor.docx"
        else:
            template_path = "templates/_HKGFT Deed 3 Trustees.docx"
    elif not template_path:
        # Fallback default if not specified
        template_path = "templates/_HKGFT Deed 2 Trustees.docx"

    doc = DocxTemplate(template_path)

    # Add trustee fields with names uppercased
    for i in range(1, 5):
        context[f"trustee{i}_name"] = (data.get(f"trustee{i}_name") or "").upper()
        context[f"trustee{i}_id"] = data.get(f"trustee{i}_id") or ""
        context[f"trustee{i}_email"] = data.get(f"trustee{i}_email") or ""

    doc.render(context)

    if output_path:
        doc.save(output_path)
        return None

    buffer = BytesIO()
    doc.save(buffer)
    buffer.seek(0)
    return buffer
