"""Blueprint « statistiques » : la page, son API JSON et ses fichiers statiques."""
import psycopg
from flask import Blueprint, abort, current_app, jsonify, render_template, request

from . import db
from .helpers import require_auth

bp = Blueprint("statistiques", __name__, static_folder="static", static_url_path="/static")


@bp.route("/")
@require_auth("admin", "BoardGames-Access")
def page():
    """Page des statistiques (bâtie sur base.html). Les données sont chargées par stats.js via l'API."""
    return render_template("statistiques.html", jeux=db.get_all_jeux(), joueurs=db.get_all_joueurs())


# ─── API JSON consommée par stats.js ──────────────────────────────────────────

@bp.route("/api/global")
@require_auth("admin", "BoardGames-Access")
def api_global():
    """Vue d'ensemble : nb de parties par jeu + classement général tous jeux confondus."""
    return jsonify(
        {
            "parties_par_jeu": db.get_nb_parties_par_jeu(),
            "classement": db.get_classement_global(),
        }
    )


@bp.route("/api/jeu/<int:jeu_id>")
@require_auth("admin", "BoardGames-Access")
def api_jeu(jeu_id):
    """Classement détaillé, extrêmes (score le plus bas / le plus haut) et historique des parties d'un jeu."""
    if db.get_jeu(jeu_id) is None:
        abort(404)
    return jsonify(
        {
            "classement": db.get_classement_par_jeu(jeu_id),
            "extremes": db.get_extremes_jeu(jeu_id),
            "parties": db.get_parties_detail_par_jeu(jeu_id),
        }
    )


@bp.route("/api/joueur/<int:joueur_id>")
@require_auth("admin", "BoardGames-Access")
def api_joueur(joueur_id):
    """Statistiques détaillées (par jeu + totaux) pour un joueur."""
    data = db.get_stats_joueur(joueur_id)
    if data is None:
        abort(404)
    return jsonify(data)


@bp.route("/api/joueur/<int:joueur_id>/jeu/<int:jeu_id>")
@require_auth("admin", "BoardGames-Access")
def api_joueur_jeu(joueur_id, jeu_id):
    """Parties d'un jeu auxquelles un joueur a participé (déroulé au clic dans la fiche joueur)."""
    return jsonify(db.get_parties_detail_joueur_jeu(joueur_id, jeu_id))


@bp.errorhandler(psycopg.Error)
def database_error(exc):
    """Base injoignable ou requête en échec : réponse 503 lisible plutôt qu'une page d'erreur brute."""
    current_app.logger.exception("Erreur PostgreSQL")
    message = "Base de données indisponible."
    if "/api/" in request.path:
        return jsonify(error="database_unavailable", message=message), 503
    return message, 503
