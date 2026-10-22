"""Routes cho Nora EDU."""
from backend.routes import studio, system

ROUTERS = studio.EDU_STUDIO_ROUTERS + system.ROUTERS

__all__ = ["studio", "system", "ROUTERS"]
