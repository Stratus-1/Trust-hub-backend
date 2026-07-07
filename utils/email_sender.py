import smtplib
import os
import logging
from email.message import EmailMessage
from dotenv import load_dotenv
import mimetypes
from typing import Optional, List, Dict, Union

# FastAPI dependency injection for authentication
from fastapi import Depends
from security import get_current_user

# Load environment variables
load_dotenv()

EMAIL_HOST = os.getenv("EMAIL_HOST")
EMAIL_PORT = int(os.getenv("EMAIL_PORT", 587))
EMAIL_ADDRESS = os.getenv("EMAIL_ADDRESS")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")

# Configure logging
logging.basicConfig(level=logging.INFO, format='[%(levelname)s] %(message)s')


# --- New: Trustee Resolution Email Function ---
def send_trustee_resolution_email(
    to_email: str,
    user_name: str,
    trust_name: str,
    docx_path: Optional[str] = None,
    doc_bytes: Optional[bytes] = None,
    subject: Optional[str] = None,
    user: str = None,
):
    """Send the trustee resolution DOCX to the user."""
    subject = subject or f"Resolution : {trust_name}"

    html_body = f"""\
    <html>
      <body style="font-family: Arial, sans-serif; color: #333; line-height: 1.6; padding: 20px;">
        <p>Dear {user_name},</p>

        <p>Attached draft resolution for you to use.</p>

        <p>Please amend where necessary. For instance you can specify the institution for which the resolution will be used.</p>

        <p>Yours faithfully,<br>
        <strong>Hong Kong Trust Services</strong><br>
        <a href="mailto:hkftservices@gmail.com">hkftservices@gmail.com</a></p>

        <hr style="margin:20px 0; border:none; border-top:1px solid #ccc;"/>

        <p style="font-size: 0.85em; color:#666;">
          This email and any accompanying attachments contain confidential and proprietary information. This information is private and protected for the benefit of The HK Services Hong Kong Foreign Trust or its associates and if you are not the intended recipient, you are requested to delete this entire communication immediately and are notified that any disclosure, copying or distribution of or taking any action based on this information is prohibited.
        </p>

        <p style="font-size: 0.85em; color:#666;">
          Emails cannot be guaranteed to be secure or free of errors or viruses. The sender does not accept any liability or responsibility for any interception, corruption, destruction, loss, late arrival or incompleteness of or tampering or interference with any of the information contained in this email.
        </p>
      </body>
    </html>
    """

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = EMAIL_ADDRESS
    msg["To"] = to_email
    msg.add_alternative(html_body, subtype="html")

    # (Policy) Do not attach documents to user emails
    logging.info("ℹ️ Skipping DOCX attachment for user email (trustee resolution)")

    try:
        with smtplib.SMTP(EMAIL_HOST, EMAIL_PORT) as smtp:
            smtp.starttls()
            smtp.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
            smtp.send_message(msg)
            logging.info("✅ Trustee resolution email sent successfully to %s", to_email)
    except Exception as e:
        logging.error("❌ Failed to send trustee resolution email: %s", e)



