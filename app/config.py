import os

try:  # chargement optionnel du .env en local (en Docker, c'est compose qui injecte les variables)
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass


def _bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).lower() in ("1", "true", "yes", "on")


def _list(name: str) -> tuple[str, ...]:
    return tuple(v.strip() for v in os.getenv(name, "").split(",") if v.strip())


class Config:
    # Route racine derrière le reverse proxy (ex. /statistiques). Vide = à la racine.
    URL_PREFIX = os.getenv("URL_PREFIX", "").rstrip("/")
    BEHIND_PROXY = _bool("BEHIND_PROXY", False)

    # Lien « Retour au Game Hub » (URL publique du hub). Vide = pas de lien.
    HUB_URL = os.getenv("HUB_URL", "").strip()

    # Rôles Keycloak autorisés (vide = tout utilisateur connecté). Remplace l'ancien « showStatistiques ».
    STATS_ROLES = _list("STATS_ROLES")

    # Même base PostgreSQL que game-hub ; ce service y accède en lecture seule.
    DB_HOST = os.getenv("DB_HOST", "")
    DB_PORT = int(os.getenv("DB_PORT") or 5432)
    DB_NAME = os.getenv("DB_NAME", "")
    DB_USER = os.getenv("DB_USER", "")
    DB_PASSWORD = os.getenv("DB_PASSWORD", "")

    # Authentification via le paquet auth_client (service d'auth séparé), désactivée par défaut en local.
    # auth_client lit lui-même AUTH_INTERNAL_URL et AUTH_PUBLIC_URL dans l'environnement.
    AUTH_ENABLED = _bool("AUTH_ENABLED", False)
