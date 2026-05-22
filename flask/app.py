import sys
import os

# Add root directory to python path so we can import src modules
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from functools import wraps
import pandas as pd
import numpy as np
from scipy.sparse import load_npz
import hashlib
import json
import boto3
from botocore.exceptions import ClientError

from src.features.content_sys import content_based_recommand
from src.features.collaborative_sys import collaborative_recommand
from src.features.hybrid_sys import HybridRecommender
from youtube_service import search_youtube_video, global_search_youtube

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'sonic-nebula-secret-key-2024')

# --- DynamoDB User Store ---
def get_dynamodb_table():
    dynamodb = boto3.resource('dynamodb', region_name=os.environ.get('AWS_REGION', 'ap-southeast-2'))
    return dynamodb.Table('SonicNebulaUsers')

def load_user(username):
    try:
        table = get_dynamodb_table()
        response = table.get_item(Key={'username': username})
        return response.get('Item')
    except ClientError as e:
        print(f"DynamoDB error: {e}")
        # Fallback to local JSON if DynamoDB is unreachable (for local testing without AWS creds)
        users = _load_local_users()
        return users.get(username)

def save_user(username, display_name, password_hash):
    try:
        table = get_dynamodb_table()
        table.put_item(Item={
            'username': username,
            'display_name': display_name,
            'password': password_hash
        })
        return True
    except ClientError as e:
        print(f"DynamoDB error: {e}")
        # Fallback to local JSON
        users = _load_local_users()
        users[username] = {'display_name': display_name, 'password': password_hash}
        _save_local_users(users)
        return True

# --- Local JSON Fallback ---
USERS_FILE = os.path.join(os.path.dirname(__file__), 'users.json')

def _load_local_users():
    if os.path.exists(USERS_FILE):
        with open(USERS_FILE, 'r') as f:
            return json.load(f)
    return {}

def _save_local_users(users):
    with open(USERS_FILE, 'w') as f:
        json.dump(users, f, indent=2)

def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user' not in session:
            return redirect(url_for('signin'))
        return f(*args, **kwargs)
    return decorated_function

# --- Load Data Once on Startup ---
print("Loading data for Flask app...")
data_dir = os.path.join(os.path.dirname(__file__), '..', 'data', 'processed')
raw_dir = os.path.join(os.path.dirname(__file__), '..', 'data', 'raw')
models_dir = os.path.join(os.path.dirname(__file__), '..', 'models')

df_song_app = pd.read_csv(os.path.join(data_dir, 'Music_Info_app.csv'))
df_ui = pd.read_csv(os.path.join(data_dir, 'Music_Info_flask.csv'))

# Heavy matrices
transformed_data = load_npz(os.path.join(data_dir, 'df_transformed.npz'))
interaction_matrix = load_npz(os.path.join(data_dir, 'interaction_matrix.npz')).tocsr()
track_ids = np.load(os.path.join(models_dir, 'track_ids.npy'), allow_pickle=True)

# --- Compute Popular Songs from User Listening History ---
popular_track_ids = []
history_path = os.path.join(raw_dir, 'User_Listening_History.csv')
if os.path.exists(history_path):
    print("Computing popular songs from listening history...")
    df_history = pd.read_csv(history_path)
    popular_track_ids = df_history['track_id'].value_counts().head(20).index.tolist()
    print(f"Found {len(popular_track_ids)} popular tracks")

