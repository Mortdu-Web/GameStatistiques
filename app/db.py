"""Statistiques (PostgreSQL) : lecture seule des tables de game-hub.

Tables lues : `jeux`, `joueurs`, `parties`, `joueurs_partie` (voir le README de game-hub).
Connexion configurée via le .env : DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD.
Les routes n'appellent que les fonctions ci-dessous ; ce service ne crée ni ne modifie aucune donnée.

Règles de calcul
- Seules les parties « complètes » comptent : autant de scores enregistrés que `parties.nb_joueurs`.
- Le meilleur score est le plus haut si `jeux.victoire_score_max` est vrai, sinon le plus bas (ex. Skyjo).
- 1ère place = meilleur score de la partie ; en cas d'égalité, tous les ex æquo la comptent.
- Dernière place = pire score de la partie ; si tous les joueurs sont à égalité, personne n'est dernier.
"""
import re
from datetime import date

import psycopg
from flask import current_app, g
from psycopg.rows import dict_row

# Une ligne par (partie complète, joueur) avec son rang et les indicateurs `gagnant` / `dernier`.
_RESULTATS = """
WITH parties_completes AS (
    SELECT p.id, p.jeu_id, p.date, j.victoire_score_max
    FROM parties p
    JOIN jeux j ON j.id = p.jeu_id
    JOIN joueurs_partie jp ON jp.partie_id = p.id
    GROUP BY p.id, p.jeu_id, p.date, p.nb_joueurs, j.victoire_score_max
    HAVING COUNT(*) = p.nb_joueurs
),
bruts AS (
    SELECT pc.id AS partie_id, pc.jeu_id, pc.date, pc.victoire_score_max,
           jp.joueur_id, jp.score,
           RANK() OVER (
               PARTITION BY pc.id
               ORDER BY CASE WHEN pc.victoire_score_max THEN -jp.score ELSE jp.score END
           ) AS rang,
           MIN(jp.score) OVER (PARTITION BY pc.id) AS score_min,
           MAX(jp.score) OVER (PARTITION BY pc.id) AS score_max
    FROM parties_completes pc
    JOIN joueurs_partie jp ON jp.partie_id = pc.id
),
resultats AS (
    SELECT bruts.*,
           (rang = 1) AS gagnant,
           (score_min <> score_max
            AND score = CASE WHEN victoire_score_max THEN score_min ELSE score_max END) AS dernier
    FROM bruts
)
"""

# Agrégats communs aux classements et aux fiches joueur.
_AGREGATS = """
    COUNT(*) AS nb_parties,
    COUNT(*) FILTER (WHERE r.gagnant) AS nb_premiere,
    COUNT(*) FILTER (WHERE r.dernier) AS nb_derniere,
    ROUND(AVG(r.score)::numeric, 1)::float8 AS score_moyen,
    MIN(r.score) AS score_min,
    MAX(r.score) AS score_max
"""


# ── Connexion ────────────────────────────────────────────────────────────────

def _connect() -> psycopg.Connection:
    cfg = current_app.config
    conn = psycopg.connect(
        host=cfg["DB_HOST"],
        port=cfg["DB_PORT"],
        dbname=cfg["DB_NAME"],
        user=cfg["DB_USER"],
        password=cfg["DB_PASSWORD"],
        row_factory=dict_row,
        connect_timeout=10,
        client_encoding="UTF8",
    )
    conn.read_only = True  # garde-fou : toute écriture est refusée par PostgreSQL
    return conn


def get_db() -> psycopg.Connection:
    if "db" not in g:
        g.db = _connect()
    return g.db


