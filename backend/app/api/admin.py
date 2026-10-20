from fastapi import APIRouter, Depends, Response, status

from app.api.auth import require_admin

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/check", dependencies=[Depends(require_admin)], status_code=204)
def check_admin_key():
    """Lets the dashboard confirm a key before showing owner controls."""
    return Response(status_code=status.HTTP_204_NO_CONTENT)
