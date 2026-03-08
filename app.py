from flask import Flask, request, jsonify, render_template
import os, json
from dotenv import load_dotenv
import boto3
from werkzeug.utils import secure_filename
import requests

load_dotenv()
app = Flask(__name__, template_folder="templates", static_folder="static")

# ---------------- CLOUDFLARE R2 ----------------
R2_ACCESS_KEY = os.getenv("R2_ACCESS_KEY_ID")
R2_SECRET_KEY = os.getenv("R2_SECRET_ACCESS_KEY")
R2_BUCKET = os.getenv("R2_BUCKET_NAME")
R2_ENDPOINT = os.getenv("R2_ENDPOINT")
R2_PUBLIC = os.getenv("R2_PUBLIC_BASE")

s3 = boto3.client(
    "s3",
    endpoint_url=R2_ENDPOINT,
    aws_access_key_id=R2_ACCESS_KEY,
    aws_secret_access_key=R2_SECRET_KEY,
    region_name="auto"
)

MOVIES_JSON = "movies.json"
BANNER_JSON = "banner.json"

# ---------------- HELPERS ----------------
def load_movies():
    if os.path.exists(MOVIES_JSON):
        with open(MOVIES_JSON, "r") as f:
            return json.load(f)
    return []

def save_movies(data):
    with open(MOVIES_JSON, "w") as f:
        json.dump(data, f, indent=2)

# ---------------- ROUTES ----------------
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/add_movie")
def add_movie_page():
    return render_template("add_movies.html")

@app.route("/movies")
def movies():
    return jsonify(load_movies())

# ---------------- SAVE MOVIE INFO ----------------
@app.route("/save-movie", methods=["POST"])
def save_movie_info():
    data = request.get_json(force=True)
    title = data.get("title")
    category = data.get("category")
    poster = data.get("poster")
    preview = data.get("preview")
    movie = data.get("movie")
    is_banner = data.get("is_banner")

    if is_banner == "yes":
        with open(BANNER_JSON, "w") as f:
            json.dump({"banner": poster}, f, indent=2)
        return jsonify({"status":"success","message":"Banner saved!"})

    if not all([title, category, poster, preview, movie]):
        return jsonify({"status":"error","message":"Missing movie info"}),400

    movies = load_movies()
    new_id = max([m["id"] for m in movies], default=0) + 1
    movies.append({
        "id": new_id,
        "title": title,
        "category": category,
        "poster": poster,
        "preview": preview,
        "movie": movie
    })
    save_movies(movies)
    return jsonify({"status":"success","message":"Movie info saved!"})

# ---------------- PAYMENTS ----------------
FLUTTERWAVE_SECRET_KEY = os.getenv("FLUTTERWAVE_SECRET_KEY")
FLUTTERWAVE_BASE_URL = "https://api.flutterwave.com/v3"

@app.route("/pay", methods=["POST"])
def pay():
    data = request.get_json(force=True)
    phone = data.get("phone")
    amount = data.get("amount")
    movie_id = data.get("movie_id")
    tx_ref = f"movie_{movie_id}_{phone}"

    payload = {
        "tx_ref": tx_ref,
        "amount": amount,
        "currency": "UGX",
        "payment_options": "mobilemoneyuganda",
        "redirect_url": os.getenv("PAYMENT_CALLBACK_URL","http://localhost:5001/payment_callback"),
        "customer":{"phonenumber":phone,"email":"customer@example.com","name":"Movie Customer"},
        "customizations":{"title":"Classic Movies UG","description":"Movie purchase"}
    }
    headers = {"Authorization": f"Bearer {FLUTTERWAVE_SECRET_KEY}"}
    return requests.post(f"{FLUTTERWAVE_BASE_URL}/payments", json=payload, headers=headers).json()

@app.route("/payment_callback")
def payment_callback():
    return "Payment checked"

if __name__=="__main__":
    app.run(debug=True, port=5001)
