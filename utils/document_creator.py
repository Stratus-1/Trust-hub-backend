from docxtpl import DocxTemplate
from io import BytesIO

def generate_trust_docx(
    data: dict,
    template_path: str = None,
    output_path: str = None
) -> BytesIO:

    # Base context with uppercased fields where needed
    context = {
        "trust_number": data.get("trust_number", ""),
        "trust_name": data.get("trust_name", "").upper(),
        "full_name": data.get("full_name", ""),
        "id_number": data.get("id_number", ""),
        "email": data.get("email", ""),
        "phone_number": data.get("phone_number", ""),
        "trust_email": data.get("trust_email", "N/A"),
        "establishment_date_1": data.get("establishment_date_1", ""),
        "establishment_date_2": data.get("establishment_date_2", ""),
        "beneficiaries": data.get("beneficiaries", "N/A"),
        "is_bullion_member": "Yes" if data.get("is_bullion_member") else "No",
        "member_number": data.get("member_number", "N/A"),
        "referrer_number": data.get("referrer_number", "N/A"),
        "settlor_name": data.get("settlor_name", "").upper(),
        "settlor_id": data.get("settlor_id", ""),
        "settlor_email": data.get("settlor_email", ""),
        "trustee1_email": data.get("trustee1_email", ""),
        "trustee2_email": data.get("trustee2_email", ""),
        "trustee3_email": data.get("trustee3_email", ""),
        "owner_name": data.get("owner_name", "").upper(),
        "owner_id": data.get("owner_id", ""),
        "owner_email": data.get("owner_email", ""),
        "signer_name": data.get("signer_name", "").upper(),
        "signer_id": data.get("signer_id", ""),
        "signer_email": data.get("signer_email", ""),
        "property_address": data.get("property_address", ""),
        # Some templates use capitalized key
        "Property_Address": data.get("Property_Address") or data.get("property_address", ""),
    }


    # Determine which template to use
    trustees = [data.get(f"trustee{i}_name", "").strip().upper() for i in range(1, 5) if data.get(f"trustee{i}_name")]
    settlor_name = data.get("settlor_name", "").strip().upper()

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
        context[f"trustee{i}_name"] = data.get(f"trustee{i}_name", "").upper()
        context[f"trustee{i}_id"] = data.get(f"trustee{i}_id", "")
        context[f"trustee{i}_email"] = data.get(f"trustee{i}_email", "")

    doc.render(context)

    if output_path:
        doc.save(output_path)
        return None

    buffer = BytesIO()
    doc.save(buffer)
    buffer.seek(0)
    return buffer