def send_confirmation_email(
    to_email: str,
    full_name: str,
    trust_name: str,
    pdf_path: str,
    reply_to: str = None,
    bcc: str = None,
    cc_list: Optional[List[str]] = None,
    trust_emails: Optional[Dict[str, str]] = None,
    user: str = None,
):
    subject = f"Trust Deed PDF: {trust_name}"

    html_body = f"""\
    <html>
      <body style="font-family: Arial, sans-serif; color: #333; line-height: 1.6; padding: 20px;">
        <p>Dear {full_name},</p>

        <p>Your <strong>{trust_name}</strong> has been set up successfully.</p>

        <p>
          Within 24 hours, you will receive an email from <strong>SignNow</strong> prompting you to sign the deed and documents electronically.
          This is an external software system that charges a fee for each signature.
        </p>

        <p>After you sign, the document link will be sent to the next person, and this will continue until all parties have signed.</p>

        <p>Once everybody has signed, the completed and signed document will be emailed to all parties.</p>

        <p>
          You may edit your trust by selecting <strong>Edit Trust</strong> at
          <a href="https://hongkongtrust.vercel.app/" target="_blank" style="color: #1a0dab; text-decoration: underline;">
            https://hongkongtrust.vercel.app/
          </a>.
          Please note that the deed will need to be signed again and a fee of <strong>R165</strong> will apply.
        </p>

        <p>Yours faithfully,<br>
        <strong>Hong Kong Trust Services</strong><br>
        <a href="mailto:hkftservices@gmail.com">hkftservices@gmail.com</a></p>

        <hr style="margin:20px 0; border:none; border-top:1px solid #ccc;"/>

        <p style="font-size: 0.85em; color:#666;">
          This email and any accompanying attachments contain confidential and proprietary information. This information is private and protected for the benefit of The HK Services Hong Kong Foreign Trust or its associates and if you are not the intended recipient, you are requested to delete this entire communication immediately and are notified that any disclosure, copying or distribution of or taking any action based on this information is prohibited.
        </p>

        <p style="font-size: 0.85em; color:#666;">
          Emails cannot be guaranteed to be secure or free of errors or viruses. The sender does not accept any liability or responsibility for any interception, corruption, destruction, loss, late arrival or incompleteness of or tampering or interference with any of the information contained in this email.
        </p>
      </body>
    </html>
    """

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = EMAIL_ADDRESS
    msg["To"] = to_email

    # Build CC list: include all trust-related emails, deduplicated; exclude primary recipient and blanks
    cc_candidates: List[str] = []
    if cc_list:
      cc_candidates.extend(cc_list)
    if trust_emails:
      # Collect from common keys if provided
      for k in [
        'email', 'trust_email', 'settlor_email',
        'trustee1_email', 'trustee2_email', 'trustee3_email', 'trustee4_email',
        'owner_email', 'signer_email',
      ]:
        v = trust_emails.get(k)
        if v:
          cc_candidates.append(v)

    # Normalize, dedupe, and exclude the main recipient
    norm = lambda s: s.strip().lower()
    primary = norm(to_email)
    unique_cc = []
    seen = set()
    for e in cc_candidates:
      if not e:
        continue
      n = norm(e)
      if n and n != primary and n not in seen:
        unique_cc.append(e.strip())
        seen.add(n)

    if unique_cc:
      msg["Cc"] = ", ".join(unique_cc)

    if bcc:
        msg["Bcc"] = bcc
    if reply_to:
        msg["Reply-To"] = reply_to

    msg.add_alternative(html_body, subtype="html")  # HTML-only

    # (Policy) Do not attach documents to user emails
    logging.info("ℹ️ Skipping PDF attachment for user confirmation email")

    try:
        with smtplib.SMTP(EMAIL_HOST, EMAIL_PORT) as smtp:
            smtp.starttls()
            smtp.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
            smtp.send_message(msg)
            logging.info("✅ Email sent successfully to %s", to_email)
    except Exception as e:
        logging.error("❌ Failed to send email: %s", e)


