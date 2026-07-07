from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import os

from security import create_token

from routers import trusts, sale_cede
from routers import submit_trust
from routers import payment
from routers import cede_payment
from routers.loan_agreement import router as loan_agreement_router
from routers.lease_agreement import router as lease_agreement_router
from routers.generate_resolution import router as generate_resolution_router
from routers.get_all_referrers import router as get_all_referrers_router
from routers import edit_trust
from routers import edit_trust_payment

app = FastAPI()

# Ensure uploads directory exists (prevents runtime error)
os.makedirs("uploads", exist_ok=True)

# Serve static files from the "uploads" folder
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")

# CORS middleware configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/auth/bootstrap")
def auth_bootstrap():
    token = create_token({"role": "frontend"})
    return {"access_token": token, "token_type": "bearer"}

# Register routers

app.include_router(get_all_referrers_router, prefix="/referrers", tags=["referrers"])
app.include_router(sale_cede.router, prefix="/api", tags=["Sale & Cede Agreement"])
app.include_router(trusts.router, prefix="/trusts", tags=["Trusts"])
app.include_router(edit_trust.router, prefix="/edit-trust", tags=["Edit Trust"])
app.include_router(submit_trust.router, prefix="/trust", tags=["Submit Trust"])
app.include_router(payment.router, prefix="/api", tags=["Payments"])
app.include_router(edit_trust_payment.router, prefix="/payments", tags=["Payments"])
app.include_router(cede_payment.router, prefix="/api", tags=["Cede Payments"])
app.include_router(loan_agreement_router, tags=["Loan Agreements"])
app.include_router(lease_agreement_router, tags=["Lease Agreements"])
app.include_router(generate_resolution_router, tags=["Generate Resolution"])

@app.get("/")
def root():
    return {"message": "Backend is running"}
