"""Statistiques (PostgreSQL) : lecture seule des parties de game-hub.

REMPLACANT DIRECT de l'ancien fichier : mêmes fonctions, mêmes paramètres, mêmes retours, même init_app(app).
Fichier autonome (psycopg, psycopg_pool, Flask).

Ce service se connecte avec un rôle qui n'a accès QU'AUX vues `games.v_results` / `games.v_complete_matches`,
au catalogue `games.games` et à la liste des personnes (svc_stats, voir sql/003_login_roles.sql). Il ne peut lire
ni les comptes, ni les fichiers, ni les tâches, et la connexion est en lecture seule côté serveur.

Règles de calcul (définies une seule fois, dans les vues de sql/001_schema.sql)
- Seules les parties « complètes » comptent : autant de scores enregistrés que `player_count`.
- Le meilleur score est le plus haut si `games.higher_score_wins`, sinon le plus bas (ex. Skyjo).
- 1ère place = meilleur score de la partie ; en cas d'égalité, tous les ex æquo la comptent.
- Dernière place = pire score de la partie ; si tous les joueurs sont à égalité, personne n'est dernier.

Nouveautés côté .env (optionnelles) : DB_USER = svc_stats ; DB_SSLMODE (« require » par défaut,
« verify-full » + DB_SSLROOTCERT en production).
"""
import atexit
import re
from contextlib import contextmanager
from datetime import date

import psycopg
from flask import current_app
from psycopg.conninfo import make_conninfo
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

_EXT_KEY = "hub_db_pool"
_REQUIRED = ("games.v_results", "games.v_complete_matches", "games.games", "core.persons")

_NOM = "r.first_name AS prenom, r.last_name AS nom"

# Agrégats communs aux classements et aux fiches joueur.
_AGREGATS = """
    COUNT(*) AS nb_parties,
    COUNT(*) FILTER (WHERE r.is_winner) AS nb_premiere,
    COUNT(*) FILTER (WHERE r.is_last) AS nb_derniere,
    ROUND(AVG(r.score)::numeric, 1)::float8 AS score_moyen,
    MIN(r.score) AS score_min,
    MAX(r.score) AS score_max
"""


# ── Connexion / pool ─────────────────────────────────────────────────────────

def init_app(app) -> None:
    """Ouvre le pool et vérifie la base. Lève RuntimeError (message lisible) au moindre problème.

    Un pool par worker gunicorn, créé ici : ne pas lancer gunicorn avec --preload.
    """
    cfg = app.config
    missing = [k for k in ("DB_HOST", "DB_NAME", "DB_USER", "DB_PASSWORD") if not cfg.get(k)]
    if missing:
        raise RuntimeError(f"Variables manquantes dans le .env : {', '.join(missing)}")

    conninfo = make_conninfo(
        host=cfg["DB_HOST"],
        port=cfg.get("DB_PORT") or 5432,
        dbname=cfg["DB_NAME"],
        user=cfg["DB_USER"],
        password=cfg["DB_PASSWORD"],
        connect_timeout=10,
        client_encoding="UTF8",
        sslmode=cfg.get("DB_SSLMODE") or "require",
        sslrootcert=cfg.get("DB_SSLROOTCERT") or None,
        options="-c statement_timeout=15000 -c lock_timeout=5000 -c idle_in_transaction_session_timeout=15000",
    )
    try:
        psycopg.connect(conninfo).close()
    except psycopg.Error as exc:
        raise RuntimeError(
            f"[DB] Connexion impossible à {cfg['DB_HOST']}:{cfg.get('DB_PORT') or 5432} "
            f"(base « {cfg['DB_NAME']} », utilisateur « {cfg['DB_USER']} ») : {exc}"
        ) from exc

    pool = ConnectionPool(
        conninfo,
        min_size=cfg.get("DB_POOL_MIN") or 1,
        max_size=cfg.get("DB_POOL_MAX") or 5,
        kwargs={"row_factory": dict_row},
        check=ConnectionPool.check_connection,
        timeout=10,
        name="hub-stats",
        open=True,
    )
    try:
        problems = []
        with pool.connection() as conn:
            for t in _REQUIRED:
                row = conn.execute(
                    "SELECT to_regclass(%s) IS NOT NULL AS ok, "
                    "COALESCE(has_table_privilege(to_regclass(%s), 'SELECT'), false) AS can_read", (t, t)
                ).fetchone()
                if not row["ok"]:
                    problems.append(f"{t} introuvable (sql/001_schema.sql appliqué ?)")
                elif not row["can_read"]:
                    problems.append(f"pas de droit SELECT sur {t} (DB_USER rattaché à app_stats ?)")
        if problems:
            raise RuntimeError("[DB] Base non prête : " + " ; ".join(problems))
    except Exception:
        pool.close()
        raise
    app.extensions[_EXT_KEY] = pool
    atexit.register(pool.close)


