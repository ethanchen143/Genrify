from flask import Flask, redirect, request, session, url_for, render_template
from spotipy.oauth2 import SpotifyOAuth
import spotipy
from datetime import timedelta,datetime
import redis
import json
import time
from uuid import uuid4
import numpy as np
import os

app = Flask(__name__)
app.config['SESSION_COOKIE_NAME'] = 'spotify_login_session'
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['REMEMBER_COOKIE_SECURE'] = False
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(minutes = 30)  # Sessions expire
app.secret_key = os.getenv('SECRET_KEY','secret_key')

REDIRECT_URL = f"https://www.genrify.us/callback"
SCOPE = 'user-library-read playlist-read-private playlist-modify-private playlist-modify-public'

batch_size = 50
from urllib.parse import urlparse
redis_url = urlparse(os.getenv('REDISCLOUD_URL'))
redis_client = redis.Redis(host=redis_url.hostname, port=redis_url.port, password=redis_url.password)


@app.after_request
def add_header(response):
    response.cache_control.no_store = True
    return response

@app.route('/')
def index():
    session['uuid'] = str(uuid4())
    logged_in = 'token_info' in session and 'access_token' in session['token_info']
    sp_oauth = SpotifyOAuth(
        client_id=os.getenv('SPOTIPY_CLIENT_ID'),
        client_secret=os.getenv('SPOTIPY_CLIENT_SECRET'),
        redirect_uri=REDIRECT_URL,
        scope=SCOPE,
        cache_path=f"cache/.cache-{session['uuid']}"
    )
    auth_url = sp_oauth.get_authorize_url()
    return render_template('index.html', login_url=auth_url, logged_in=logged_in)

