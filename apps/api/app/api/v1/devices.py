from __future__ import annotations

from fastapi import APIRouter, status

from app.api.deps import CurrentUserDep, DevicesServiceDep
from app.schemas.notification import DeviceOut, DeviceRegister

router = APIRouter()


@router.get("", response_model=list[DeviceOut])
async def list_devices(current_user: CurrentUserDep, service: DevicesServiceDep) -> list[DeviceOut]:
    devices = await service.list_for_user(current_user.id)
    return [DeviceOut.model_validate(d) for d in devices]


@router.post("", response_model=DeviceOut, status_code=status.HTTP_201_CREATED)
async def register_device(
    payload: DeviceRegister, current_user: CurrentUserDep, service: DevicesServiceDep
) -> DeviceOut:
    device = await service.register(current_user.id, payload)
    return DeviceOut.model_validate(device)


@router.delete("/{device_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_device(
    device_id: int, current_user: CurrentUserDep, service: DevicesServiceDep
) -> None:
    await service.remove(current_user.id, device_id)
