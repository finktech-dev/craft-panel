"""Small operational endpoints kept separate from administration resources."""

from fastapi import APIRouter, Depends, HTTPException

from app.core.security import get_current_admin
from app.services.scheduler_service import scheduler_service
from app.services.server_process import ServerProcessError
from app.services.spark_service import spark_service

router = APIRouter(tags=["operations"], dependencies=[Depends(get_current_admin)])


@router.get("/spark/status")
async def spark_status():
    return spark_service.status()


@router.post("/spark/audit")
async def spark_audit():
    try:
        return await spark_service.audit()
    except ServerProcessError as error:
        raise HTTPException(409, str(error)) from error


@router.get("/scheduler")
async def scheduler_jobs():
    return scheduler_service.jobs()


@router.post("/scheduler/backup/{hours}")
async def scheduler_backup(hours: int):
    if not 1 <= hours <= 168:
        raise HTTPException(400, "Intervalo inválido.")
    return scheduler_service.add_backup(hours)