# Merge remaining songs from raw data that aren't in flask CSV
raw_csv_path = os.path.join(raw_dir, 'Music_Info.csv')
if os.path.exists(raw_csv_path):
    df_all_raw = pd.read_csv(raw_csv_path)
    missing = df_all_raw[~df_all_raw['track_id'].isin(df_ui['track_id'])].copy()
    if len(missing) > 0:
        missing['tags'] = missing['tags'].fillna('')
        missing['genre'] = missing['genre'].fillna('')
        def categorize(row):
            text = str(row.get('tags', '')).lower() + " " + str(row.get('genre', '')).lower()
            if 'pop' in text: return 'Pop'
            elif 'rock' in text: return 'Rock'
            elif 'electronic' in text or 'edm' in text or 'dance' in text: return 'Electronic'
            elif 'hip hop' in text or 'rap' in text: return 'Hip Hop'
            elif 'indie' in text or 'alternative' in text: return 'Indie'
            elif 'r&b' in text or 'rnb' in text or 'soul' in text: return 'R&B / Soul'
            elif 'jazz' in text or 'blues' in text: return 'Jazz / Blues'
            elif 'classical' in text: return 'Classical'
            else: return 'Other'
        missing['primary_category'] = missing.apply(categorize, axis=1)
        missing['duration'] = pd.to_datetime(missing['duration_ms'], unit='ms').dt.strftime('%M:%S')
        cols_needed = ['track_id', 'name', 'artist', 'year', 'duration_ms', 'primary_category', 'spotify_preview_url', 'tags', 'duration']
        for c in cols_needed:
            if c not in missing.columns:
                missing[c] = ''
        missing = missing[cols_needed]
        df_ui = pd.concat([df_ui, missing], ignore_index=True)

print(f"Total UI tracks: {len(df_ui)}")
print("Flask app data loaded successfully!")