def send_amended_trust_email(
    to_email: str,
    full_name: str,
    trust_name: str,
    pdf_path: str,
    cc_email: str = None,
    reply_to: str = None,
    bcc: str = None,
    cc_list: Optional[List[str]] = None,
    trust_emails: Optional[Dict[str, str]] = None,
    parties: Optional[Union[Dict[str, str], List[Dict[str, str]]]] = None,
    user: str = None,
):
    """
    Send the amended trust deed to the client and optionally CC the admin.
    Subject and body are tailored for amended deeds.
    """
    subject = f"Amended Trust Deed : {trust_name}"

    html_body = f"""\
    <html>
      <body style="font-family: Arial, sans-serif; color: #333; line-height: 1.6; padding: 20px;">
        <p>Dear {full_name},</p>

        <p>Your <strong>{trust_name}</strong> has been edited successfully.</p>

        <p>
          Within 24 hours, you will receive an email from <strong>SignNow</strong> prompting you to sign the deed and documents electronically.
          This is an external software system that charges a fee for each signature.
        </p>

        <p>After you sign, the document link will be sent to the next person, and this will continue until all parties have signed.</p>

        <p>Once everybody has signed, the completed and signed document will be emailed to all parties.</p>

        <p>
          You may edit your trust by selecting <strong>Edit Trust</strong> at
          <a href="https://hongkongtrust.vercel.app/" target="_blank" style="color: #1a0dab; text-decoration: underline;">
            https://hongkongtrust.vercel.app/
          </a>.
          Please note that the deed will need to be signed again and a fee of <strong>R165</strong> will apply.
        </p>

        <p>Yours faithfully,<br>
        <strong>Hong Kong Trust Services</strong><br>
        <a href="mailto:hkftservices@gmail.com">hkftservices@gmail.com</a></p>

        <hr style="margin:20px 0; border:none; border-top:1px solid #ccc;"/>

        <p style="font-size: 0.85em; color:#666;">
          This email and any accompanying attachments contain confidential and proprietary information. This information is private and protected for the benefit of The HK Services Hong Kong Foreign Trust or its associates and if you are not the intended recipient, you are requested to delete this entire communication immediately and are notified that any disclosure, copying or distribution of or taking any action based on this information is prohibited.
        </p>

        <p style="font-size: 0.85em; color:#666;">
          Emails cannot be guaranteed to be secure or free of errors or viruses. The sender does not accept any liability or responsibility for any interception, corruption, destruction, loss, late arrival or incompleteness of or tampering or interference with any of the information contained in this email.
        </p>
      </body>
    </html>
    """

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = EMAIL_ADDRESS
    msg["To"] = to_email
    if bcc:
        msg["Bcc"] = bcc
    if reply_to:
        msg["Reply-To"] = reply_to

    # Build CCs from explicit cc_email/cc_list, trust_emails, and parties
    cc_candidates: List[str] = []
    if cc_email:
        cc_candidates.append(cc_email)
    if cc_list:
        cc_candidates.extend(cc_list)
    if trust_emails:
        for k in [
            'email', 'trust_email', 'settlor_email',
            'trustee1_email', 'trustee2_email', 'trustee3_email', 'trustee4_email',
            'owner_email', 'signer_email',
        ]:
            v = trust_emails.get(k)
            if isinstance(v, str) and v.strip():
                cc_candidates.append(v.strip())
    if parties:
        if isinstance(parties, dict):
            for k in [
                'settlor_email', 'trustee1_email', 'trustee2_email', 'trustee3_email', 'trustee4_email',
                'owner_email', 'signer_email',
            ]:
                v = parties.get(k)
                if isinstance(v, str) and v.strip():
                    cc_candidates.append(v.strip())
        elif isinstance(parties, list):
            for it in parties:
                if not isinstance(it, dict):
                    continue
                for ek in ('email', 'email_address', 'emailAddress'):
                    ev = it.get(ek)
                    if isinstance(ev, str) and ev.strip():
                        cc_candidates.append(ev.strip())
                        break

    # Normalize, dedupe, and exclude the primary recipient
    norm = lambda s: s.strip().lower()
    primary = norm(to_email)
    unique_cc = []
    seen = set()
    for e in cc_candidates:
        if not e:
            continue
        n = norm(e)
        if n and n != primary and n not in seen:
            unique_cc.append(e)
            seen.add(n)

    if unique_cc:
        msg["Cc"] = ", ".join(unique_cc)

    msg.add_alternative(html_body, subtype="html")

    # (Policy) Do not attach documents to user emails
    logging.info("ℹ️ Skipping PDF attachment for amended deed user email")

    try:
        with smtplib.SMTP(EMAIL_HOST, EMAIL_PORT) as smtp:
            smtp.starttls()
            smtp.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
            smtp.send_message(msg)
            logging.info("✅ Amended deed email sent to %s (cc: %s)", to_email, cc_email or "-")
    except Exception as e:
        logging.error("❌ Failed to send amended deed email: %s", e)


