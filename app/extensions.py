# app/extensions.py

import os
from urllib.parse import urlparse
from flask import current_app
import mysql.connector
from sqlalchemy import create_engine

def get_db_connection():
    """
    Establishes a connection to the Aiven MySQL database using the DATABASE_URL.
    This uses the plain mysql-connector for direct cursor/execute operations.
    """
    database_url = os.environ.get('AIVEN_DATABASE_URL')
    if not database_url:
        raise Exception("AIVEN_DATABASE_URL environment variable not set.")

    try:
        # Parse the database URL to extract connection details
        result = urlparse(database_url)
        
        # SSL arguments are required for a secure connection to Aiven
        ssl_args = {'ssl_ca': 'ca.pem'}

        return mysql.connector.connect(
            host=result.hostname,
            user=result.username,
            password=result.password,
            database=result.path[1:],  # Remove the leading '/'
            port=result.port,
            **ssl_args
        )
    except Exception as e:
        print(f"Error connecting to the database via get_db_connection: {e}")
        return None

def get_engine():
    """
    Creates a SQLAlchemy engine for the Aiven MySQL database.
    This is used by pandas for functions like read_sql_query.
    """
    database_url = os.environ.get('AIVEN_DATABASE_URL')
    if not database_url:
        raise Exception("AIVEN_DATABASE_URL environment variable not set.")

    try:
        # The Aiven URL includes "?ssl-mode=REQUIRED" which is not supported
        # by the mysql-connector-python driver via SQLAlchemy's create_engine.
        # To fix this, we parse the URL, rebuild it, and provide SSL 
        # configuration through `connect_args`.
        parsed_url = urlparse(database_url)

        # Reconstruct the database URI for SQLAlchemy without the query string.
        clean_uri = (
            f"mysql+mysqlconnector://{parsed_url.username}:{parsed_url.password}@"
            f"{parsed_url.hostname}:{parsed_url.port}{parsed_url.path}"
        )

        # Provide the required SSL arguments separately in connect_args.
        connect_args = {'ssl_ca': 'ca.pem'}
        
        # Create the engine with the cleaned URI and separate SSL arguments.
        # pool_pre_ping helps prevent connections from timing out.
        return create_engine(clean_uri, connect_args=connect_args, pool_pre_ping=True)
        
    except Exception as e:
        print(f"Error creating SQLAlchemy engine: {e}")
        return None