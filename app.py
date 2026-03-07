from flask import Flask, request, jsonify, send_from_directory, render_template, send_file
import os, json
from werkzeug.utils import secure_filename
import requests
import boto3
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__, template_folder="templates", static_folder="static")

# ---------------- FLUTTERWAVE ----------------
FLUTTERWAVE_SECRET_KEY = os.getenv("FLUTTERWAVE_SECRET_KEY")
FLUTTERWAVE_BASE_URL = "https://api.flutterwave.com/v3"

# ---------------- CLOUDFLARE R2 ----------------
R2_ACCESS_KEY = os.getenv("R2_ACCESS_KEY_ID")
R2_SECRET_KEY = os.getenv("R2_SECRET_ACCESS_KEY")
R2_BUCKET = os.getenv("R2_BUCKET_NAME")
R2_ENDPOINT = os.getenv("R2_ENDPOINT")
R2_PUBLIC = os.getenv("R2_PUBLIC_BASE")

# ---------------- FOLDERS ----------------
MOVIE_FOLDER = "static/movies"
IMAGE_FOLDER = "static/images"
os.makedirs(MOVIE_FOLDER, exist_ok=True)
os.makedirs(IMAGE_FOLDER, exist_ok=True)

MOVIES_JSON = "movies.json"
BANNER_JSON = "banner.json"
ALLOWED_MOVIE_EXT = {"mp4", "mov", "avi", "mkv"}
ALLOWED_IMAGE_EXT = {"jpg", "jpeg", "png", "gif"}

# ---------------- R2 CLIENT ----------------
s3 = boto3.client(
    "s3",
    endpoint_url=R2_ENDPOINT,
    aws_access_key_id=R2_ACCESS_KEY,
    aws_secret_access_key=R2_SECRET_KEY,
    region_name="auto"
)

def upload_to_r2(local_path, filename, content_type):
    s3.upload_file(
        local_path,
        R2_BUCKET,
        filename,
        ExtraArgs={"ContentType": content_type}
    )
    return f"{R2_PUBLIC}/{filename}"

# ---------------- HELPERS ----------------
def allowed_file(filename, allowed):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in allowed

def load_movies():
    if os.path.exists(MOVIES_JSON):
        with open(MOVIES_JSON, "r") as f:
            return json.load(f)
    return []

def save_movies(data):
    with open(MOVIES_JSON, "w") as f:
        json.dump(data, f, indent=2)

# ---------------- ROUTES ----------------
@app.route("/secure_movie/<int:movie_id>")
def secure_movie(movie_id):
    paid_cookie = request.cookies.get(f"movie_unlocked_{movie_id}")
    if paid_cookie != "true":
        return "You must pay to watch this movie", 403

    movie = next((m for m in load_movies() if m["id"] == movie_id), None)
    if not movie:
        return "Movie not found", 404

    local_path = os.path.join(MOVIE_FOLDER, os.path.basename(movie["movie"]))
    if not os.path.exists(local_path):
        return "Movie file missing", 404

    return send_file(local_path, as_attachment=False)

@app.route("/")
def index():
    return send_from_directory("static", "index.html")

@app.route("/add_movie")
def add_movie_page():
    return render_template("add_movies.html")

@app.route("/upload_movie", methods=["POST"])
def upload_movie():
    is_banner = request.form.get("is_banner") == "yes"
    poster = request.files.get("poster_file")
    if not poster or not allowed_file(poster.filename, ALLOWED_IMAGE_EXT):
        return jsonify({"status": "error", "message": "Poster image required"}), 400

    poster_name = secure_filename(poster.filename)
    poster_path = os.path.join(IMAGE_FOLDER, poster_name)
    poster.save(poster_path)
    poster_url = upload_to_r2(poster_path, poster_name, poster.content_type)

    if is_banner:
        with open(BANNER_JSON, "w") as f:
            json.dump({"banner": poster_url}, f, indent=2)
        return jsonify({"status": "success", "message": "Banner uploaded", "url": poster_url})

    # Movie upload
    title = request.form.get("title")
    category = request.form.get("category")
    preview = request.files.get("preview_file")
    movie = request.files.get("movie_file")

    if not all([title, category, preview, movie]):
        return jsonify({"status": "error", "message": "Missing movie fields"}), 400

    if not allowed_file(preview.filename, ALLOWED_MOVIE_EXT) or not allowed_file(movie.filename, ALLOWED_MOVIE_EXT):
        return jsonify({"status": "error", "message": "Invalid video format"}), 400

    preview_name = secure_filename(preview.filename)
    movie_name = secure_filename(movie.filename)
    preview_path = os.path.join(MOVIE_FOLDER, preview_name)
    movie_path = os.path.join(MOVIE_FOLDER, movie_name)
    preview.save(preview_path)
    movie.save(movie_path)

    preview_url = upload_to_r2(preview_path, preview_name, preview.content_type)
    movie_url = upload_to_r2(movie_path, movie_name, movie.content_type)

    movies = load_movies()
    new_id = max([m["id"] for m in movies], default=0) + 1
    movies.append({
        "id": new_id,
        "title": title,
        "category": category,
        "poster": poster_url,
        "preview": preview_url,
        "movie": movie_url
    })
    save_movies(movies)
    return jsonify({"status": "success", "message": "Movie uploaded successfully"})

# ---------------- API ----------------
@app.route("/movies")
def movies():
    return jsonify(load_movies())

@app.route("/player_preview")
def preview():
    return send_from_directory("static", "player_preview.html")

@app.route("/player")
def player():
    return send_from_directory("static", "player.html")

# ---------------- PAYMENTS ----------------
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
        "redirect_url": os.getenv("PAYMENT_CALLBACK_URL", "http://localhost:5001/payment_callback"),
        "customer": {"phonenumber": phone, "email": "customer@example.com", "name": "Movie Customer"},
        "customizations": {"title": "Classic Movies UG", "description": "Movie purchase"}
    }
    headers = {"Authorization": f"Bearer {FLUTTERWAVE_SECRET_KEY}"}
    return requests.post(f"{FLUTTERWAVE_BASE_URL}/payments", json=payload, headers=headers).json()

@app.route("/payment_callback")
def payment_callback():
    return "Payment checked"

@app.route("/static/<path:path>")
def static_files(path):
    return send_from_directory("static", path)

# ---------------- RUN FOR LOCAL TESTING ONLY ----------------
if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5001)  # local dev only; Render uses gunicorn
