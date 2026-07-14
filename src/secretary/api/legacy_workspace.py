"""Legacy Lumina workspace routes.

All kb/graph endpoints have been removed. Shibei is the primary knowledge path.
This router is kept empty so app.py can import it without breaking; it should
be removed from app.py's router registration and then this file deleted.
"""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter()