def send_admin_email_with_attachments(
    admin_email: str,
    trust_name: str,
    docx_path: str,
    pdf_path: str,
    parties: Optional[Dict[str, str]] = None,
    user: str = None,
):
    subject = f"Trust Documents for Signing – {trust_name}"

    # Pull party info safely
    p = parties or {}
    settlor_name = p.get('settlor_name', '')
    settlor_email = p.get('settlor_email', '')
    trustee1_name = p.get('trustee1_name', '')
    trustee1_email = p.get('trustee1_email', '')
    trustee2_name = p.get('trustee2_name', '')
    trustee2_email = p.get('trustee2_email', '')
    trustee3_name = p.get('trustee3_name', '')
    trustee3_email = p.get('trustee3_email', '')
    trustee4_name = p.get('trustee4_name', '')
    trustee4_email = p.get('trustee4_email', '')
    owner_name    = p.get('owner_name', '')
    owner_email   = p.get('owner_email', '')
    signer_name   = p.get('signer_name', '')
    signer_email  = p.get('signer_email', '')

    def line(label, name, email):
        if not (name or email):
            return ''
        if name and email:
            return f"<p>{label}: {name} ({email})</p>"
        return f"<p>{label}: {name or email}</p>"

    parties_html = "".join([
        line("Settlor", settlor_name, settlor_email),
        line("Trustee 1", trustee1_name, trustee1_email),
        line("Owner", owner_name, owner_email),
        line("Trustee 2", trustee2_name, trustee2_email),
        line("Signer", signer_name, signer_email),
        line("Trustee 3", trustee3_name, trustee3_email),
        line("Trustee 4", trustee4_name, trustee4_email),
    ])

    html_body = f"""\
    <html>
      <body style="font-family: Arial, sans-serif; color: #333; line-height: 1.6; padding: 20px;">
        <p>Dear Admin</p>

        <p>Please find attached the new or edited <strong>{trust_name}</strong> documents for signing.</p>

        <p>The parties to the trust are as follows:</p>
        {parties_html}

        <p>Kindly review and upload the PDF for signing at your earliest convenience.</p>
        <p>Yours faithfully,<br>
        <strong>Hong Kong Trust Services</strong><br>
        <a href="mailto:hkftservices@gmail.com">hkftservices@gmail.com</a></p>

        <hr style="margin:20px 0; border:none; border-top:1px solid #ccc;"/>

        <p style="font-size: 0.85em; color:#666;">
          This email and any accompanying attachments contain confidential and proprietary information. This information is private and protected for the benefit of The HK Services Hong Kong Foreign Trust or its associates and if you are not the intended recipient, you are requested to delete this entire communication immediately and are notified that any disclosure, copying or distribution of or taking any action based on this information is prohibited.
        </p>

        <p style="font-size: 0.85em; color:#666;">
          Emails cannot be guaranteed to be secure or free of errors or viruses. The sender does not accept any liability or responsibility for any interception, corruption, destruction, loss, late arrival or incompleteness of or tampering or interference with any of the information contained in this email.
        </p>
      </body>
    </html>
    """

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = EMAIL_ADDRESS
    msg["To"] = admin_email

    msg.add_alternative(html_body, subtype="html")  # HTML-only content

    # Attach DOCX
    try:
        with open(docx_path, "rb") as f:
            file_data = f.read()
            mime_type, _ = mimetypes.guess_type(docx_path)
            maintype, subtype = (mime_type or "application/vnd.openxmlformats-officedocument.wordprocessingml.document").split("/")
            msg.add_attachment(file_data, maintype=maintype, subtype=subtype, filename=os.path.basename(docx_path))
    except Exception as e:
        logging.warning("⚠️ Failed to attach DOCX: %s", e)

    # Attach PDF
    try:
        with open(pdf_path, "rb") as f:
            file_data = f.read()
            mime_type, _ = mimetypes.guess_type(pdf_path)
            maintype, subtype = (mime_type or "application/pdf").split("/")
            msg.add_attachment(file_data, maintype=maintype, subtype=subtype, filename=os.path.basename(pdf_path))
    except Exception as e:
        logging.warning("⚠️ Failed to attach PDF: %s", e)

    try:
        with smtplib.SMTP(EMAIL_HOST, EMAIL_PORT) as smtp:
            smtp.starttls()
            smtp.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
            smtp.send_message(msg)
            logging.info("✅ Admin email sent successfully to %s", admin_email)
    except Exception as e:
        logging.error("❌ Failed to send admin email: %s", e)


