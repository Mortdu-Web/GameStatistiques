# game-stats — statistiques des jeux de société

Service **indépendant** de `game-hub` : son propre conteneur, son propre code, aucune dépendance entre les deux.
Il partage seulement la base PostgreSQL (en **lecture seule**) et le service d'authentification.
Même structure que `game-hub` : `create_app`, `config.py`, `helpers.py`, `db.py`, `URL_PREFIX`, Docker, réseau `web`.

## Lancer en local (sans authentification)
```bash
pip install -r requirements.txt      # sans auth-client
cp .env.example .env                 # renseigner DB_* ; AUTH_ENABLED=false et URL_PREFIX= (vide)
flask --app wsgi run --debug --port 5001
```
Page : `http://localhost:5001/` (ou `http://localhost:5001<URL_PREFIX>/` si un préfixe est défini).

## Production (avec authentification)
```bash
pip install -r requirements-auth.txt   # ajoute auth-client
# .env : AUTH_ENABLED=true + AUTH_INTERNAL_URL / AUTH_PUBLIC_URL + URL_PREFIX=/statistiques
```

## Docker
```bash
cp .env.example .env                 # renseigner PORT (différent de game-hub), DB_*
docker network create web            # déjà fait pour game-hub : ne pas refaire
docker compose up -d --build
```
En production (auth activée) : `WITH_AUTH=true docker compose up -d --build` avec `AUTH_ENABLED=true` dans le `.env`.

Le reverse proxy doit rediriger `/statistiques/` vers `game-stats:<PORT>` **sans retirer le préfixe**
(comme pour `/game-hub/`) : l'application sert elle-même ses routes sous `URL_PREFIX`.

## Structure
```
wsgi.py                  point d'entrée (gunicorn / flask)
app/
  __init__.py            create_app : préfixe d'URL, proxy, base de données, blueprint
  config.py              lecture du .env
  helpers.py             require_auth (auth_client si AUTH_ENABLED) + stats_access (rôles STATS_ROLES)
  db.py                  PostgreSQL en lecture seule : classements, extrêmes, historiques
  routes.py              blueprint « statistiques » : page + API JSON
  templates/             base.html, statistiques.html
  static/                site.css (variables, barre du haut), stats.css, stats.js
```

## Routes
- `<URL_PREFIX>/` : la page
- `<URL_PREFIX>/api/global` : parties par jeu + classement général
- `<URL_PREFIX>/api/jeu/<jeu_id>` : classement, extrêmes et historique d'un jeu (404 si inconnu)
- `<URL_PREFIX>/api/joueur/<joueur_id>` : totaux + détail par jeu d'un joueur (404 si inconnu)
- `<URL_PREFIX>/api/joueur/<joueur_id>/jeu/<jeu_id>` : parties d'un jeu auxquelles le joueur a participé

## Données
Tables lues : `jeux`, `joueurs`, `parties`, `joueurs_partie` (celles de `game-hub`). Ce service ne crée aucune table
et ouvre ses connexions en lecture seule. Il est recommandé de lui donner un compte PostgreSQL dédié :
```sql
CREATE ROLE stats_ro LOGIN PASSWORD '...';
GRANT CONNECT ON DATABASE <base> TO stats_ro;
GRANT USAGE ON SCHEMA public TO stats_ro;
GRANT SELECT ON jeux, joueurs, parties, joueurs_partie TO stats_ro;
```

### Règles de calcul (voir l'en-tête de `app/db.py`)
- Seules les parties **complètes** comptent : autant de scores enregistrés que `parties.nb_joueurs`.
- Le meilleur score est le plus haut si `jeux.victoire_score_max` est vrai, sinon le plus bas (ex. Skyjo).
- **1ère place** = meilleur score de la partie ; en cas d'égalité, tous les ex æquo la comptent.
- **Dernière place** = pire score de la partie ; si tous les joueurs sont à égalité (ou partie solo), personne n'est dernier.
- Classement : nombre de victoires, puis % de victoires, puis nombre de parties.

### Accès
`STATS_ROLES` (ex. `stats,admin`) restreint la page à ces rôles Keycloak ; vide = tout utilisateur connecté.
Cela remplace l'ancienne permission `showStatistiques`.

### Noms des jeux
Le nom affiché vient de `jeux.name`, mis en forme automatiquement (`trainMexicain` → « Train Mexicain »).
Pour un nom avec accents ou apostrophe, ajouter une entrée à `_NOMS_JEUX` dans `app/db.py`
(déjà fait pour « Très Futé » et « P'tit Bac »).
