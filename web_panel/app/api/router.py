"""Agregador de rutas REST; se ampliará con los módulos de fases posteriores."""

from fastapi import APIRouter

from app.api.endpoints_auth import router as auth_router
from app.api.endpoints_cloudflare import router as cloudflare_router
from app.api.endpoints_backups import crash_router, router as backups_router
from app.api.endpoints_installer import router as installer_router
from app.api.endpoints_onboarding import router as onboarding_router
from app.api.endpoints_runtime import router as runtime_router
from app.api.endpoints_mods import router as mods_router
from app.api.endpoints_public import router as public_router
from app.api.endpoints_server import router as server_router
from app.api.endpoints_schematics import banner_router, router as schematics_router
from app.api.endpoints_tunnel import router as tunnel_router
from app.api.endpoints_configs import router as configs_router
from app.api.endpoints_operations import router as operations_router
from app.api.endpoints_registry import router as registry_router
from app.api.endpoints_restrictions import router as restrictions_router
from app.api.endpoints_worlds import router as worlds_router
from app.api.endpoints_crashes import router as crashes_router
from app.api.endpoints_whitelist import router as whitelist_router
from app.api.endpoints_waypoints import router as waypoints_router
from app.api.endpoints_luckperms import router as luckperms_router
from app.api.endpoints_advancements import router as advancements_router
from app.api.endpoints_access import router as access_router
from app.api.endpoints_discord import router as discord_router

router = APIRouter(prefix="/api")
router.include_router(auth_router)
router.include_router(access_router)
router.include_router(cloudflare_router)
router.include_router(backups_router)
router.include_router(crash_router)
router.include_router(installer_router)
router.include_router(onboarding_router)
router.include_router(runtime_router)
router.include_router(mods_router)
router.include_router(public_router)
router.include_router(server_router)
router.include_router(schematics_router)
router.include_router(banner_router)
router.include_router(tunnel_router)
router.include_router(restrictions_router)
router.include_router(configs_router)
router.include_router(registry_router)
router.include_router(operations_router)
router.include_router(worlds_router)
router.include_router(crashes_router)
router.include_router(whitelist_router)
router.include_router(waypoints_router)
router.include_router(luckperms_router)
router.include_router(advancements_router)
router.include_router(discord_router)