@app.route('/callback')
def callback():
    session['uuid'] = str(uuid4())
    sp_oauth = SpotifyOAuth(
        client_id=os.getenv('SPOTIPY_CLIENT_ID'),
        client_secret=os.getenv('SPOTIPY_CLIENT_SECRET'),
        redirect_uri=REDIRECT_URL,
        scope=SCOPE,
        cache_path=f"cache/.cache-{session['uuid']}"
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
    user_id = session.get('user_id')
    if user_id:
        redis_client.delete(user_id) 
        redis_client.delete(user_id + 'AN')
        redis_client.delete(user_id + 'AN-text')
    session.pop('token_info', None)
    session.clear()
    return redirect('https://accounts.spotify.com/en/logout')

@app.route('/get_tracks')
def get_tracks():
    if 'token_info' not in session or 'access_token' not in session['token_info']:
        return redirect(url_for('index'))
    sp = spotipy.Spotify(auth=session['token_info']['access_token'])
    user_id = session['user_id']
    need_to_refresh = True
    if redis_client.exists(user_id):
        all_tracks = redis_client.get(user_id)
        all_tracks = json.loads(all_tracks.decode('utf-8'))  # Decode and deserialize
        if all_tracks[:batch_size] == sp.current_user_saved_tracks(limit=batch_size, offset=0)['items']:
            need_to_refresh = False
    if need_to_refresh:
        offset = 0
        limit = batch_size
        all_tracks = []
        while True:
            results = sp.current_user_saved_tracks(limit=limit, offset=offset)
            all_tracks.extend(results['items'])
            if results['next'] is None:
                break
            offset += limit
        redis_client.set(user_id, json.dumps(all_tracks))  # Serialize and store
    return render_template('dashboard.html', tracks=all_tracks)
    
@app.route('/analyze_tracks')
def analyze_tracks():
    user_id = session['user_id']
    ana_id = user_id + 'AN'
    need_to_refresh = True
    if redis_client.exists(ana_id):
        data = redis_client.get(ana_id)
        data = json.loads(data.decode('utf-8'))
        need_to_refresh = False
    if need_to_refresh:
        tracks = redis_client.get(user_id)
        tracks = json.loads(tracks.decode('utf-8'))
        def simplify_data(data):
            simplified_data = []
            for entry in data:
                track_info = entry['track']
                simplified_track = {
                    'added_at': entry['added_at'][:10],
                    'album_name': track_info['album']['name'],
                    'album_release_date': track_info['album']['release_date'],
                    'artist_names': ', '.join(artist['name'] for artist in track_info['artists']),
                    'artist_id': track_info['artists'][0]['id'],
                    'track_name': track_info['name'],
                    'track_popularity': track_info['popularity'],
                    'id': track_info['id']
                }
                simplified_data.append(simplified_track)
            return simplified_data
        
        data = simplify_data(tracks)
        sp = spotipy.Spotify(auth=session['token_info']['access_token'])
        
        # This is too slow - delete - get country, audio analysis (pitch/timbre)
        # for idx,song in enumerate(data):
        #     # Get Country
        #     import musicbrainzngs
        #     musicbrainzngs.set_useragent("MusicDNA", "1.0", "ethanchen143@gmail.com")
        #     def get_artist_country(artist_name):
        #         result = musicbrainzngs.search_artists(artist=artist_name)
        #         for artist in result['artist-list']:
        #             if 'country' in artist:
        #                 return artist['country']
        #         return "US"
        #     if song['artist_names']:
        #         try:
        #             data[idx]['origin'] = get_artist_country(song['artist_names'][0])
        #         except Exception as e:
        #             data[idx]['origin'] = 'US'
        #     else:
        #         data[idx]['origin'] = 'US'
        #     # Get Audio Analysis and Handle Rate Limits
        #     try:
        #         analysis = sp.audio_analysis(song['id'])
        #     except spotipy.exceptions.SpotifyException as e:
        #         print('Rate Limit Audio Analysis')
        #         if e.http_status == 429:
        #             print(f'retrying: after 60 seconds')
        #             time.sleep(60)
        #             analysis = sp.audio_analysis(song['id'])
        #         else:
        #             data[idx]['pitch'] = [0]*12
        #             data[idx]['timbre'] = [0]*12
        #             continue
                
        #     all_pitches = [segment['pitches'] for segment in analysis['segments']]
        #     mean_pitches = np.mean(all_pitches, axis=0).tolist()
        #     data[idx]['pitch'] = mean_pitches
        #     all_timbre = [segment['timbre'] for segment in analysis['segments']]
        #     mean_timbre = np.mean(all_timbre, axis=0).tolist()
        #     data[idx]['timbre'] = mean_timbre
            
        # Get Genre and Audio Features
        for i in range(0,len(data),batch_size):
            ids = [track['artist_id'] for track in data[i:i+batch_size]]
            try:
                artists = sp.artists(ids)['artists']
            except spotipy.exceptions.SpotifyException as e:
                print('Rate Limit')
                if e.http_status == 429:
                    print(f'retrying: after 60 seconds')
                    time.sleep(60)
                    artists = sp.artists(ids)['artists']
            
            for track, artist in zip(data[i:i+batch_size], artists):
                track['genres'] = artist.get('genres', [])
                
            ids = [track['id'] for track in data[i:i+batch_size]]
            try:
                features = sp.audio_features(ids)
            except spotipy.exceptions.SpotifyException as e:
                print('Rate Limit')
                if e.http_status == 429:
                    print(f'retrying: after 60 seconds')
                    time.sleep(60)
                    features = sp.audio_features(ids)
                    
            for track, feature in zip(data[i:i+batch_size], features):
                track['acousticness'] = feature['acousticness']
                track['danceability'] = feature['danceability']
                track['energy'] = feature['energy']
                track['instrumentalness'] = feature['instrumentalness']
                track['liveness'] = feature['liveness']
                track['loudness'] = feature['loudness']
                track['speechiness'] = feature['speechiness']
                track['tempo'] = feature['tempo']
                track['valence'] = feature['valence']
                track['key'] = feature['key']
                track['mode'] = feature['mode']
                track['time_signature'] = feature['time_signature']

        redis_client.set(ana_id, json.dumps(data))
    
    # Get Cleaned Genres
    from genre_map import convert
    import copy
    prepared_data = copy.deepcopy(data)
    for track in prepared_data:
        processed = []
        for g in track['genres']:
            processed.append(convert(g))
        processed = list(set(processed))
        if 'Others' in processed and len(processed) != 1:
            processed.remove('Others')
        track['genres'] = processed

    # Analyze data->text, with cacheing
    from analysis import analyze
    an_text_id = session['user_id']+'AN-Text'
    if redis_client.exists(an_text_id):
        ana_text = redis_client.get(an_text_id)
        ana_text = json.loads(ana_text.decode('utf-8'))
    else:
        ana_text = analyze(prepared_data)
        redis_client.set(an_text_id, json.dumps(ana_text))
    return render_template('analytics.html',data = prepared_data, text = ana_text)

import faiss
def kmeans(data, k, max_iterations=1000):
    num_clusters = k
    dimension = data.shape[1]
    initial_centroids = np.random.rand(num_clusters, dimension).astype('float32')
    kmeans = faiss.Kmeans(dimension, num_clusters, niter=max_iterations, verbose=True)
    kmeans.centroids = initial_centroids  # Initialize centroids
    kmeans.train(data)
    D, I = kmeans.index.search(data, 1)
    return I.flatten(), kmeans.centroids

@app.route('/organize_tracks')
def organize_tracks():
    # dates, timbre, genre, popularity, danceability, energy, acousticness, liveness
    dates_weight = 5
    genre_weights = 1 # 20-point difference between genres
    popular_weights = 2.5
    valence_weights = 2.5
    dance_weights = 2.5
    energy_weights = 2.5
    acoustic_weights = 2.5
    live_weights = 2.5
    # timbre_weights = 1 # 12-point system
    
    sp = spotipy.Spotify(auth=session['token_info']['access_token'])
    user_id = session['user_id']
    ana_id = user_id + 'AN'
    if not redis_client.exists(ana_id):
        analyze_tracks()

    data = redis_client.get(ana_id)
    data = json.loads(data.decode('utf-8'))
    
    # Date and Timbre
    data = np.array(data)
    dates = []
    # timbres = []
    for d in data:
        if len(d['album_release_date']) == 10:
            dates.append(datetime.strptime(d['album_release_date'],'%Y-%m-%d'))
        elif len(d['album_release_date']) == 7:
            dates.append(datetime.strptime(d['album_release_date'],'%Y-%m'))
        else:
            dates.append(datetime.strptime(d['album_release_date'],'%Y'))
        # timbres.append(d['timbre'])
    min_date = min(dates)
    max_date = max(dates)
    dates = [((date - min_date).total_seconds() / (max_date - min_date).total_seconds())*dates_weight for date in dates]
    
    # timbres = np.array(timbres)
    # min_vals = timbres.min(axis=0)
    # max_vals = timbres.max(axis=0)
    # normalized_timbres = (timbres - min_vals) / (max_vals - min_vals)
    
    # Genre
    genre_score = {  
                "Soundtracks": 0,
                "Classical": 10,
                "Jazz": 20,
                "Country/Folk": 40,
                "RnB/Soul": 60,
                "Pop": 80,
                "Funk": 100,
                "Indie": 120,
                "Rock": 140,
                "Hip-Hop": 160,
                "Electronic": 180,
                "Experimental": 200,
                "Others": 250, # let genre dominate
            }
    
    from genre_map import convert
    for track in data:
        processed = []
        for g in track['genres']:
            processed.append(convert(g))
        processed = list(set(processed))
        if 'Others' in processed and len(processed) > 1:
            processed.remove('Others')
        if not processed:
            track['genres'] = 'Others'
        order = ["Soundtracks","Classical","Experimental","Jazz","Country/Folk","Funk","Indie","Rock","RnB/Soul","Hip-Hop","Electronic","Pop","Others"]
        # Get the most niche genre
        for genre in order:
            if genre in processed:
                track['genres'] = genre
                break
    genres = [genre_score[d['genres']]*genre_weights for d in data]
    genres = [0 if np.isnan(x) else x for x in genres]
     
    popularities = [d['track_popularity']/100 for d in data]

    # Populate clean_data
    clean_data = []
    for idx in range(len(data)):
        tmp = []
        tmp.append(dates[idx])
        tmp.append(genres[idx])
        tmp.append(popularities[idx]*popular_weights)
        tmp.append(data[idx]['valence']*valence_weights)
        tmp.append(data[idx]['danceability']*dance_weights)
        tmp.append(data[idx]['energy']*energy_weights)
        tmp.append(data[idx]['acousticness']*acoustic_weights)
        tmp.append(data[idx]['liveness']*live_weights)
        # tmp.extend(normalized_timbres[idx])
        clean_data.append(tmp)
    clean_data = np.array(clean_data)
    
    # around 30 songs / Playlists
    num_k = len(data)//30+1
    cluster_ids, centroids = kmeans(clean_data, k=num_k)
    
    # Debug Print
    # np.set_printoptions(threshold=np.inf)
    # for i in range(len(centroids)):
    #     print(f'Playlist {i+1}: {centroids[i]}')
    
    from collections import defaultdict
    cluster_tracks = defaultdict(list)
    for idx, track in enumerate(data):
        cluster_id = int(cluster_ids[idx])  
        cluster_tracks[cluster_id].append(track['id'])

    def custom_name(cluster_id):
        avg_date = min_date + (centroids[cluster_id][0] / dates_weight)*(max_date-min_date)
        year = avg_date.strftime("%Y")
        genre_num = int(centroids[cluster_id][1])
        closest_genre= None
        min_difference = float('inf')
        for k,v in genre_score.items():
            difference = abs(genre_num - v)
            if difference < min_difference:
                min_difference = difference
                closest_genre = k
        res = f"{year}'s {closest_genre}"
        return res
        
    playlist_ids = {}
    for cluster_id in cluster_tracks:
        playlist_name = f'Genrify_{cluster_id + 1}_{custom_name(cluster_id)}'
        playlist = sp.user_playlist_create(user=user_id, name=playlist_name, public=False)
        playlist_ids[cluster_id] = playlist['id']

    for cluster_id, tracks in cluster_tracks.items():
        if len(tracks) > 50:
            print(f'Large Playlist {cluster_id+1}: Size {len(tracks)}')
            batch_size = 50
            for i in range(0, len(tracks), batch_size):
                batch_tracks = tracks[i:i + batch_size]
                sp.playlist_add_items(playlist_ids[cluster_id], batch_tracks)
        else:
            if tracks:
                sp.playlist_add_items(playlist_ids[cluster_id], tracks)
                
    return render_template('message.html',text = f"{num_k} playlists created, check them out on your Spotify app!")


@app.route('/delete_playlists')
def delete_user_playlists():
    sp = spotipy.Spotify(auth=session['token_info']['access_token'])
    user_id = session['user_id']
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

    # Batch delete playlists
    batch_size = 100 
    total_deleted = 0

    for i in range(0, len(to_delete), batch_size):
        batch = to_delete[i:i + batch_size]
        for playlist_id in batch:
            sp.user_playlist_unfollow(user_id, playlist_id)
        total_deleted += len(batch)

    return render_template('message.html',text = f"{total_deleted} playlists deleted, you can log out and generate again.")

# if __name__ == '__main__':
#     app.run(debug=True, port=port_num)