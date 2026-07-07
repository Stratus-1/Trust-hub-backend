# routers/contact.py
from fastapi import APIRouter, HTTPException, BackgroundTasks
from fastapi.responses import JSONResponse
from pydantic import BaseModel, EmailStr
from typing import Optional
import logging

from utils.email_sender import get_smtp_connection, EMAIL_ADDRESS
from email.message import EmailMessage

router = APIRouter()

ADMIN_EMAIL = "info@trusthub.biz"


class ContactFormRequest(BaseModel):
    full_name: str
    email: str
    phone: Optional[str] = None
    subject: Optional[str] = None
    message: str


def send_contact_emails(data: ContactFormRequest):
    subject_line = data.subject or "New Contact Form Submission"

    # --- Email to admin ---
    admin_html = f"""\
    <html>
      <body style="font-family: Arial, sans-serif; color: #333; line-height: 1.6; padding: 20px;">
        <p>Dear Admin,</p>

        <p>You have received a new contact form submission from <strong>{data.full_name}</strong>.</p>

        <table style="border-collapse: collapse; width: 100%; max-width: 600px;">
          <tr>
            <td style="padding: 8px; border: 1px solid #ddd; background: #f9f9f9; font-weight: bold; width: 140px;">Full Name</td>
            <td style="padding: 8px; border: 1px solid #ddd;">{data.full_name}</td>
          </tr>
          <tr>
            <td style="padding: 8px; border: 1px solid #ddd; background: #f9f9f9; font-weight: bold;">Email</td>
            <td style="padding: 8px; border: 1px solid #ddd;"><a href="mailto:{data.email}">{data.email}</a></td>
          </tr>
          {"<tr><td style='padding: 8px; border: 1px solid #ddd; background: #f9f9f9; font-weight: bold;'>Phone</td><td style='padding: 8px; border: 1px solid #ddd;'>" + data.phone + "</td></tr>" if data.phone else ""}
          {"<tr><td style='padding: 8px; border: 1px solid #ddd; background: #f9f9f9; font-weight: bold;'>Subject</td><td style='padding: 8px; border: 1px solid #ddd;'>" + data.subject + "</td></tr>" if data.subject else ""}
          <tr>
            <td style="padding: 8px; border: 1px solid #ddd; background: #f9f9f9; font-weight: bold; vertical-align: top;">Message</td>
            <td style="padding: 8px; border: 1px solid #ddd; white-space: pre-wrap;">{data.message}</td>
          </tr>
        </table>

        <p style="margin-top: 20px;">Please reply directly to <a href="mailto:{data.email}">{data.email}</a>.</p>

        <hr style="margin:20px 0; border:none; border-top:1px solid #ccc;"/>

        <p style="font-size: 0.85em; color:#666;">
          This email was generated automatically by the TrustHub contact form.
        </p>
      </body>
    </html>
    """

    admin_msg = EmailMessage()
    admin_msg["Subject"] = f"[Contact Form] {subject_line} – {data.full_name}"
    admin_msg["From"] = EMAIL_ADDRESS
    admin_msg["To"] = ADMIN_EMAIL
    admin_msg["Reply-To"] = data.email
    admin_msg.add_alternative(admin_html, subtype="html")

    # --- Confirmation email to sender ---
    user_html = f"""\
    <html>
      <body style="font-family: Arial, sans-serif; color: #333; line-height: 1.6; padding: 20px;">
        <p>Dear {data.full_name},</p>

        <p>Thank you for reaching out to <strong>Hong Kong Trust Services</strong>.</p>

        <p>We have received your message and a member of our team will get back to you as soon as possible, typically within <strong>1–2 business days</strong>.</p>

        <p>For your records, here is a copy of your submission:</p>

        <blockquote style="border-left: 4px solid #ccc; margin: 10px 0; padding: 10px 20px; color: #555;">
          {data.message}
        </blockquote>

        <p>Yours faithfully,<br>
        <strong>Hong Kong Trust Services</strong><br>
        <a href="mailto:info@trusthub.biz">info@trusthub.biz</a></p>

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

    user_msg = EmailMessage()
    user_msg["Subject"] = f"We received your message – {subject_line}"
    user_msg["From"] = EMAIL_ADDRESS
    user_msg["To"] = data.email
    user_msg.add_alternative(user_html, subtype="html")

    try:
        with get_smtp_connection() as smtp:
            smtp.send_message(admin_msg)
            logging.info("✅ Contact form admin email sent to %s", ADMIN_EMAIL)
            smtp.send_message(user_msg)
            logging.info("✅ Contact form confirmation email sent to %s", data.email)
    except Exception as e:
        logging.error("❌ Failed to send contact form emails: %s", e)


@router.post("/contact", tags=["Contact"])
async def submit_contact_form(
    data: ContactFormRequest,
    background_tasks: BackgroundTasks,
):
    """
    Submit a contact form enquiry.

    - Sends an email to the admin (info@trusthub.biz) with full submission details.
    - Sends a confirmation email to the user acknowledging their enquiry.
    """
    if not data.full_name or not data.full_name.strip():
        raise HTTPException(status_code=400, detail="full_name is required.")
    if not data.email or not data.email.strip():
        raise HTTPException(status_code=400, detail="email is required.")
    if not data.message or not data.message.strip():
        raise HTTPException(status_code=400, detail="message is required.")

    background_tasks.add_task(send_contact_emails, data)

    return JSONResponse(
        status_code=200,
        content={
            "message": "Your message has been received. We will be in touch shortly.",
        }
    )