@contextmanager
def _read():
    """Curseur en lecture seule dans une transaction courte (retour au pool automatique)."""
    with current_app.extensions[_EXT_KEY].connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SET TRANSACTION READ ONLY")
            yield cur


# ── Utilitaires ──────────────────────────────────────────────────────────────

def _clean(row: dict | None) -> dict | None:
    """Rend une ligne sérialisable en JSON (dates en ISO 8601)."""
    if row is None:
        return None
    return {k: v.isoformat() if isinstance(v, date) else v for k, v in row.items()}


def _all(sql: str, params: tuple = ()) -> list[dict]:
    with _read() as cur:
        cur.execute(sql, params)
        return [_clean(r) for r in cur.fetchall()]


def _one(sql: str, params: tuple = ()) -> dict | None:
    with _read() as cur:
        cur.execute(sql, params)
        return _clean(cur.fetchone())


# Noms à corriger à la main (accents, apostrophes) : clé = nom en minuscules, sans espaces ni caractères spéciaux.
# Les autres jeux sont mis en forme automatiquement (« trainMexicain » -> « Train Mexicain »).
_NOMS_JEUX = {
    "tresfute": "Très Futé",
    "ptitbac": "P'tit Bac",
}


def _label(name: str | None, jeu_id: int) -> str:
    """Nom lisible d'un jeu pour l'affichage."""
    name = (name or "").strip()
    if not name:
        return f"Jeu {jeu_id}"
    cle = re.sub(r"[^a-z0-9]", "", name.lower())
    if cle in _NOMS_JEUX:
        return _NOMS_JEUX[cle]
    spaced = name if " " in name else re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", name)
    return spaced[:1].upper() + spaced[1:]


def _taux(r: dict) -> int:
    return round(100 * r["nb_premiere"] / r["nb_parties"]) if r["nb_parties"] else 0


def _avec_taux(rows: list[dict]) -> list[dict]:
    """Ajoute `taux_victoire` (% de parties gagnées) et trie : victoires, puis taux, puis nombre de parties."""
    for r in rows:
        r["taux_victoire"] = _taux(r)
    return sorted(
        rows,
        key=lambda r: (-r["nb_premiere"], -r["taux_victoire"], -r["nb_parties"],
                       (r["nom"] or "").lower(), (r["prenom"] or "").lower()),
    )


# ── Jeux & joueurs ───────────────────────────────────────────────────────────

def get_all_jeux() -> list[dict]:
    rows = _all("SELECT id, name FROM games.games WHERE is_active ORDER BY name, id")
    return [{"id": r["id"], "name": r["name"], "label": _label(r["name"], r["id"])} for r in rows]


def get_jeu(jeu_id: int) -> dict | None:
    r = _one("SELECT id, name FROM games.games WHERE id = %s", (jeu_id,))
    return None if r is None else {"id": r["id"], "name": r["name"], "label": _label(r["name"], r["id"])}


def get_all_joueurs() -> list[dict]:
    return _all("SELECT id, first_name AS prenom, last_name AS nom FROM core.persons ORDER BY last_name, first_name")


# ── Vue d'ensemble ───────────────────────────────────────────────────────────

def get_nb_parties_par_jeu() -> list[dict]:
    """Nombre de parties complètes par jeu (les jeux sans partie apparaissent avec 0)."""
    rows = _all(
        """SELECT g.id AS jeu_id, g.name, COUNT(c.id) AS nb_parties
           FROM games.games g
           LEFT JOIN games.v_complete_matches c ON c.game_id = g.id
           WHERE g.is_active
           GROUP BY g.id, g.name
           ORDER BY nb_parties DESC, g.name, g.id"""
    )
    return [{**r, "label": _label(r["name"], r["jeu_id"])} for r in rows]


