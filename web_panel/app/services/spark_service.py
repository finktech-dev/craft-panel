from __future__ import annotations
import re
from app.services.server_process import MinecraftServerManager, server_manager
class SparkService:
 def __init__(self, manager:MinecraftServerManager=server_manager): self.m=manager
 def status(self):
  urls=re.findall(r'https://spark\.lucko\.me/\S+', '\n'.join(x['message'] for x in self.m.history[-500:]))
  return {'last_report_url':urls[-1] if urls else None,'note':'El reporte Spark aparece en consola al terminar.'}
 async def audit(self):
  await self.m.send_command('/spark sampler --timeout 30'); return {'success':True,'message':'Sampler Spark iniciado.'}
spark_service=SparkService()
