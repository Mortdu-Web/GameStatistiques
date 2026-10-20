# Importer Config en premier : il charge le .env, et auth_client lit son environnement à l'import.
from .config import Config

if Config.AUTH_ENABLED:
    from auth_client import require_auth
else:

    def require_auth(*roles: str, mode: str = "any"):
        """Auth desactivee (dev local) : ne controle rien."""

        def decorator(view):
            return view

        return decorator


# Décorateur commun à toutes les vues : utilisateur connecté, et rôle STATS_ROLES s'il est défini.
stats_access = require_auth(*Config.STATS_ROLES)
