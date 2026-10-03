"""Provider estático para demostraciones sin host, mundo ni credenciales."""

from app.schemas.providers import ProviderDescriptor, ProviderStatus


class DemoProvider:
    """Ejemplo no registrable automáticamente y sin efectos laterales."""

    @property
    def descriptor(self) -> ProviderDescriptor:
        return ProviderDescriptor(
            id="demo",
            name="Demostración local",
            kind="demo",
            capabilities=("runtime.discover", "server.observe", "backups.observe"),
        )

    def status(self) -> ProviderStatus:
        return ProviderStatus(
            provider_id=self.descriptor.id,
            state="not_configured",
            message="Modo demostración: no hay un servidor, mundo ni cuenta conectados.",
        )
