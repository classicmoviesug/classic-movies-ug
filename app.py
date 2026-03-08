from flask import Flask, request, jsonify, send_from_directory, render_template, redirect
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
MOVIES_KEY = "movies.json"
BANNER_KEY = "banner.json"

# ---------------- FOLDERS ----------------
MOVIE_FOLDER = "static/movies"
IMAGE_FOLDER = "static/images"
os.makedirs(MOVIE_FOLDER, exist_ok=True)
os.makedirs(IMAGE_FOLDER, exist_ok=True)

ALLOWED_MOVIE_EXT = {"mp4","mov","avi","mkv"}
ALLOWED_IMAGE_EXT = {"jpg","jpeg","png","gif"}

# ---------------- R2 CLIENT ----------------
s3 = boto3.client(
    "s3",
    endpoint_url=R2_ENDPOINT,
    aws_access_key_id=R2_ACCESS_KEY,
    aws_secret_access_key=R2_SECRET_KEY,
    region_name="auto"
)

# ---------------- R2 HELPERS ----------------
def upload_to_r2(local_path, filename, content_type):
    s3.upload_file(
        local_path,
        R2_BUCKET,
        filename,
        ExtraArgs={"ContentType": content_type}
    )
    return f"{R2_PUBLIC}/{filename}"

def load_movies():
    try:
        obj = s3.get_object(Bucket=R2_BUCKET, Key=MOVIES_KEY)
        return json.loads(obj["Body"].read())
    except s3.exceptions.NoSuchKey:
        return []
    except:
        return []

def save_movies(data):
    s3.put_object(
        Bucket=R2_BUCKET,
        Key=MOVIES_KEY,
        Body=json.dumps(data, indent=2),
        ContentType="application/json"
    )

# ---------------- HELPERS ----------------
def allowed_file(filename, allowed):
    return "." in filename and filename.rsplit(".",1)[1].lower() in allowed

# ---------------- ROUTES ----------------
@app.route("/")
def index():
    # Serve index.html if exists; else redirect to add_movie
    index_file = os.path.join("templates", "index.html")
    if os.path.exists(index_file):
        return render_template("index.html")
    else:
        return redirect("/add_movie")

@app.route("/add_movie")
def add_movie_page():
    return render_template("add_movies.html")

@app.route("/movies")
def movies():
    return jsonify(load_movies())

@app.route("/player_preview")
def preview():
    return send_from_directory("static","player_preview.html")

@app.route("/player")
def player():
    return send_from_directory("static","player.html")

# ---------------- UPLOAD ----------------
@app.route("/upload_movie",methods=["POST"])
def upload_movie():
    is_banner = request.form.get("is_banner") == "yes"
    poster = request.files.get("poster_file")
    if not poster or not allowed_file(poster.filename, ALLOWED_IMAGE_EXT):
        return jsonify({"status":"error","message":"Poster image required"}),400
    poster_name = secure_filename(poster.filename)
    poster_path = os.path.join(IMAGE_FOLDER,poster_name)
    poster.save(poster_path)
    poster_url = upload_to_r2(poster_path,poster_name,poster.content_type)

    # ---------- BANNER ----------
    if is_banner:
        s3.put_object(
            Bucket=R2_BUCKET,
            Key=BANNER_KEY,
            Body=json.dumps({"banner":poster_url},indent=2),
            ContentType="application/json"
        )
        return jsonify({"status":"success","message":"Banner uploaded","url":poster_url})

    # ---------- MOVIE ----------
    title = request.form.get("title")
    category = request.form.get("category")
    preview = request.files.get("preview_file")
    movie = request.files.get("movie_file")
    if not all([title,category,preview,movie]):
        return jsonify({"status":"error","message":"Missing movie fields"}),400
    if not allowed_file(preview.filename,ALLOWED_MOVIE_EXT) or not allowed_file(movie.filename,ALLOWED_MOVIE_EXT):
        return jsonify({"status":"error","message":"Invalid video format"}),400

    preview_name = secure_filename(preview.filename)
    movie_name = secure_filename(movie.filename)
    preview_path = os.path.join(MOVIE_FOLDER,preview_name)
    movie_path = os.path.join(MOVIE_FOLDER,movie_name)
    preview.save(preview_path)
    movie.save(movie_path)

    preview_url = upload_to_r2(preview_path,preview_name,preview.content_type)
    movie_url = upload_to_r2(movie_path,movie_name,movie.content_type)

    movies = load_movies()
    new_id = max([m["id"] for m in movies], default=0) + 1
    movies.append({
        "id":new_id,
        "title":title,
        "category":category,
        "poster":poster_url,
        "preview":preview_url,
        "movie":movie_url
    })
    save_movies(movies)
    return jsonify({"status":"success","message":"Movie uploaded successfully"})

# ---------------- PAYMENTS ----------------
@app.route("/pay",methods=["POST"])
def pay():
    data = request.get_json(force=True)
    phone = data.get("phone")
    amount = data.get("amount")
    movie_id = data.get("movie_id")
    tx_ref = f"movie_{movie_id}_{phone}"
    payload = {
        "tx_ref":tx_ref,
        "amount":amount,
        "currency":"UGX",
        "payment_options":"mobilemoneyuganda",
        "redirect_url":"https://classic-movies-ug-4.onrender.com/payment_callback",
        "customer":{
            "phonenumber":phone,
            "email":"customer@example.com",
            "name":"Movie Customer"
        },
        "customizations":{
            "title":"Classic Movies UG",
            "description":"Movie purchase"
        }
    }
    headers = {"Authorization":f"Bearer {FLUTTERWAVE_SECRET_KEY}"}
    return requests.post(f"{FLUTTERWAVE_BASE_URL}/payments",json=payload,headers=headers).json()

@app.route("/payment_callback")
def payment_callback():
    return "Payment checked"

# ---------------- STATIC ----------------
@app.route("/static/<path:path>")
def static_files(path):
    return send_from_directory("static",path)

# ---------------- SERVER ----------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT",5001))
    app.run(host="0.0.0.0",port=port)