def send_admin_email_with_attachments_xrp(
    admin_email: str,
    full_name: str,
    trust_name: str,
    docx_path: str,
    pdf_path: str,
    parties: Optional[Dict[str, str]] = None,
    user: str = None,
):
    subject = f"Trust Documents for Signing – {trust_name}"

    # Pull party info safely
    p = parties or {}
    settlor_name = p.get('settlor_name', '')
    settlor_email = p.get('settlor_email', '')
    trustee1_name = p.get('trustee1_name', '')
    trustee1_email = p.get('trustee1_email', '')
    trustee2_name = p.get('trustee2_name', '')
    trustee2_email = p.get('trustee2_email', '')
    trustee3_name = p.get('trustee3_name', '')
    trustee3_email = p.get('trustee3_email', '')
    trustee4_name = p.get('trustee4_name', '')
    trustee4_email = p.get('trustee4_email', '')
    owner_name    = p.get('owner_name', '')
    owner_email   = p.get('owner_email', '')
    signer_name   = p.get('signer_name', '')
    signer_email  = p.get('signer_email', '')

    def line(label, name, email):
        if not (name or email):
            return ''
        if name and email:
            return f"<p>{label}: {name} ({email})</p>"
        return f"<p>{label}: {name or email}</p>"

    parties_html = "".join([
        line("Settlor", settlor_name, settlor_email),
        line("Trustee 1", trustee1_name, trustee1_email),
        line("Owner", owner_name, owner_email),
        line("Trustee 2", trustee2_name, trustee2_email),
        line("Signer", signer_name, signer_email),
        line("Trustee 3", trustee3_name, trustee3_email),
        line("Trustee 4", trustee4_name, trustee4_email),
    ])

    html_body = f"""\
    <html>
      <body style="font-family: Arial, sans-serif; color: #333; line-height: 1.6; padding: 20px;">
        <p>Dear Admin</p>

        <p>Please find attached the new or edited <strong>{trust_name}</strong> documents for signing.</p>

        <p>The parties to the trust are as follows:</p>
        {parties_html}

        <p>Kindly review and upload the PDF for signing at your earliest convenience.</p>
        <p>Yours faithfully,<br>
        <strong>Hong Kong Trust Services</strong><br>
        <a href="mailto:hkftservices@gmail.com">hkftservices@gmail.com</a></p>

        <hr style="margin:20px 0; border:none; border-top:1px solid #ccc;"/>

        <p style="font-size: 0.85em; color:#666;">
          This email and any accompanying attachments contain confidential and proprietary information. This information is private and protected for the benefit of The HK Services Hong Kong Foreign Trust or its associates and if you are not the intended recipient, you are requested to delete this entire communication immediately and are notified that any disclosure, copying or distribution of or taking any action based on this information is prohibited.
        </p>

        <p style="font-size: 0.85em; color:#666;">
          Emails cannot be guaranteed to be secure or free of errors or viruses. The sender does not accept any liability or responsibility for any interception, corruption, destruction, loss, late arrival or incompleteness of or tampering or interference with any of the information contained in this email.
        </p>
      </body>
    </html>
    """

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = EMAIL_ADDRESS
    msg["To"] = admin_email

    msg.add_alternative(html_body, subtype="html")  # Only HTML version

    # Attach DOCX
    try:
        with open(docx_path, "rb") as f:
            file_data = f.read()
            mime_type, _ = mimetypes.guess_type(docx_path)
            maintype, subtype = (mime_type or "application/vnd.openxmlformats-officedocument.wordprocessingml.document").split("/")
            msg.add_attachment(file_data, maintype=maintype, subtype=subtype, filename=os.path.basename(docx_path))
    except Exception as e:
        logging.warning("⚠️ Failed to attach DOCX: %s", e)

    # Attach PDF
    try:
        with open(pdf_path, "rb") as f:
            file_data = f.read()
            mime_type, _ = mimetypes.guess_type(pdf_path)
            maintype, subtype = (mime_type or "application/pdf").split("/")
            msg.add_attachment(file_data, maintype=maintype, subtype=subtype, filename=os.path.basename(pdf_path))
    except Exception as e:
        logging.warning("⚠️ Failed to attach PDF: %s", e)

    try:
        with smtplib.SMTP(EMAIL_HOST, EMAIL_PORT) as smtp:
            smtp.starttls()
            smtp.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
            smtp.send_message(msg)
            logging.info("✅ XRP confirmation email sent successfully to %s", admin_email)
    except Exception as e:
        logging.error("❌ Failed to send XRP admin email: %s", e)


