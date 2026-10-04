"""Editor de configuración limitado a server/config y sin rutas arbitrarias."""
from __future__ import annotations
import asyncio, json, os, re, uuid
from pathlib import Path
import json5, tomlkit
from app.core.config import Settings, settings
from app.schemas.universal import ConfigDocument, ConfigFile, ConfigNode
from app.services.runtime_guard import ServerActiveError, require_server_stopped
from app.services.server_process import MinecraftServerManager, server_manager

class ConfigServiceError(RuntimeError): status_code=400
class ConfigConflictError(ConfigServiceError): status_code=409
class ConfigService:
 def __init__(self, configured_settings: Settings=settings, manager: MinecraftServerManager=server_manager): self.s=configured_settings; self.m=manager; self.lock=asyncio.Lock()
 @property
 def root(self)->Path: assert self.s.config_directory; return self.s.config_directory
 async def list_files(self)->list[ConfigFile]: return await asyncio.to_thread(self._list)
 def _list(self):
  if not self.root.is_dir(): return []
  return [self._file_info(p) for p in sorted(self.root.rglob('*')) if p.is_file() and p.suffix.lower() in {'.toml','.json','.json5','.jsonc','.cfg','.conf','.properties'}]
 def _file_info(self, path: Path) -> ConfigFile:
  relative=path.relative_to(self.root).as_posix(); name=path.stem.replace('-common','').replace('-server','').replace('-client','').replace('_',' ').replace('-',' ')
  category=self._category_for(relative.lower())
  return ConfigFile(path=relative,title=' '.join(word.capitalize() for word in name.split()),category=category,format=path.suffix.lower().lstrip('.'),size_kb=round(path.stat().st_size/1024,2))
 @staticmethod
 def _category_for(path: str) -> str:
  if 'luckperms' in path: return 'Permisos y Roles (LuckPerms)'
  if any(token in path for token in ('create','railway','combat','weapon','gun','sword','armor','build','security')): return 'Combate y construcciones'
  if any(token in path for token in ('modernfix','ferrite','aiimprovements','fastsuite','chunky','connectivity')): return 'Rendimiento'
  if any(token in path for token in ('aether','undergarden','regions','terralith','dungeon','structure','nether')): return 'Mundo y exploración'
  if any(token in path for token in ('voice','sound','accessories','emote','client')): return 'Experiencia y jugadores'
  return 'Otros mods'
 def path(self, rel:str)->Path:
  if not rel or '\\' in rel: raise ConfigServiceError('Ruta de configuración inválida.')
  p=(self.root/rel).resolve()
  if not p.is_relative_to(self.root.resolve()) or p.suffix.lower() not in {'.toml','.json','.json5','.jsonc','.cfg','.conf','.properties'}: raise ConfigServiceError('Archivo de configuración no permitido.')
  return p
 async def read(self, rel:str)->ConfigDocument:
  p=self.path(rel)
  if not p.is_file(): raise ConfigServiceError('No existe el archivo solicitado.')
  return await asyncio.to_thread(self._read,p,rel)
 def _read(self,p,rel):
  raw=p.read_text(encoding='utf-8'); fmt=p.suffix.lower().lstrip('.')
  try: data=tomlkit.parse(raw) if fmt=='toml' else (json5.loads(raw) if fmt in {'json','json5','jsonc'} else self._cfg(raw))
  except Exception as e: raise ConfigServiceError(f'No se pudo parsear {rel}: {e}') from e
  return ConfigDocument(path=rel,format=fmt,raw_content=raw,tree=self._node('root',data,'',None))
 def _cfg(self, raw):
  return {m.group(1).strip(): self._scalar(m.group(2).strip()) for m in re.finditer(r'^\s*([^#;=]+?)\s*=\s*(.*?)\s*$',raw,re.M)}
 def _scalar(self,v):
  if v.lower() in {'true','false'}: return v.lower()=='true'
  try:return int(v) if '.' not in v else float(v)
  except ValueError:return v.strip('"')
 def _node(self,key,v,path,comment):
  full=path
  if isinstance(v,dict): return ConfigNode(path=full,key=key,type='section',children=[self._node(str(k),x,f'{full}.{k}'.strip('.'),getattr(x,'trivia',None).comment if hasattr(x,'trivia') else None) for k,x in v.items()])
  typ='boolean' if isinstance(v,bool) else 'number' if isinstance(v,(int,float)) else 'list' if isinstance(v,list) else 'null' if v is None else 'string'
  text=str(comment or ''); m=re.search(r'Range:\s*([-+\d.]+)\s*~\s*([-+\d.]+)',text,re.I)
  return ConfigNode(path=full,key=key,type=typ,value=v,comment=text.lstrip('# ').strip() or None,minimum=float(m.group(1)) if m else None,maximum=float(m.group(2)) if m else None)
 async def save(self,rel,content,changes=None):
  p=self.path(rel); fmt=p.suffix.lower().lstrip('.')
  if changes is not None:
   if fmt!='toml': raise ConfigServiceError('El formulario visual preserva comentarios solo para TOML; usá el editor de código.')
   try:
    doc=tomlkit.parse(p.read_text(encoding='utf-8'))
    for path,value in changes.items():
     target=doc; parts=path.split('.')
     for key in parts[:-1]: target=target[key]
     target[parts[-1]]=value
    content=tomlkit.dumps(doc)
   except Exception as e: raise ConfigServiceError(f'No se pudo aplicar el cambio: {e}') from e
  if content is None: raise ConfigServiceError('No se recibió contenido para guardar.')
  try: require_server_stopped(self.m, 'guardar configuraciones de mods')
  except ServerActiveError as e: raise ConfigConflictError(str(e)) from e
  try: tomlkit.parse(content) if fmt=='toml' else (json5.loads(content) if fmt in {'json','json5','jsonc'} else self._cfg(content))
  except Exception as e: raise ConfigServiceError(f'Sintaxis inválida: {e}') from e
  async with self.lock:
   await asyncio.to_thread(self._atomic,p,content)
  return await self.read(rel)
 def _atomic(self,p,content):
  tmp=p.with_name(f'.{p.name}.{uuid.uuid4().hex}.tmp'); tmp.write_text(content,encoding='utf-8'); os.replace(tmp,p)
config_service=ConfigService()