# --- Cover Art ---
ABSTRACT_COVERS = [
    "https://lh3.googleusercontent.com/aida-public/AB6AXuADJ3RFdLbxS3AgscMEA1q3FScXxl2Cqjs5_J5DvZrW9KSr_WGXsYg-H5U7Z8Kp5mShbidG-D2vZO5me6Jx-Ynhh9gaCM923Ty5DYw92_JkgDaLpdlYg0euLooGzWevUyME_zAekOqM_uXhfeFFjA67olDO7iWPhMvALYou1036tMtAb3k1thCiiex7qNWNkwkEKi6KM70AbrRZ9tvKwGFvkj5Htj6PbXXRfUa5lhNU2STiasSfCVffNmMKeBehZEOqIcJFVGzSImCt",
    "https://lh3.googleusercontent.com/aida-public/AB6AXuCgXqFTP9TbA7YgJhfKMcbpzBJ42PDChaXuB914CL57AM9CraQWsJ7OvKsFCaL6YdYZQuiZfRV1UhZNCcdoXg_Dbr48vaUTOrSx_tmsyPCM35BMKw07uYaTcn-TRtgDtf0FNrgzqVJqU9U7ce8uOV1JwMImpfQFe8zlvNP57wERe8w1PoOOshv9nHv3tJPBodrhAc0LNmW0tV2hn1oIlermbWZ2MI0epuw41huvmGLjWgddgkBEy8-Om86lnjrSKNQ0w-S3Xaypm6Wb",
    "https://lh3.googleusercontent.com/aida-public/AB6AXuCFLpxyHTT2pzIjHQ6tACNRLgdtBxV8vOgAPUBmiSABR5UTfLLe4az0FnJWiOYu9EJShmNK9kDXZFlHPOGVrRgYvC_LlhCOsouyO9jpBw20ZCmJGCCTPyZZw7tnsiIXvQJIwpC8fFWulgmHGn8J34KgYtF-_ySLLo2fVPMH-K6m9gVWL3K0lTe0H1rB20ld3_BP0Y0XXITGvU_ZrWiFtKrzcmWG3bp5MlIKCzgGjr1e6FnZxRwrwjTfLKUa4cAhJnuAKHeJWX0qvk-h",
    "https://lh3.googleusercontent.com/aida-public/AB6AXuC5rwrB7NExkhMHmSCQHqUMkfynINker-J2gOi85Zg9OL5VVoaYBN1wYsAFE6u7A5jvW-5AvD4uXFvnuMpTiswpJidkZ4EuuhRtEa9gkUjIHCGhm60sTfXZBRB0TBHVl71qwSX8I_Xs_XUnEOpH5L1Sz3hsoMPMA9JBWkr15ObPyYCYv5xHQNYnrfok6L4oGe_9FUY1zU0-VB7xNu9txGGqrVT4gr9_S54uS1QC7QH_FdtehiuVahmSzBARDNs5QVpW_du-MVeQw86J",
    "https://lh3.googleusercontent.com/aida-public/AB6AXuDGSv0VBkOKaEA_wusMp-NK4Eyao-lcUDX8MqKYCPABPf2bmNXreCEu9119bEYaFlph9qju12eUhVjN9WaOXcOmaE1-Czt2ozJ9WwfXB9oHKdlI1m2YSkwz7g8JKQ2e4mO1KDbuSvUXD4hzzAUVtUmnYwKwj9fcxgtXFy46j_XJNHeenpkYK03pes-Hy80g7oC13WEcWjTlHi1NiY6MRHvG3hB8T8tGwq0Vd7qYNTtHz1efH0L91QezlDKiQm7q9CdZKo-XtLPhFBFF",
    "https://lh3.googleusercontent.com/aida-public/AB6AXuD9i4aLCtbKsGcyUyolnyC-iMr1OCsy5npJ2w20I9yh2CTSkYxOyVI8tjqj_rQaJZh91ADzCx250Zs17k7yxT7WRH6l_g1iuxjCUZnkH_bXU8J_Ge0prN9fhgEx6T1SW0ez-ZDewfoePRDI39zkPhJpERxVsa6CYqv10FF_F0MIi_1B3LyYK3fOW5GZ-FUEexmCKxYD3cQOMH5h3Yr8LbPIHJ1yg-hFi7vA39fA1vlqQSkqZmt-jh4P3ymcy6SaVDfWJr91vGW6mZR4",
    "https://lh3.googleusercontent.com/aida-public/AB6AXuAL_4A7Nc2UwNlyhjgoS6tuL1EaaVL9GuVSBkFBXuRrYzZzPoiy0TywEd4E86cR0eqFQJnCg9sijiDlJ9Ep3U9yqzGZSbdC5bFJoxFYBSoNWJlUEIFBryqWUKt0X0DZ_z3ugofnbz_DcDjytITqzy810B4WJs6a13dgm12b7inSR-bag4IxmUVqrkelEXF0mI1Svt3onXj2LAx_DW32axYbYOcugMzM2KoulixNM8zwQNm0wzgfYCweFbDV2CouQ8zMCCnGcQDj6ynM",
    "https://lh3.googleusercontent.com/aida-public/AB6AXuBggNEVUQP4mPqM4TGMPzxhHPljCVJajesMcvw6jmPQgic2rdcMsfuSZuk2BoG4h--WfGyvWEvK_SbLD0niLN0UlxpH3v9Fuo-8Si1yn9LYEGWSVfh8MYQMxY7t7pA7wxeoK7EBmbqajPoOncas2B9HkODcbRJIgQpf71bdKYmoeLwXSgZg6a0qVYETl0dT9jBd6sBpmyigCrhSGkdZbMlnVyqt85YFA7XuJlIUsbiyvk9BmRLgs08xIaQJIsRjhCkjhJ16-Z5DeNk8"
]

# Genre images for Explore page
GENRE_IMAGES = {
    'RnB': "https://picsum.photos/seed/music_rnb/800/800",
    'Rock': "https://picsum.photos/seed/music_rock/800/800",
    'Pop': "https://picsum.photos/seed/music_pop/800/800",
    'Metal': "https://picsum.photos/seed/music_metal/800/800",
    'Electronic': "https://picsum.photos/seed/music_electronic/800/800",
    'Jazz': "https://picsum.photos/seed/music_jazz/800/800",
    'Punk': "https://picsum.photos/seed/music_punk/800/800",
    'Country': "https://picsum.photos/seed/music_country/800/800",
    'Folk': "https://picsum.photos/seed/music_folk/800/800",
    'Reggae': "https://picsum.photos/seed/music_reggae/800/800",
    'Rap': "https://picsum.photos/seed/music_rap/800/800",
    'Blues': "https://picsum.photos/seed/music_blues/800/800",
    'New Age': "https://picsum.photos/seed/music_newage/800/800",
    'Latin': "https://picsum.photos/seed/music_latin/800/800",
    'World': "https://picsum.photos/seed/music_world/800/800"
}