def _close_db(_exc=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_app(app) -> None:
    missing = [k for k in ("DB_HOST", "DB_NAME", "DB_USER", "DB_PASSWORD") if not app.config.get(k)]
    if missing:
        raise RuntimeError(f"Variables manquantes dans le .env : {', '.join(missing)}")
    app.teardown_appcontext(_close_db)


# ── Utilitaires ──────────────────────────────────────────────────────────────

def _clean(row: dict | None) -> dict | None:
    """Rend une ligne sérialisable en JSON (dates en ISO 8601)."""
    if row is None:
        return None
    return {k: v.isoformat() if isinstance(v, date) else v for k, v in row.items()}


def _all(sql: str, params: tuple = ()) -> list[dict]:
    return [_clean(r) for r in get_db().execute(sql, params).fetchall()]


def _one(sql: str, params: tuple = ()) -> dict | None:
    return _clean(get_db().execute(sql, params).fetchone())


# Noms à corriger à la main (accents, apostrophes) : clé = nom en base, en minuscules et sans espaces.
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
    cle = name.lower().replace(" ", "")
    if cle in _NOMS_JEUX:
        return _NOMS_JEUX[cle]
    spaced = name if " " in name else re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", name)
    return spaced[:1].upper() + spaced[1:]


def _avec_taux(rows: list[dict]) -> list[dict]:
    """Ajoute `taux_victoire` (% de parties gagnées) et trie : victoires, puis taux, puis nombre de parties."""
    for r in rows:
        r["taux_victoire"] = round(100 * r["nb_premiere"] / r["nb_parties"]) if r["nb_parties"] else 0
    return sorted(
        rows,
        key=lambda r: (-r["nb_premiere"], -r["taux_victoire"], -r["nb_parties"],
                       (r["nom"] or "").lower(), (r["prenom"] or "").lower()),
    )


# ── Jeux & joueurs ───────────────────────────────────────────────────────────

def get_all_jeux() -> list[dict]:
    rows = _all("SELECT id, name FROM jeux ORDER BY name, id")
    return [{"id": r["id"], "name": r["name"], "label": _label(r["name"], r["id"])} for r in rows]


def get_jeu(jeu_id: int) -> dict | None:
    r = _one("SELECT id, name FROM jeux WHERE id = %s", (jeu_id,))
    return None if r is None else {"id": r["id"], "name": r["name"], "label": _label(r["name"], r["id"])}


def get_all_joueurs() -> list[dict]:
    return _all("SELECT id, prenom, nom FROM joueurs ORDER BY nom, prenom")


# ── Vue d'ensemble ───────────────────────────────────────────────────────────

def get_nb_parties_par_jeu() -> list[dict]:
    """Nombre de parties complètes par jeu (les jeux sans partie apparaissent avec 0)."""
    rows = _all(
        _RESULTATS
        + """SELECT j.id AS jeu_id, j.name, COUNT(pc.id) AS nb_parties
             FROM jeux j
             LEFT JOIN parties_completes pc ON pc.jeu_id = j.id
             GROUP BY j.id, j.name
             ORDER BY nb_parties DESC, j.name, j.id"""
    )
    return [{**r, "label": _label(r["name"], r["jeu_id"])} for r in rows]


def get_classement_global() -> list[dict]:
    """Classement de tous les joueurs ayant au moins une partie complète, tous jeux confondus."""
    rows = _all(
        _RESULTATS
        + """SELECT jo.id, jo.prenom, jo.nom,
                    COUNT(*) AS nb_parties,
                    COUNT(*) FILTER (WHERE r.gagnant) AS nb_premiere,
                    COUNT(*) FILTER (WHERE r.dernier) AS nb_derniere
             FROM resultats r
             JOIN joueurs jo ON jo.id = r.joueur_id
             GROUP BY jo.id, jo.prenom, jo.nom"""
    )
    return _avec_taux(rows)


# ── Par jeu ──────────────────────────────────────────────────────────────────

def get_classement_par_jeu(jeu_id: int) -> list[dict]:
    rows = _all(
        _RESULTATS
        + f"""SELECT jo.id, jo.prenom, jo.nom, {_AGREGATS}
              FROM resultats r
              JOIN joueurs jo ON jo.id = r.joueur_id
              WHERE r.jeu_id = %s
              GROUP BY jo.id, jo.prenom, jo.nom""",
        (jeu_id,),
    )
    return _avec_taux(rows)


def get_extremes_jeu(jeu_id: int) -> dict:
    """Score le plus bas et le plus haut jamais enregistrés pour ce jeu (None si aucune partie)."""

    def _extreme(ordre: str) -> dict | None:
        return _one(
            _RESULTATS
            + f"""SELECT r.score, r.partie_id, r.date, jo.prenom, jo.nom
                  FROM resultats r
                  JOIN joueurs jo ON jo.id = r.joueur_id
                  WHERE r.jeu_id = %s
                  ORDER BY r.score {ordre}, r.date, r.partie_id
                  LIMIT 1""",
            (jeu_id,),
        )

    return {"score_plus_bas": _extreme("ASC"), "score_plus_haut": _extreme("DESC")}


def _parties_detail(where: str, params: tuple) -> list[dict]:
    """Parties (les plus récentes d'abord) avec le score de chacun, classé du meilleur au moins bon."""
    rows = _all(
        _RESULTATS
        + f"""SELECT r.partie_id, r.date, r.score, r.gagnant, jo.id AS joueur_id, jo.prenom, jo.nom
              FROM resultats r
              JOIN joueurs jo ON jo.id = r.joueur_id
              WHERE {where}
              ORDER BY r.date DESC, r.partie_id DESC, r.rang, jo.nom, jo.prenom""",
        params,
    )
    parties: dict[int, dict] = {}
    for r in rows:
        partie = parties.setdefault(r["partie_id"], {"partie_id": r["partie_id"], "date": r["date"], "scores": []})
        partie["scores"].append({k: r[k] for k in ("joueur_id", "prenom", "nom", "score", "gagnant")})
    return list(parties.values())


def get_parties_detail_par_jeu(jeu_id: int) -> list[dict]:
    return _parties_detail("r.jeu_id = %s", (jeu_id,))


# ── Par joueur ───────────────────────────────────────────────────────────────

def get_stats_joueur(joueur_id: int) -> dict | None:
    """Totaux + détail par jeu d'un joueur ; None si le joueur n'existe pas."""
    joueur = _one("SELECT id, prenom, nom FROM joueurs WHERE id = %s", (joueur_id,))
    if joueur is None:
        return None

    par_jeu = _all(
        _RESULTATS
        + f"""SELECT j.id AS jeu_id, j.name, {_AGREGATS}
              FROM resultats r
              JOIN jeux j ON j.id = r.jeu_id
              WHERE r.joueur_id = %s
              GROUP BY j.id, j.name
              ORDER BY nb_parties DESC, j.name, j.id""",
        (joueur_id,),
    )
    for r in par_jeu:
        r["jeu"] = _label(r["name"], r["jeu_id"])
        r["taux_victoire"] = round(100 * r["nb_premiere"] / r["nb_parties"]) if r["nb_parties"] else 0

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
        "r.jeu_id = %s AND r.partie_id IN (SELECT partie_id FROM resultats WHERE joueur_id = %s)",
        (jeu_id, joueur_id),
    )
