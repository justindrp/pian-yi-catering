"""
Pian Yi Catering API v2
FastAPI backend for the quota management system.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(
    title="Pian Yi Catering API",
    description="Quota management system for catering business",
    version="2.0.0",
)

# CORS middleware - allow all origins for development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def root():
    """Health check and API info endpoint."""
    return {"message": "Pian Yi Catering API v2"}


@app.get("/health")
async def health_check():
    """Health check endpoint for monitoring."""
    return {"status": "healthy"}
