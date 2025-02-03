from flask import Flask, render_template, request, jsonify
import json
import subprocess
import threading
from trading_bot import main as run_bot

app = Flask(__name__)

# Load config
with open("config.json", "r") as f:
    config = json.load(f)

# Global variable to store logs
logs = []

@app.route("/")
def index():
    """Render the main UI page."""
    return render_template("index.html", filters=config["filters"], logs=logs)

@app.route("/update_filters", methods=["POST"])
def update_filters():
    """Update filter settings."""
    new_filters = request.json
    config["filters"] = new_filters
    with open("config.json", "w") as f:
        json.dump(config, f, indent=4)
    return jsonify({"status": "success", "message": "Filters updated!"})

@app.route("/get_logs", methods=["GET"])
def get_logs():
    """Return real-time logs."""
    return jsonify(logs)

@app.route("/start_bot", methods=["POST"])
def start_bot():
    """Start the bot in a separate thread."""
    def run():
        run_bot()
    threading.Thread(target=run, daemon=True).start()
    return jsonify({"status": "success", "message": "Bot started!"})

if __name__ == "__main__":
    app.run(debug=True)