from typing import Annotated

from fastapi import APIRouter, Depends

from app.config import settings
from app.deps import Actor, require_roles
from app.services.gmail import configuration_status

router = APIRouter(prefix="/integrations/gmail", tags=["gmail"])


@router.get("/status")
async def status(
    actor: Annotated[Actor, Depends(require_roles("studio_owner", "platform_admin"))],
) -> dict:
    return configuration_status(settings)
