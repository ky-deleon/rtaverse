import os
from dotenv import load_dotenv
from app import create_app

# Load environment variables from .env file at the very beginning
load_dotenv()

# The FLASK_ENV variable will be read from the .env file
app = create_app(env=os.getenv("FLASK_ENV"))

if __name__ == "__main__":
    # The debug flag will be set based on the environment config
    app.run(host="127.0.0.1", port=5000)
