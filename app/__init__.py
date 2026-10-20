from flask import Flask
from werkzeug.middleware.proxy_fix import ProxyFix

from . import db
from .config import Config
from .routes import bp as stats_bp


def create_app() -> Flask:
    # static_folder=None : les fichiers statiques sont servis par le blueprint « statistiques »,
    # sous URL_PREFIX (comme dans game-hub).
    app = Flask(__name__, static_folder=None)
    app.config.from_object(Config)

    if Config.BEHIND_PROXY:
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    db.init_app(app)
    app.register_blueprint(stats_bp, url_prefix=Config.URL_PREFIX or None)

    @app.context_processor
    def inject_links():
        return {"hub_url": Config.HUB_URL}

    return app
