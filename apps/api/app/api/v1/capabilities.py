from fastapi import APIRouter

from app.api.deps import ProviderDep
from app.schemas.capabilities import CapabilitiesOut

router = APIRouter()


@router.get("", response_model=CapabilitiesOut)
async def get_capabilities(provider: ProviderDep) -> CapabilitiesOut:
    """What the active data provider can supply, so clients render an honest
    "not available from this data provider" state for unsupported features
    (as opposed to "not published yet"). Public, contains no secrets."""
    return CapabilitiesOut(**provider.capabilities.model_dump())
