import os
from docxtpl import DocxTemplate
from io import BytesIO

# Slot -> template file. This stands in for the "Admin → Templates bucket" lookup
# until template files are managed outside the repo; slots without a file on disk
# still resolve (so callers get a clear error) rather than KeyError.
TEMPLATES = {
    "deed_2t_settlor_is_trustee": "templates/_HKGFT Deed 2 Trustees Same settlor.docx",
    "deed_2t_settlor_not_trustee": "templates/_HKGFT Deed 2 Trustees.docx",
    "deed_3t_settlor_is_trustee": "templates/_HKGFT Deed 3 Trustees same Settlor.docx",
    "deed_3t_settlor_not_trustee": "templates/_HKGFT Deed 3 Trustees.docx",
    "deed_4t_settlor_is_trustee": "templates/_HKGFT Deed 4 Trustees Same settlor.docx",
    "deed_4t_settlor_not_trustee": "templates/_HKGFT Deed 4 Trustees.docx",
    "deed_relinquished_1t": "templates/_HKGFT Deed Relinquished 1 Trustee.docx",
}


def resolve_template_slot(fields: dict) -> str:
    # Frontend hint takes priority over everything else.
    slot = fields.get("template_slot")
    if slot:
        return slot

    if fields.get("control_mode") == "relinquish":
        return "deed_relinquished_1t"

    # Legacy fallback: derive trustee_count / settlor_is_trustee from the raw
    # trusteeN_name / settlor_name fields when the caller hasn't sent them explicitly.
    trustee_count = fields.get("trustee_count")
    if trustee_count in (None, ""):
        n = sum(1 for i in range(1, 5) if (fields.get(f"trustee{i}_name") or "").strip())
    else:
        n = int(trustee_count)

    settlor_is_trustee = fields.get("settlor_is_trustee")
    if settlor_is_trustee in (None, ""):
        settlor_name = (fields.get("settlor_name") or "").strip().upper()
        trustee_names = {
            (fields.get(f"trustee{i}_name") or "").strip().upper()
            for i in range(1, 5) if fields.get(f"trustee{i}_name")
        }
        sit = bool(settlor_name) and settlor_name in trustee_names
    else:
        sit = str(settlor_is_trustee).strip().lower() == "true"

    return f"deed_{max(2, n)}t_{'settlor_is_trustee' if sit else 'settlor_not_trustee'}"


def resolve_template_path(fields: dict) -> str:
    slot = resolve_template_slot(fields)
    path = TEMPLATES.get(slot)
    if path is None:
        raise FileNotFoundError(f"No template registered for slot '{slot}'.")
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"Template for slot '{slot}' is not yet available — expected file at '{path}'."
        )
    return path


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


    if not template_path:
        template_path = resolve_template_path(data)

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
