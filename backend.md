# Hong Kong Foreign Trust Backend Overview

Purpose: rebuild brief for Lovable or another backend/API generator.

Source repo: `/Users/user/stratsol-projects/hongkongbackend`

Current stack:

- FastAPI
- Python
- MSSQL via `pyodbc`
- MongoDB via `motor` for legacy payment/session records
- DOCX generation via `python-docx` and `docxtpl`
- PDF conversion via LibreOffice
- Email via SMTP helpers
- Deployment target: Google Cloud Run (URL: https://trust-hub-backend-service-95969170543.us-central1.run.app)
- Entrypoint: `main.py`

Local run:

```bash
uvicorn main:app --reload
```

Health check:

```text
GET /
-> {"message":"Backend is running"}
```

## Product Responsibility

The backend is the system of record and document-generation layer for the Hong Kong Foreign Trust app.

It handles:

- Trust application submission.
- Trust lookup.
- Trust editing and amended deed generation.
- Crypto payment metadata capture.
- Trust deed DOCX/PDF generation.
- Trustee resolution generation.
- Lease agreement generation.
- Loan agreement creation and DOCX generation.
- Sale and cession agreement generation.
- Referrer summary/reporting endpoints.
- Email notifications to users and admin.

## Main Runtime Files

```text
main.py
database.py
security.py
models.py
routers/submit_trust.py
routers/trusts.py
routers/edit_trust.py
routers/payment.py
routers/edit_trust_payment.py
routers/cede_payment.py
routers/sale_cede.py
routers/loan_agreement.py
routers/lease_agreement.py
routers/generate_resolution.py
routers/get_all_referrers.py
utils/document_creator.py
utils/email_sender.py
utils/pdf_converter.py
utils/formatter.py
```

Template files:

```text
templates/_HKGFT Deed 2 Trustees.docx
templates/_HKGFT Deed 2 Trustees Same settlor.docx
templates/_HKGFT Deed 3 Trustees.docx
templates/_HKGFT Deed 3 Trustees same Settlor.docx
templates/HK_Trust_Trustee_Appointment_Resolution_2_Trustees.docx
templates/HK_Trust_Trustee_Appointment_Resolution_3_Trustees.docx
templates/HK_Trust_Trustee_Appointment_Resolution_4_Trustees.docx
templates/HK_Foreign_Trust_Lease_Agreement.docx
templates/_Loan_Agreement_Template.docx
templates/Agreement of Sale and Cession of Claims and Rights.docx
```

Generated files are written under:

```text
uploads/
```

The app mounts uploads as static files:

```text
/uploads
```

## Environment Variables

Required or currently used:

```text
SQLSERVER_CONN
MONGO_URI
SECRET_KEY
YOCO_SECRET_KEY
YOCO_WEBHOOK_SECRET
LOAN_TEMPLATE_PATH
DOCX_OUT_DIR
SMTP settings used by utils/email_sender.py
```

Do not hardcode production credentials in a rebuild. The current repo has fallback connection behavior; replace that with required environment variables for production.

## App Bootstrap

`main.py`:

- Creates `FastAPI()`.
- Ensures `uploads/` exists.
- Mounts `/uploads`.
- Enables permissive CORS.
- Exposes `GET /auth/bootstrap`.
- Registers all routers.

Registered prefixes:

| Router | Prefix | Purpose |
| --- | --- | --- |
| `get_all_referrers_router` | `/referrers` | Referrer lookup/reporting. |
| `sale_cede.router` | `/api` | Sale and cession generation. |
| `trusts.router` | `/trusts` | Trust lookup, updates, referrers, documents. |
| `edit_trust.router` | `/edit-trust` | Dedicated edit lookup. |
| `submit_trust.router` | `/trust` | New trust submission. |
| `payment.router` | `/api` | Legacy Yoco payment. |
| `edit_trust_payment.router` | `/payments` | Legacy edit Yoco payment. |
| `cede_payment.router` | `/api` | Sale and cede payment/session. |
| `loan_agreement_router` | none | Loan agreement APIs. |
| `lease_agreement_router` | none | Lease agreement DOCX. |
| `generate_resolution_router` | none | Trustee resolution DOCX. |

## Auth Model

Endpoint:

```text
GET /auth/bootstrap
```

Returns:

```json
{
  "access_token": "...",
  "token_type": "bearer"
}
```

Token details:

- JWT
- HS256
- issuer: `myapp`
- audience: `myapp_users`
- default expiry: 15 minutes

Current use case: let the public frontend call protected routes with a short-lived bootstrap token.

Rebuild recommendation: if this becomes a real customer portal, replace bootstrap tokens with user auth and role-based access.

## Database Model

Primary database:

```text
MSSQL database: HKFT_Master
Main table: dbo.TrustApplication
```

Important TrustApplication columns used by the app:

```text
trust_number
trust_name
full_name
id_number
email
phone_number
trust_email
establishment_date_1
establishment_date_2
beneficiaries
is_bullion_member
member_number
referrer_number
settlor_name
settlor_id
settlor_email
trustee1_name
trustee1_id
trustee1_email
trustee2_name
trustee2_id
trustee2_email
trustee3_name
trustee3_id
trustee3_email
trustee4_name
trustee4_id
owner_name
owner_id
owner_email
signer_name
signer_id
signer_email
Property_Address
payment_reference
payment_amount
payment_currency
payment_method
payment_xrp_qty
payment_xrp_trans_id
payment_status
payment_timestamp
trust_deed_doc_binary
trust_deed_pdf_binary
submitted_at
source
status
has_paid
```

Other tables/procedures:

- `SaleCedePayments`
- `sp_GetTrustFromApplication`
- `sp_CreateLoanAgreement_FromApp`

Legacy MongoDB:

- `trust_registry.trusts`
- Used by old Yoco payment flow.

## New Trust Submission

Endpoint:

```text
POST /trust/submit-trust
Content-Type: multipart/form-data
```

Implemented in:

```text
routers/submit_trust.py
```

Core input fields:

```text
full_name
id_number
email
phone_number
trust_email
trust_name
establishment_date
establishmentDate
establishment_date_1
establishment_date_2
beneficiaries
is_bullion_member
member_number
referrer_number
settlor_name
settlor_id
settlor_email
owner_name
owner_id
owner_email
property_address
Property_Address
trustee1_name
trustee1_id
trustee1_email
trustee2_name
trustee2_id
trustee2_email
trustee3_name
trustee3_id
trustee3_email
signer_name
signer_id
signer_email
has_paid
payment_amount
payment_method
payment_xrp_qty
payment_xrp_trans_id
documents
was_referred_by_member
```

Flow:

```text
Generate next trust number
-> format trust name
-> normalize establishment date
-> save uploaded files into uploads/<safe trust name>
-> generate trust deed DOCX from template
-> convert DOCX to PDF with LibreOffice
-> insert TrustApplication row into MSSQL
-> store DOCX/PDF binaries in DB
-> schedule email task
-> return trust number and document path
```

Trust number format:

```text
<incrementing number>/<YY>
```

Current starting prefix:

```text
3200
```

## Document Template Selection

Shared helper:

```text
utils/document_creator.py
```

Template choice depends on trustee count and whether settlor is Trustee 1.

Current support:

- 2 trustees, settlor not trustee
- 2 trustees, settlor is trustee
- 3 trustees, settlor not trustee
- 3 trustees, settlor is trustee

`routers/trusts.py` has edit logic that references 4-trustee templates. Confirm the templates exist before enabling 4-trustee generation in production.

## PDF Conversion

Helper:

```text
utils/pdf_converter.py
```

Uses LibreOffice command-line conversion:

```text
libreoffice --headless --convert-to pdf --outdir <output_dir> <docx_path>
```

Production environment must include LibreOffice or document conversion will fail.

## Email Behavior

Helper:

```text
utils/email_sender.py
```

Main email functions:

- `send_confirmation_email`
- `send_amended_trust_email`
- `send_admin_email_with_attachments`
- `send_admin_email_with_attachments_xrp`
- `send_trustee_resolution_email`
- `send_sale_cede_emails`

Current policy in code:

- User emails generally do not attach generated deed/PDF.
- Admin emails include DOCX/PDF attachments for processing/signing.
- Admin recipient is usually `hkftservices@gmail.com`.

Known copy issue: some email text still references old Rand edit pricing. Update to current USD/service-fee copy during rebuild.

## Trust Lookup

General trust lookup:

```text
GET /trusts/{trust_number}?user_id=<id>
```

Used by:

- Lease agreement
- Loan agreement
- Trustee resolution
- Sale and cession

Dedicated edit lookup:

```text
GET /edit-trust/lookup?trust_number=<trust_number>&id_or_passport=<id>
```

Legacy edit lookup also exists:

```text
POST /trusts/edit-trust/lookup
```

Both validate trust number plus applicant/settlor ID.

For rebuild, keep one canonical edit lookup endpoint and remove duplicate behavior.

## Edit Trust

Endpoint:

```text
PUT /trusts/edit-trust/{trust_number}
Content-Type: application/json
```

Implemented in:

```text
routers/trusts.py
```

Payload shape:

```json
{
  "id_number": "...",
  "email": "...",
  "phone_number": "...",
  "trust_email": "...",
  "establishment_date": "YYYY-MM-DD",
  "beneficiaries": "...",
  "is_bullion_member": false,
  "member_number": null,
  "referrer_number": null,
  "settlor_name": "...",
  "settlor_id": "...",
  "settlor_email": "...",
  "trustees": [
    { "name": "...", "id": "..." }
  ],
  "trustee1_email": "...",
  "trustee2_email": "...",
  "trustee3_email": "...",
  "owner_name": "...",
  "owner_id": "...",
  "owner_email": "...",
  "signer_name": "...",
  "signer_id": "...",
  "signer_email": "...",
  "Property_Address": "..."
}
```

Frontend currently also attaches crypto metadata to the edit payload:

```text
payment_method
payment_amount
payment_currency
payment_crypto_symbol
payment_crypto_qty
payment_crypto_address
payment_crypto_usd_price
payment_crypto_effective_usd_price
payment_crypto_quote_adjustment_rate
payment_crypto_trans_id
payment_btc_qty/payment_xrp_qty/payment_usdt_qty
payment_btc_trans_id/payment_xrp_trans_id/payment_usdt_trans_id
payment_btc_address/payment_xrp_address/payment_usdt_address
crypto
```

Current backend edit model does not strongly type or persist all of that crypto metadata. For rebuild, add explicit payment audit columns or a JSON column for edit payment records.

Edit flow:

```text
Load existing row
-> keep trust_number and trust_name immutable
-> validate trustees
-> format dates
-> regenerate DOCX and PDF
-> update TrustApplication row and document binaries
-> send user/admin emails
```

Business rule:

- Existing trust service change costs `$125`, not R165.
- If the change is specifically appointing the foreign trust company, the amendment itself is free, but the first-year service fee of `$125` is payable.

## Current Crypto Payment Rules

Crypto is manual-payment based. Backend does not currently verify chain transactions.

Frontend quote rule:

```text
quotedPrice = marketPrice * 0.975
quantity = usdAmount / quotedPrice
```

Supported tokens:

| Token | Network label | Address |
| --- | --- | --- |
| BTC | Bitcoin mainnet | `bc1q33h4kvl46rgy7fpldtxl72l2hjx9al3t7awz2p` |
| XRP | XRPL mainnet | `rMuStHBy5N17ysmiQjUj4QQv5DTk8ovWDS` |
| USDT | Ethereum / ERC20 label in frontend | `TGU3rC5Bn1o4gpjfnFa3unuusjdvthtmks` |

Critical rebuild note: verify the USDT network/address compatibility before production. The current address begins with `T`, which usually indicates Tron-style addressing, while the requested UI label says ERC20.

## Legacy Yoco Payment

Legacy endpoints still exist:

```text
POST /api/payment-session
POST /api/payment-webhook
POST /payments/edit-trust-payment-session/{trust_number}
POST /payments/edit-trust-payment-webhook
```

They create Yoco checkout sessions in ZAR. The current frontend has been moved to crypto-only for trust and edit-trust payment. During rebuild:

- Hide/remove card and EFT UI.
- Either remove Yoco endpoints or clearly mark them as legacy.
- Do not let old Yoco code drive current trust pricing.

## Trustee Resolution

Endpoint:

```text
POST /generate-resolution
Content-Type: application/json
Response: DOCX blob
```

Required fields:

```text
email
trust_name
trust_number
full_name
```

The endpoint chooses a template based on trustee count:

```text
templates/HK_Trust_Trustee_Appointment_Resolution_{count}_Trustees.docx
```

Returns:

```text
Trustee_Resolution_<trust_number>.docx
```

## Lease Agreement

Endpoint:

```text
POST /generate-lease-agreement
Content-Type: application/json
Response: DOCX file
```

Payload fields:

```text
trust_name
trust_number
owner_name
owner_id
signer_name
Property_Address
witness_name
witness_id
establishment_date_1
establishment_date_2
```

Template:

```text
templates/HK_Foreign_Trust_Lease_Agreement.docx
```

## Loan Agreement

Endpoints:

```text
GET /trusts/{trust_number}?user_id=<id>
POST /api/loan-agreements
POST /api/loan-agreements/create-and-docx
GET /api/loan-agreements/docx/diagnostics
POST /api/loan-agreements/docx
```

Create payload:

```json
{
  "Trust_Number": "...",
  "User_Id": "...",
  "Trust_Name": "...",
  "Country": "...",
  "Lender_Name": "...",
  "Lender_ID": "...",
  "Trustee_Name": "...",
  "Witness_Name": "...",
  "Loan_Date": "YYYY-MM-DD",
  "CurrencyCode": "ZAR",
  "Items": [
    { "Desc": "...", "Type": "...", "Val": 1000 }
  ]
}
```

Rules:

- Up to 6 items.
- At least one item must have `Val > 0`.
- Backend calls `dbo.sp_CreateLoanAgreement_FromApp`.
- DOCX generation uses `_Loan_Agreement_Template.docx`.

## Sale and Cession

Endpoint:

```text
POST /api/agreements/sale-cede/generate
```

Implemented in:

```text
routers/sale_cede.py
```

Responsibilities:

- Pull trust metadata when missing.
- Render `Agreement of Sale and Cession of Claims and Rights.docx`.
- Convert DOCX to PDF.
- Persist payment/session details in `SaleCedePayments`.
- Email generated docs.

Payment/session endpoints:

```text
POST /api/cede/payment-session
POST /api/cede/xrp-payment
POST /api/cede/payment-webhook
GET /api/cede/session/{session_id}
```

Current sale/cede code still has Yoco/card branches. Align with crypto-only product direction during rebuild.

## Referrers

Endpoints:

```text
GET /referrers/get_all_referrers
GET /referrers/emails_by_name
POST /trusts/update-referrers
POST /trusts/referrer-payments
GET /trusts/all-referrer-fee-summaries
GET /trusts/referrer-fee-summary/{ref_code}
GET /trusts/signups-per-day
```

These are admin/reporting-style endpoints. They are not core to the public rebuild MVP unless a referrer dashboard is required.

## API Endpoint Map

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/` | Health check. |
| GET | `/auth/bootstrap` | Return short-lived frontend JWT. |
| POST | `/trust/submit-trust` | Submit new trust application. |
| GET | `/trusts` | List/search trusts. |
| GET | `/trusts/{trust_number}` | Fetch trust record. |
| PUT | `/trusts/{trust_number}/update-paid` | Update paid state. |
| PUT | `/trusts/{trust_number}/update-member` | Update member state. |
| POST | `/trusts/edit-trust/lookup` | Legacy edit lookup. |
| PUT | `/trusts/edit-trust/{trust_number}` | Update/edit trust and regenerate documents. |
| GET | `/edit-trust/lookup` | Dedicated edit lookup. |
| GET | `/trusts/sql-documents/{trust_number}/pdf` | Fetch stored PDF. |
| GET | `/trusts/sql-documents/{trust_number}/doc` | Fetch stored DOCX. |
| POST | `/generate-resolution` | Generate trustee resolution DOCX. |
| POST | `/generate-lease-agreement` | Generate lease agreement DOCX. |
| POST | `/api/loan-agreements` | Create loan agreement row. |
| POST | `/api/loan-agreements/docx` | Generate loan agreement DOCX. |
| POST | `/api/agreements/sale-cede/generate` | Generate sale and cession docs. |
| POST | `/api/cede/xrp-payment` | Record sale/cede XRP payment. |

## Rebuild Architecture Recommendation

Recommended backend if rebuilding cleanly:

```text
FastAPI
PostgreSQL or MSSQL with SQLAlchemy
Alembic migrations
Pydantic request/response models
Object storage for generated documents
Background queue for email/doc generation
Structured logging
Central settings module
```

Keep these modules separate:

```text
app/
  main.py
  core/config.py
  core/security.py
  db/session.py
  models/
  schemas/
  routers/
  services/
    trust_service.py
    document_service.py
    payment_service.py
    email_service.py
    crypto_quote_service.py
  templates/
```

Separate responsibilities:

- API routers should validate input and call services.
- Services should own business logic.
- Document generation should not be mixed into database update handlers.
- Payment records should be persisted as first-class rows.
- Email should be queued and retried.

## Production Risks To Fix

- Permissive CORS should be restricted to known frontend domains.
- SQL credentials must be env-only.
- Crypto payments are manually trusted via user-submitted hashes.
- BTC/XRP/USDT metadata is not consistently persisted for all flows.
- New trust submit endpoint still validates payment method against old values.
- Legacy Yoco/card/EFT code creates product confusion.
- Generated files are written to local disk; Cloud Run container disk is ephemeral.
- Emails run as background tasks in-process; failures are only logged.
- Duplicate edit lookup endpoints should be consolidated.
- No formal migrations are present.
- No proper admin/user authentication exists.

## MVP Backend Checklist

Must preserve:

- `GET /auth/bootstrap`
- `POST /trust/submit-trust`
- `GET /trusts/{trust_number}`
- `GET /edit-trust/lookup`
- `PUT /trusts/edit-trust/{trust_number}`
- `POST /generate-resolution`
- `POST /generate-lease-agreement`
- `POST /api/loan-agreements`
- `POST /api/loan-agreements/docx`
- `POST /api/agreements/sale-cede/generate`
- Static access to generated documents or a replacement download mechanism.

Should improve:

- Add a `Payment` table for all crypto payments.
- Add `TrustApplicationPayment` or `payment_json` for BTC/XRP/USDT metadata.
- Add idempotency keys for submissions.
- Add request IDs and structured logs.
- Move document binaries to object storage.
- Add explicit status transitions: `draft`, `payment_pending`, `submitted`, `docs_generated`, `sent_to_admin`, `signing_pending`, `completed`.

## Lovable / AI Backend Prompt

Use this prompt to rebuild the backend:

```text
Rebuild the Hong Kong Foreign Trust backend as a production-ready FastAPI API using the attached backend.md and frontend.md as the source of truth.

Preserve the public API contracts needed by the frontend: trust submit, trust lookup, edit lookup, edit update, trustee resolution, lease agreement, loan agreement, sale and cession, and auth bootstrap. Use environment variables for all secrets. Keep document generation from DOCX templates. Generate and store DOCX/PDF outputs. Store trust applications and payment metadata consistently.

Crypto is the current payment method. Accept BTC, XRP, and USDT payment metadata on new trust and edit trust flows. Persist token symbol, network, address, quoted USD price, 0.975 quote adjustment, token quantity, transaction hash, and USD amount. Do not rely on card/EFT/Yoco for the active checkout.

Clean up legacy duplication: one edit lookup endpoint, one payment model, centralized settings, service-layer business logic, structured errors, and safer CORS. Keep compatibility with the existing frontend payload shapes unless a migration path is provided.
```
