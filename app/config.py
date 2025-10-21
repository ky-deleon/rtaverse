import os

class BaseConfig:
    """Base configuration."""
    SECRET_KEY = os.getenv("FLASK_SECRET_KEY", "a_super_secret_key_that_is_long_and_random")
    # The AIVEN_DATABASE_URL is now the single source of truth for DB connections.
    # The individual DB_* variables are no longer needed here.
    AIVEN_DATABASE_URL = os.getenv("AIVEN_DATABASE_URL")
    TEMPLATES_AUTO_RELOAD = False

class DevConfig(BaseConfig):
    """Development configuration."""
    DEBUG = True
    # In development, disable caching of static files for easier testing
    SEND_FILE_MAX_AGE_DEFAULT = 0

class ProdConfig(BaseConfig):
    """Production configuration."""
    DEBUG = False
