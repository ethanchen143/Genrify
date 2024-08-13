from flask import Flask, redirect, request, session, url_for, render_template,jsonify
from spotipy.oauth2 import SpotifyOAuth
import spotipy
from datetime import datetime
import json
import numpy as np
import os
import threading
from flask_session import Session

app = Flask(__name__)

app.config['SESSION_TYPE'] = 'filesystem'
app.config['SESSION_FILE_DIR'] = './flask_session/'  # Ensure this directory exists
app.config['SESSION_FILE_THRESHOLD'] = 100  # Max number of files before cleanup
Session(app)

REDIRECT_URL = f"https://www.genrify.us/callback"
SCOPE = 'user-library-read playlist-read-private playlist-modify-private playlist-modify-public'

@app.route('/')
def index():
    logged_in = 'token_info' in session and 'access_token' in session['token_info']
    sp_oauth = SpotifyOAuth(
        client_id=os.getenv('CLIENT_ID'),
        client_secret=os.getenv('CLIENT_SECRET'),
        redirect_uri=REDIRECT_URL,
        scope=SCOPE,
    )
    auth_url = sp_oauth.get_authorize_url()
    return render_template('index.html', login_url=auth_url, logged_in=logged_in)

@app.route('/callback')
def callback():
    sp_oauth = SpotifyOAuth(
        client_id=os.getenv('CLIENT_ID'),
        client_secret=os.getenv('CLIENT_SECRET'),
        redirect_uri=REDIRECT_URL,
        scope=SCOPE,
    )
    token_info = sp_oauth.get_access_token(request.args.get('code'))
    session['token_info'] = token_info
    access_token = token_info['access_token']
    if sp_oauth.is_token_expired(token_info):
        token_info = sp_oauth.refresh_access_token(token_info['refresh_token'])
        session['token_info'] = token_info
        access_token = token_info['access_token']
    sp = spotipy.Spotify(auth=access_token)
    user_profile = sp.current_user()
    session['user_id'] = user_profile['id']
    return redirect(url_for('index'))

@app.route('/logout')
def logout():
    session.pop('token_info', None)
    session.clear()
    return redirect('https://accounts.spotify.com/en/logout')

def simplify_data(data):
    return [
        {
            'added_at': entry['added_at'][:10],
            'album_name': track['album']['name'],
            'album_release_date': track['album']['release_date'],
            'artist_names': ', '.join(artist['name'] for artist in track['artists']),
            'artist_id': track['artists'][0]['id'],
            'track_name': track['name'],
            'track_popularity': track['popularity'],
            'id': track['id']
        } for entry in data for track in [entry['track']]
    ]

def enrich_data(data, sp):
    chunk_size = 50  # Spotify API batch limit
    for i in range(0, len(data), chunk_size):
        track_chunk = data[i:i+chunk_size]
        artist_ids = [track['artist_id'] for track in track_chunk]
        artists = sp.artists(artist_ids)['artists']
        features = sp.audio_features([track['id'] for track in track_chunk])
        for track, artist, feature in zip(track_chunk, artists, features):
            track['genres'] = artist.get('genres', [])
            feature_data = {k: feature.get(k, 0) for k in [
                'acousticness', 'danceability', 'energy', 'instrumentalness', 
                'liveness', 'loudness', 'speechiness', 'tempo', 'valence', 
                'key', 'mode', 'time_signature']}
            track.update(feature_data)
        
def bg_get_tracks(user_id,sp):
    cache_file = f"./cache/{user_id}.json"
    if not os.path.exists(cache_file):
        offset = 0
        limit = 50
        all_tracks = []
        while True:
            results = sp.current_user_saved_tracks(limit=limit, offset=offset)
            all_tracks.extend(results['items'])
            if results['next'] is None:
                break
            offset += limit
        with open(cache_file, 'w') as f:
            json.dump(all_tracks, f)
    