# --- New: Sale & Cede Agreement Email Function ---
def send_sale_cede_emails(
    client_email: Optional[str],
    owner_full_name: str,
    trust_name: str,
    docx_path: str,
    pdf_path: str,
    admin_email: str = "hkftservices@gmail.com",
    reply_to: Optional[str] = None,
    bcc: Optional[str] = None,
    trust_emails: Optional[Dict[str, str]] = None,
    parties: Optional[Union[Dict[str, str], List[Dict[str, str]]]] = None,
    user: str = None,
):
    """Send Sale & Cede Agreement emails.

    Policy:
      - Client email: ONLY 'To' the client (NO CC, NO BCC).
      - Admin email:   ONLY 'To' the admin (NO CC).
      - Admin receives DOCX + PDF attachments.
      - Client receives informational email (no attachments).
    """
    # CCs are DISABLED for Sale & Cede client/admin flow per policy.
    cc_candidates: List[str] = []

    # Build parties HTML (names & emails) similar to other admin emails
    def _sale_cede_parties_html(parties_payload):
        if not parties_payload:
            return ""
        # List-shaped payload: [{role,name,email}] support
        if isinstance(parties_payload, list):
            lines = []
            for it in parties_payload:
                if not isinstance(it, dict):
                    continue
                role = (it.get('role') or it.get('type') or it.get('label') or it.get('participant_type') or 'Participant').strip()
                name = (it.get('name') or it.get('full_name') or it.get('fullName') or it.get('display_name') or it.get('displayName') or '').strip()
                email = (it.get('email') or it.get('email_address') or it.get('emailAddress') or '').strip()
                if not (name or email):
                    continue
                if name and email:
                    lines.append(f"<p>{role}: {name} ({email})</p>")
                else:
                    lines.append(f"<p>{role}: {name or email}</p>")
            return "".join(lines)
        # Dict-shaped payload
        p = parties_payload if isinstance(parties_payload, dict) else {}
        def pick(d, *keys):
            for k in keys:
                v = d.get(k)
                if isinstance(v, str) and v.strip():
                    return v.strip()
            return ""
        settlor_name  = pick(p, 'settlor_name', 'settlorFullName', 'settlor')
        settlor_email = pick(p, 'settlor_email', 'settlorEmail')
        trustee1_name  = pick(p, 'trustee1_name', 'trustee1FullName', 'trustee_1_name')
        trustee1_email = pick(p, 'trustee1_email', 'trustee1Email', 'trustee_1_email')
        trustee2_name  = pick(p, 'trustee2_name', 'trustee2FullName', 'trustee_2_name')
        trustee2_email = pick(p, 'trustee2_email', 'trustee2Email', 'trustee_2_email')
        trustee3_name  = pick(p, 'trustee3_name', 'trustee3FullName', 'trustee_3_name')
        trustee3_email = pick(p, 'trustee3_email', 'trustee3Email', 'trustee_3_email')
        trustee4_name  = pick(p, 'trustee4_name', 'trustee4FullName', 'trustee_4_name')
        trustee4_email = pick(p, 'trustee4_email', 'trustee4Email', 'trustee_4_email')
        owner_name     = pick(p, 'owner_name', 'ownerFullName', 'property_owner_name')
        owner_email    = pick(p, 'owner_email', 'ownerEmail', 'property_owner_email', 'owner_email_address', 'ownerEmailAddress')
        signer_name    = pick(p, 'signer_name', 'signerFullName', 'primary_signer_name')
        signer_email   = pick(p, 'signer_email', 'signerEmail', 'primary_signer_email', 'signerEmailAddress')
        def line(label, name, email):
            if not (name or email):
                return ''
            if name and email:
                return f"<p>{label}: {name} ({email})</p>"
            return f"<p>{label}: {name or email}</p>"
        html = "".join([
            line("Settlor",   settlor_name,  settlor_email),
            line("Trustee 1", trustee1_name, trustee1_email),
            line("Owner",     owner_name,    owner_email),
            line("Trustee 2", trustee2_name, trustee2_email),
            line("Signer",    signer_name,   signer_email),
            line("Trustee 3", trustee3_name, trustee3_email),
            line("Trustee 4", trustee4_name, trustee4_email),
        ])
        return html

    parties_html_block = _sale_cede_parties_html(parties)

    # Build client email (PDF only)
    client_msg = None
    if client_email:
        client_subject = f"Agreement of Sale & Cession: {trust_name}"
        client_html = f"""\
        <html>
          <body style="font-family: Arial, sans-serif; color: #333; line-height: 1.6; padding: 20px;">
            <p>Dear {owner_full_name},</p>

            <p>Your<strong>Agreement of Sale and Cession of Claims and Rights</strong> for
               <strong>{trust_name}</strong> has been completed</p>

             <p>
          Within 24 hours, you will receive an email from <strong>SignNow</strong> prompting you to sign the agreement electronically.
          This is an external software system that charges a fee for each signature.
        </p>

        <p>After you sign, the document link will be sent to the next person, and this will continue until all parties have signed.</p>

        <p>Once everybody has signed, the completed and signed document will be emailed to all parties.</p>

        <p>
          The signing process must be completed within 36 Hours
        </p>

        <p>Yours faithfully,<br>
        <strong>Hong Kong Trust Services</strong><br>
        <a href="mailto:hkftservices@gmail.com">hkftservices@gmail.com</a></p>

        <hr style="margin:20px 0; border:none; border-top:1px solid #ccc;"/>

        <p style="font-size: 0.85em; color:#666;">
          This email and any accompanying attachments contain confidential and proprietary information. This information is private and protected for the benefit of The HK Services Hong Kong Foreign Trust or its associates and if you are not the intended recipient, you are requested to delete this entire communication immediately and are notified that any disclosure, copying or distribution of or taking any action based on this information is prohibited.
        </p>

        <p style="font-size: 0.85em; color:#666;">
          Emails cannot be guaranteed to be secure or free of errors or viruses. The sender does not accept any liability or responsibility for any interception, corruption, destruction, loss, late arrival or incompleteness of or tampering or interference with any of the information contained in this email.
        </p>
          </body>
        </html>
        """

        client_msg = EmailMessage()
        client_msg["Subject"] = client_subject
        client_msg["From"] = EMAIL_ADDRESS
        client_msg["To"] = client_email
        # No CC or BCC per policy
        if reply_to:
            client_msg["Reply-To"] = reply_to
        client_msg.add_alternative(client_html, subtype="html")

        # (Policy) Do not attach documents to user emails
        logging.info("ℹ️ Skipping PDF attachment for Sale & Cede client email")

    # Build admin email (DOCX + PDF)
    admin_subject = f"Sale & Cede Agreement: {trust_name}"
    admin_html = f"""\
    <html>
      <body style="font-family: Arial, sans-serif; color: #333; line-height: 1.6; padding: 20px;">
        <p>Dear Admin,</p>
        <p>Attached is the <strong>Sale & Cession Agreement</strong> for <strong>{trust_name}</strong> for electronic signature.</p>

        <p>The parties to the trust are as follows:</p>
        {parties_html_block}

        <ul style="padding-left: 20px;">
          <li>DOCX: editable source</li>
          <li>PDF: client-facing copy</li>
        </ul>
       
        <p>Yours faithfully,<br>
        <strong>Hong Kong Trust Services</strong><br>
        <a href="mailto:hkftservices@gmail.com">hkftservices@gmail.com</a></p>

        <hr style="margin:20px 0; border:none; border-top:1px solid #ccc;"/>

        <p style="font-size: 0.85em; color:#666;">
          This email and any accompanying attachments contain confidential and proprietary information. This information is private and protected for the benefit of The HK Services Hong Kong Foreign Trust or its associates and if you are not the intended recipient, you are requested to delete this entire communication immediately and are notified that any disclosure, copying or distribution of or taking any action based on this information is prohibited.
        </p>

        <p style="font-size: 0.85em; color:#666;">
          Emails cannot be guaranteed to be secure or free of errors or viruses. The sender does not accept any liability or responsibility for any interception, corruption, destruction, loss, late arrival or incompleteness of or tampering or interference with any of the information contained in this email.
        </p>
      </body>
    </html>
    """

    admin_msg = EmailMessage()
    admin_msg["Subject"] = admin_subject
    admin_msg["From"] = EMAIL_ADDRESS
    admin_msg["To"] = admin_email
    # No CC for admin per policy
    admin_msg.add_alternative(admin_html, subtype="html")

    # Attach DOCX
    try:
        with open(docx_path, "rb") as f:
            file_data = f.read()
            mime_type, _ = mimetypes.guess_type(docx_path)
            maintype, subtype = (mime_type or "application/vnd.openxmlformats-officedocument.wordprocessingml.document").split("/")
            admin_msg.add_attachment(file_data, maintype=maintype, subtype=subtype, filename=os.path.basename(docx_path))
    except Exception as e:
        logging.warning("⚠️ Failed to attach Sale & Cede DOCX: %s", e)

    # Attach PDF
    try:
        with open(pdf_path, "rb") as f:
            file_data = f.read()
            mime_type, _ = mimetypes.guess_type(pdf_path)
            maintype, subtype = (mime_type or "application/pdf").split("/")
            admin_msg.add_attachment(file_data, maintype=maintype, subtype=subtype, filename=os.path.basename(pdf_path))
    except Exception as e:
        logging.warning("⚠️ Failed to attach Sale & Cede PDF: %s", e)

    # Send emails (reuse a single SMTP connection if possible)
    try:
        with smtplib.SMTP(EMAIL_HOST, EMAIL_PORT) as smtp:
            smtp.starttls()
            smtp.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
            if client_msg is not None:
                smtp.send_message(client_msg)
                logging.info("✅ Sale & Cede client email sent to %s", client_email)
            smtp.send_message(admin_msg)
            logging.info("✅ Sale & Cede admin email sent to %s", admin_email)
    except Exception as e:
        logging.error("❌ Failed to send Sale & Cede emails: %s", e)
