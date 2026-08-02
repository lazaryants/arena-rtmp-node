"""WSGI entry point used by Gunicorn."""

from .restream_manager import app

application = app
