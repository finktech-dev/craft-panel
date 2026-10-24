"""Static provider for demos with no host, world or credentials."""

from app.schemas.providers import ProviderDescriptor, ProviderStatus


class DemoProvider:
    """Example that is never registered automatically and has no side effects."""

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
