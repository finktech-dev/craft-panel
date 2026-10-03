from typing import Any, Literal
from pydantic import BaseModel, Field

class ConfigFile(BaseModel):
    path: str
    title: str
    category: str
    format: str
    size_kb: float
class ConfigNode(BaseModel): path: str; key: str; type: Literal['boolean','number','string','list','section','null']; value: Any = None; comment: str | None = None; minimum: float | None = None; maximum: float | None = None; children: list['ConfigNode'] = Field(default_factory=list)
class ConfigDocument(BaseModel): path: str; format: str; raw_content: str; tree: ConfigNode
class ConfigSaveRequest(BaseModel): content: str | None = Field(default=None, max_length=2_000_000); changes: dict[str, Any] | None = None
class BlacklistState(BaseModel): items: list[str]; enforcement_available: bool; message: str
class BlacklistItemRequest(BaseModel): item_id: str = Field(pattern=r'^!?[a-zA-Z0-9_.*-]+:[a-zA-Z0-9_./*-]+$')
class RegistryItem(BaseModel): item_id: str; mod_id: str; source_jar: str
class PlayerItem(BaseModel): username: str; uuid: str | None = None; is_whitelisted: bool = False; is_op: bool = False; is_banned: bool = False
class PlayerAction(BaseModel): username: str = Field(pattern=r'^[A-Za-z0-9_]{3,16}$'); reason: str | None = Field(default=None, max_length=200); mode: Literal['survival','spectator','creative'] | None = None
class Gamerule(BaseModel): name: str; value: str; kind: Literal['boolean','number']

class WorldEditToggleRequest(BaseModel):
    enabled: bool

class RestrictionItemRequest(BaseModel):
    item_id: str = Field(pattern=r'^!?[a-zA-Z0-9_.*-]+:[a-zA-Z0-9_./*-]+$')
    action: Literal['add', 'remove'] = 'add'

class RestrictionMobRequest(BaseModel):
    entity_id: str = Field(pattern=r'^[a-zA-Z0-9_.-]+:[a-zA-Z0-9_.-]+$')
    action: Literal['add', 'remove'] = 'add'

class RestrictionVillagerRequest(BaseModel):
    profession_id: str = Field(pattern=r'^[a-zA-Z0-9_.-]+:[a-zA-Z0-9_.-]+$')
    disabled: bool = False
    disable: bool | None = None
