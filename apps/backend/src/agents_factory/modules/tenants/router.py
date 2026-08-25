from fastapi import APIRouter


# Task 4 will add authenticated handlers and mount this router.
router = APIRouter(prefix="/tenants", tags=["tenants"])