def get_classement_global() -> list[dict]:
    """Classement de tous les joueurs ayant au moins une partie complète, tous jeux confondus."""
    rows = _all(
        f"""SELECT r.person_id AS id, {_NOM},
                   COUNT(*) AS nb_parties,
                   COUNT(*) FILTER (WHERE r.is_winner) AS nb_premiere,
                   COUNT(*) FILTER (WHERE r.is_last) AS nb_derniere
            FROM games.v_results r
            GROUP BY r.person_id, r.first_name, r.last_name"""
    )
    return _avec_taux(rows)


# ── Par jeu ──────────────────────────────────────────────────────────────────

def get_classement_par_jeu(jeu_id: int) -> list[dict]:
    rows = _all(
        f"""SELECT r.person_id AS id, {_NOM}, {_AGREGATS}
            FROM games.v_results r
            WHERE r.game_id = %s
            GROUP BY r.person_id, r.first_name, r.last_name""",
        (jeu_id,),
    )
    return _avec_taux(rows)


def get_extremes_jeu(jeu_id: int) -> dict:
    """Score le plus bas et le plus haut jamais enregistrés pour ce jeu (None si aucune partie)."""

    def _extreme(ordre: str) -> dict | None:  # `ordre` vient du code, jamais de l'utilisateur
        return _one(
            f"""SELECT r.score, r.match_id AS partie_id, r.played_on AS date, {_NOM}
                FROM games.v_results r
                WHERE r.game_id = %s
                ORDER BY r.score {ordre}, r.played_on, r.match_id
                LIMIT 1""",
            (jeu_id,),
        )

    return {"score_plus_bas": _extreme("ASC"), "score_plus_haut": _extreme("DESC")}


def _parties_detail(where: str, params: tuple) -> list[dict]:
    """Parties (les plus récentes d'abord) avec le score de chacun, classé du meilleur au moins bon.

    `where` est une constante du code (jamais construite depuis une entrée utilisateur) ; les valeurs passent par `params`.
    """
    rows = _all(
        f"""SELECT r.match_id AS partie_id, r.played_on AS date, r.score, r.is_winner AS gagnant,
                   r.person_id AS joueur_id, {_NOM}
            FROM games.v_results r
            WHERE {where}
            ORDER BY r.played_on DESC, r.match_id DESC, r.rank, r.last_name, r.first_name""",
        params,
    )
    parties: dict[int, dict] = {}
    for r in rows:
        partie = parties.setdefault(r["partie_id"], {"partie_id": r["partie_id"], "date": r["date"], "scores": []})
        partie["scores"].append({k: r[k] for k in ("joueur_id", "prenom", "nom", "score", "gagnant")})
    return list(parties.values())


def get_parties_detail_par_jeu(jeu_id: int) -> list[dict]:
    return _parties_detail("r.game_id = %s", (jeu_id,))


# ── Par joueur ───────────────────────────────────────────────────────────────

def get_stats_joueur(joueur_id: int) -> dict | None:
    """Totaux + détail par jeu d'un joueur ; None si le joueur n'existe pas."""
    joueur = _one("SELECT id, first_name AS prenom, last_name AS nom FROM core.persons WHERE id = %s", (joueur_id,))
    if joueur is None:
        return None

    par_jeu = _all(
        f"""SELECT r.game_id AS jeu_id, r.game_name AS name, {_AGREGATS}
            FROM games.v_results r
            WHERE r.person_id = %s
            GROUP BY r.game_id, r.game_name
            ORDER BY nb_parties DESC, r.game_name, r.game_id""",
        (joueur_id,),
    )
    for r in par_jeu:
        r["jeu"] = _label(r["name"], r["jeu_id"])
        r["taux_victoire"] = _taux(r)

    nb_parties = sum(r["nb_parties"] for r in par_jeu)
    nb_premiere = sum(r["nb_premiere"] for r in par_jeu)
    return {
        **joueur,
        "nb_parties_total": nb_parties,
        "nb_premiere_total": nb_premiere,
        "nb_derniere_total": sum(r["nb_derniere"] for r in par_jeu),
        "taux_victoire_total": round(100 * nb_premiere / nb_parties) if nb_parties else 0,
        "par_jeu": par_jeu,
    }


def get_parties_detail_joueur_jeu(joueur_id: int, jeu_id: int) -> list[dict]:
    """Parties d'un jeu auxquelles le joueur a participé (avec le score de tous les participants)."""
    return _parties_detail(
        "r.game_id = %s AND r.match_id IN (SELECT match_id FROM games.v_results WHERE person_id = %s)",
        (jeu_id, joueur_id),
    )