def bg_analyze_tracks(user_id,sp):
    ana_file = f"./cache/{user_id}_AN.json"
    if not os.path.exists(ana_file):
        cache_file = f"./cache/{user_id}.json"
        if not os.path.exists(cache_file):
            bg_get_tracks(user_id, sp)
        with open(cache_file, 'r') as f:
            tracks = json.load(f)
        data = simplify_data(tracks)
        enrich_data(data, sp)
        from genre_map import convert
        for track in data:
            processed = list(set(convert(g) for g in track['genres'])) # Niche Genres-> Mainstream Genres
            if 'Others' in processed and len(processed) != 1:
                processed.remove('Others')
            track['genres'] = processed
        with open(ana_file, 'w') as f:
            json.dump(data, f)
            
    from analysis import analyze
    an_text_file = f"./cache/{user_id}_AN-Text.json"
    if not os.path.exists(an_text_file):
        with open(ana_file, 'r') as f:
            data = json.load(f)
        ana_text = analyze(data)
        with open(an_text_file, 'w') as f:
            json.dump(ana_text, f)

def bg_organize_tracks(user_id, sp):
    bg_analyze_tracks(user_id, sp)
    ana_file = f"./cache/{user_id}_AN.json"
    with open(ana_file, 'r') as f:
        data = json.load(f)
    
    # Initialize a dictionary to hold tracks categorized by decade and genre
    categorized_tracks = {}

    for track in data:
        # Get the genre
        order = ["Soundtracks", "Classical", "Experimental", "Jazz", "Country/Folk", "Funk", "Rock", "RnB/Soul", "Indie", "Hip-Hop", "Electronic", "Pop", "Others"]
        order = [genre for genre in order if genre in track['genres']]
        genre = order[0] if order else 'Others'
        
        # Unclassified Genre
        if genre == 'Others':
            continue
        
        # Get the decade
        try:
            if len(track['album_release_date']) == 10:
                year = datetime.strptime(track['album_release_date'], '%Y-%m-%d').year
            elif len(track['album_release_date']) == 7:
                year = datetime.strptime(track['album_release_date'], '%Y-%m').year
            else:
                year = datetime.strptime(track['album_release_date'], '%Y').year
        except:
            year = datetime.now().year
        
        decade = (year // 10) * 10

        # Create a key based on genre and decade
        key = f"{decade}s {genre}"
        
        if key not in categorized_tracks:
            categorized_tracks[key] = []
        
        categorized_tracks[key].append(track['id'])

    # Prepare to merge small playlists
    keys_sorted = sorted(categorized_tracks.keys())
    merged_categorized_tracks = {}

    i = 0
    while i < len(keys_sorted):
        key = keys_sorted[i]
        if len(categorized_tracks[key]) < 10:
            # Attempt to merge with next decade
            if i + 1 < len(keys_sorted):
                next_key = keys_sorted[i + 1]
                if key.split(' ')[1] == next_key.split(' ')[1]:  # Same genre
                    # Merge tracks with next decade
                    combined_key = f"{key.split(' ')[0]}_{next_key.split(' ')[0]}s {key.split(' ')[1]}"
                    merged_categorized_tracks[combined_key] = categorized_tracks[key] + categorized_tracks[next_key]
                    i += 2
                    continue
            
            # Attempt to merge with previous decade
            if i > 0:
                prev_key = keys_sorted[i - 1]
                if key.split(' ')[1] == prev_key.split(' ')[1]:  # Same genre
                    combined_key = f"{prev_key.split(' ')[0]}_{key.split(' ')[0]}s {key.split(' ')[1]}"
                    merged_categorized_tracks[combined_key] = categorized_tracks[prev_key] + categorized_tracks[key]
                    del merged_categorized_tracks[prev_key]
                    i += 1
                    continue
        
        # If no merge was done, just add the current key to the merged list
        if key not in merged_categorized_tracks:
            merged_categorized_tracks[key] = categorized_tracks[key]
        i += 1

    # Create playlists based on the merged categories
    playlist_ids = {}
    for key, tracks in merged_categorized_tracks.items():
        # Format the playlist name as Genrified_80s_RnB or Genrified_70_80s_RnB for merged decades
        decades, genre = key.split(' ', 1)
        playlist_name = f'Genrified_{decades.replace(" ", "_")}_{genre.replace("/", "_")}'
        playlist = sp.user_playlist_create(user=user_id, name=playlist_name, public=False)
        playlist_ids[key] = playlist['id']
        
        # Add tracks to the playlists
        batch_size = 50  # Spotify Rate Limit
        for i in range(0, len(tracks), batch_size):
            batch_tracks = tracks[i:i + batch_size]
            sp.playlist_add_items(playlist_ids[key], batch_tracks)

def bg_delete_playlists(user_id,sp):
    playlists = sp.current_user_playlists()
    to_delete = []
    while playlists:
        for playlist in playlists['items']:
            if playlist['name'].startswith('Genrify'):
                to_delete.append(playlist['id'])
        if playlists['next']:
            playlists = sp.next(playlists)
        else:
            playlists = None
    batch_size = 100 
    for i in range(0, len(to_delete), batch_size):
        batch = to_delete[i:i + batch_size]
        for playlist_id in batch:
            sp.user_playlist_unfollow(user_id, playlist_id)
                    

def background_job(user_id, token_info, job_type):
    sp = spotipy.Spotify(auth=token_info['access_token'])
    status_file = f"./cache/{user_id}_status.json"
    try:
        with open(status_file, 'w') as f:
            json.dump('pending', f)
        if job_type == 'get_tracks':
            bg_get_tracks(user_id, sp)                
        elif job_type == 'analyze_tracks':
            bg_analyze_tracks(user_id, sp)                
        elif job_type == 'organize_tracks':
            bg_organize_tracks(user_id, sp)
        elif job_type == 'delete_playlists':
            bg_delete_playlists(user_id, sp)
        with open(status_file, 'w') as f:
            json.dump('completed', f)
    except Exception as e:
        with open(status_file, 'w') as f:
            json.dump(f'error: {str(e)}', f)

@app.route('/start_task/<job_type>')
def start_task(job_type):
    if 'token_info' not in session or 'access_token' not in session['token_info']:
        return redirect(url_for('index'))
    
    user_id = session['user_id']
    token_info = session['token_info']
    status_file = f"./cache/{user_id}_status.json"
    
    with open(status_file, 'w') as f:
        json.dump('pending', f)
    
    thread = threading.Thread(target=background_job, args=(user_id, token_info, job_type))
    thread.start()
    return render_template('waiting.html', job_type=job_type)

@app.route('/get_tracks')
def get_tracks():
    return redirect(url_for('start_task', job_type='get_tracks'))

@app.route('/analyze_tracks')
def analyze_tracks():
    return redirect(url_for('start_task', job_type='analyze_tracks'))

@app.route('/organize_tracks')
def organize_tracks():
    return redirect(url_for('start_task', job_type='organize_tracks'))

@app.route('/delete_playlists')
def delete_playlists():
    return redirect(url_for('start_task', job_type='delete_playlists'))

@app.route('/check_status')
def check_status():
    user_id = session['user_id']
    cache_file = f"./cache/{user_id}_status.json"
    with open(cache_file, 'r') as f:
        status = json.load(f)
    if status == 'completed':
        job_type = request.args.get('job_type')
        print(f'checking status, job_type: {job_type}')
        return jsonify({'status': 'completed', 'job_type': job_type})
    elif 'error' in status:
        return jsonify({'status': 'error', 'details': status})
    else:
        return jsonify({'status': 'pending'})

@app.route('/results')
def results():
    user_id = session['user_id']
    job_type = request.args.get('type')
    
    if job_type == 'get_tracks':
        cache_file = f"./cache/{user_id}.json"
        if os.path.exists(cache_file):
            with open(cache_file, 'r') as f:
                all_tracks = json.load(f)
            return render_template('dashboard.html', tracks=all_tracks)
        else:
            return render_template('message.html', text="No tracks found.")
    elif job_type == 'analyze_tracks':
        ana_file = f"./cache/{user_id}_AN.json"
        an_text_file = f"./cache/{user_id}_AN-Text.json"
        if os.path.exists(ana_file) and os.path.exists(an_text_file):
            with open(ana_file, 'r') as f:
                data = json.load(f)
            with open(an_text_file, 'r') as f:
                ana_text = json.load(f)
            return render_template('analytics.html', data=data, text=ana_text)
        else:
            return render_template('message.html', text="Analysis data not found.")
    elif job_type == 'organize_tracks':
        return render_template('message.html', text="Genrify_Playlists created, check them out on your Spotify app!")
    elif job_type == 'delete_playlists':
        return render_template('message.html', text="Genrify_Playlists deleted. Try generating again!")
    else:
        return render_template('message.html', text=f"Invalid job type: {job_type}")

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=8080)