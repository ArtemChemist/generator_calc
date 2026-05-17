import os
from flask import Flask


def create_app():
    app = Flask(__name__, instance_relative_config=True, template_folder='../templates')
    app.config['DATABASE'] = os.path.join(app.instance_path, 'generator.db')
    os.makedirs(app.instance_path, exist_ok=True)

    from .db import init_app
    init_app(app)

    from .routes.views import bp as views_bp
    from .routes.api import bp as api_bp
    app.register_blueprint(views_bp)
    app.register_blueprint(api_bp, url_prefix='/api')

    return app