def get_cover(track_id):
    return ABSTRACT_COVERS[hash(track_id) % len(ABSTRACT_COVERS)]

def get_popular_songs(n=10):
    """Get most popular songs based on listening history"""
    popular = df_ui[df_ui['track_id'].isin(popular_track_ids)].head(n).to_dict('records')
    for p in popular:
        p['cover'] = get_cover(p['track_id'])
    if len(popular) < n:
        # Fill remaining from random
        extra = df_ui.sample(n=n - len(popular)).to_dict('records')
        for e in extra:
            e['cover'] = get_cover(e['track_id'])
        popular.extend(extra)
    return popular

@app.context_processor
def inject_global_vars():
    # Provide a real track as the default playbar song instead "Welcome"
    default_track = get_popular_songs(1)[0]
    return dict(default_track=default_track)

# =================== AUTH ROUTES ===================

@app.route('/health')
def health_check():
    """Endpoint for AWS Target Group Health Checks"""
    return "OK", 200

@app.route('/signin', methods=['GET', 'POST'])
def signin():
    if 'user' in session:
        return redirect(url_for('index'))
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        user_data = load_user(username)
        if user_data and user_data.get('password') == hash_password(password):
            session['user'] = username
            session['display_name'] = user_data.get('display_name', username)
            return redirect(url_for('index'))
        else:
            return render_template('signin.html', error='Invalid username or password.')
    return render_template('signin.html')

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if 'user' in session:
        return redirect(url_for('index'))
    if request.method == 'POST':
        display_name = request.form.get('display_name', '').strip()
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        if not username or not password or not display_name:
            return render_template('signup.html', error='All fields are required.')
        
        user_data = load_user(username)
        if user_data:
            return render_template('signup.html', error='Username already exists.')
        
        save_user(username, display_name, hash_password(password))
        session['user'] = username
        session['display_name'] = display_name
        return redirect(url_for('index'))
    return render_template('signup.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('signin'))

# =================== MAIN ROUTES ===================

@app.route('/')
@login_required
def index():
    # Top Picks (8 songs)
    top_picks = df_ui[df_ui['spotify_preview_url'].notna() & (df_ui['spotify_preview_url'] != '')].sample(n=8).to_dict('records')
    for pick in top_picks:
        pick['cover'] = get_cover(pick['track_id'])
    
    # Genre lanes
    categories_to_show = ['Pop', 'Electronic', 'Rock', 'Indie', 'Hip Hop', 'R&B / Soul', 'Jazz / Blues', 'Classical']
    lanes = {}
    for cat in categories_to_show:
        cat_df = df_ui[(df_ui['primary_category'] == cat) & df_ui['spotify_preview_url'].notna() & (df_ui['spotify_preview_url'] != '')]
        if len(cat_df) == 0:
            continue
        sample_n = min(12, len(cat_df))
        rows = cat_df.sample(n=sample_n).to_dict('records')
        unique_rows = list({r['track_id']: r for r in rows}.values())[:8]
        for tr in unique_rows:
            tr['cover'] = get_cover(tr['track_id'])
        if unique_rows:
            lanes[cat] = unique_rows
    
    # Popular songs for right sidebar
    popular = get_popular_songs(10)
    
    return render_template('home.html', top_picks=top_picks, lanes=lanes, popular=popular)

@app.route('/search')
@login_required
def search():
    query = request.args.get('q', '').lower()
    if not query:
        return jsonify([])
    results = df_ui[(df_ui['name'].str.lower().str.contains(query, na=False)) | 
                    (df_ui['artist'].str.lower().str.contains(query, na=False))].head(15)
    return jsonify(results.to_dict('records'))

@app.route('/recommend/<track_id>')
@login_required
def recommend(track_id):
    track_info = df_ui[df_ui['track_id'] == track_id]
    if len(track_info) == 0:
        return "Track not found", 404
    track_info = dict(track_info.iloc[0])
    track_info['cover'] = get_cover(track_info['track_id'])
    song_name = track_info['name']
    artist_name = track_info['artist']
    
    # Get number of recommendations from query param
    k = int(request.args.get('k', 10))
    
    hybrid_recommender = HybridRecommender(
        song_name, artist_name, df_song_app, transformed_data,
        track_ids, interaction_matrix, 0.5, k, 0.5
    )
    try:
        recommendations = hybrid_recommender.get_recommendations()
    except Exception as e:
        print(f"Error getting recommendations: {e}")
        recommendations = content_based_recommand(song_name, df_song_app, transformed_data, k)
    
    rec_list = []
    for idx, row in recommendations.iterrows():
        ui_match = df_ui[df_ui['name'] == row['name']].head(1)
        duration = ui_match['duration'].values[0] if len(ui_match) > 0 else "0:00"
        tied_track_id = ui_match['track_id'].values[0] if len(ui_match) > 0 else track_id
        preview_url = ui_match['spotify_preview_url'].values[0] if len(ui_match) > 0 else ''
        rec_list.append({
            'name': row['name'], 'artist': row['artist'],
            'spotify_preview_url': preview_url if str(preview_url) != 'nan' else '',
            'duration': duration, 'track_id': tied_track_id,
            'cover': get_cover(tied_track_id)
        })
    return render_template('recommend.html', main_track=track_info, recommendations=rec_list, k=k)

@app.route('/api/youtube')
@login_required
def get_youtube_video():
    song = request.args.get('song')
    artist = request.args.get('artist')
    if not song:
        return jsonify({'error': 'Missing parameters'}), 400
    result = search_youtube_video(song, artist or '')
    if result:
        return jsonify(result)
    return jsonify({'error': 'Not found'}), 404

@app.route('/explore')
@login_required
def explore():
    """Explore page - shows genres from dataset"""
    genre_counts = df_ui['primary_category'].value_counts().to_dict()
    genres = []
    for genre_name, count in genre_counts.items():
        if genre_name == 'Other':
            continue
        genres.append({
            'name': genre_name,
            'count': count,
            'image': GENRE_IMAGES.get(genre_name, ABSTRACT_COVERS[0])
        })
    return render_template('explore.html', genres=genres)

@app.route('/genre/<genre_name>')
@login_required
def genre_page(genre_name):
    """Show all songs for a specific genre"""
    page = int(request.args.get('page', 1))
    per_page = 30
    genre_df = df_ui[df_ui['primary_category'] == genre_name]
    total = len(genre_df)
    total_pages = (total + per_page - 1) // per_page
    
    songs = genre_df.iloc[(page-1)*per_page : page*per_page].to_dict('records')
    for s in songs:
        s['cover'] = get_cover(s['track_id'])
    
    return render_template('genre.html', genre_name=genre_name, songs=songs,
                         page=page, total_pages=total_pages, total=total)

@app.route('/global_search')
@login_required
def global_search():
    """YouTube search for songs outside the dataset"""
    query = request.args.get('q', '')
    results = []
    if query:
        results = global_search_youtube(query)
    return render_template('global_search.html', query=query, results=results)

@app.route('/api/youtube_search')
@login_required
def api_youtube_search():
    query = request.args.get('q', '')
    if not query:
        return jsonify([])
    return jsonify(global_search_youtube(query))

@app.route('/settings')
@login_required
def settings():
    return render_template('settings.html')

@app.route('/profile')
@login_required
def profile():
    return render_template('profile.html')

if __name__ == '__main__':
    app.run(debug=True, port=5000)
