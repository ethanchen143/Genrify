import numpy as np
import requests
from collections import Counter

def get_bio(artist_name):
    last_api = '9ba91375b3fa52ccffec116c0656f908'
    url = f"http://ws.audioscrobbler.com/2.0/?method=artist.getinfo&artist={artist_name}&api_key={last_api}&format=json"
    response = requests.get(url)
    if response.status_code == 200:
        data = response.json()
        if 'artist' in data and 'bio' in data['artist']:
            bio_summary = data['artist']['bio']['summary']
            return bio_summary
    return None

def get_tags(artist_name):
    last_api = '9ba91375b3fa52ccffec116c0656f908'
    url = f"http://ws.audioscrobbler.com/2.0/?method=artist.gettoptags&artist={artist_name}&api_key={last_api}&format=json"
    response = requests.get(url)
    if response.status_code == 200:
        data = response.json()
        if 'toptags' in data and 'tag' in data['toptags']:
            top_tags = [tag['name'] for tag in data['toptags']['tag']][:10] # Get Top 10 Tags
            return top_tags
    return None

import anthropic
import os

def analyze(data):
    print(data[0])
    genres = [y for x in data for y in x['genres']]
    counter = Counter(genres)
    fav_genres = counter.most_common(5)
    artists = []
    for track in data:
        artist_names = track['artist_names'].split(',')
        artists.extend(artist_names)
    counter = Counter(artists)
    fav_artists = counter.most_common(10)
    top_genres = ', '.join([genre[0] for genre in fav_genres])
    top_artists = ', '.join([artist[0] for artist in fav_artists])
    top_tags = ''
    for artist in fav_artists:
        tags = get_tags(artist[0])
        if tags:  # Check if tags is not None
            top_tags += f'{artist[0]}: '
            top_tags += ', '.join(tags)
            top_tags += '\n'
    
    popular = np.array([x['track_popularity'] for x in data])
    pop_mean = np.mean(popular)
    pop_median = np.median(popular)
    pop_std = np.std(popular)

    tempo = np.array([x['tempo'] for x in data])
    tempo_mean = np.mean(tempo)
    tempo_median = np.median(tempo)
    tempo_std = np.std(tempo)

    valence = np.array([x['valence'] for x in data])
    valence_mean = np.mean(valence)
    valence_median = np.median(valence)
    valence_std = np.std(valence)

    acousticness = np.array([x['acousticness'] for x in data])
    acousticness_mean = np.mean(acousticness)
    acousticness_median = np.median(acousticness)
    acousticness_std = np.std(acousticness)

    energy = np.array([x['energy'] for x in data])
    energy_mean = np.mean(energy)
    energy_median = np.median(energy)
    energy_std = np.std(energy)

    danceability = np.array([x['danceability'] for x in data])
    danceability_mean = np.mean(danceability)
    danceability_median = np.median(danceability)
    danceability_std = np.std(danceability)
    
    prompt = (
        f'Information helpful for describing my music taste: '
        f'My top 5 genres are {top_genres}. My top 10 artists are {top_artists}.'
        f'Top tags associated with my top artists are {top_tags}.'
        f'Here are the song metadata analysis statistics: '
        f'(Cite numeric data to prove your points and be insightful about Std which represents how well spread and diverse my tastes are)'
        f"(Analyze deeper, don't just report the facts directly, connect the dots with my top genres and artists, engage your audience)"
        f'Popularity (out of 100, with higher score being more popular): Mean - {pop_mean}, Median - {pop_median}, Std - {pop_std}. '
        f'Tempo (in BPM): Mean - {tempo_mean}, Median - {tempo_median}, Std - {tempo_std}. '
        f'Valence (a measure from 0.0 to 1.0 describing the musical positiveness conveyed by a track. Tracks with high valence sound more positive (e.g. happy, cheerful, euphoric), while tracks with low valence sound more negative (e.g. sad, depressed, angry)): Mean - {valence_mean}, Median - {valence_median}, Std - {valence_std}. '
        f'Acousticness (A confidence measure from 0.0 to 1.0 of whether the track is acoustic): Mean - {acousticness_mean}, Median - {acousticness_median}, Std - {acousticness_std}. '
        f'Energy (a measure from 0.0 to 1.0 and represents perceptual intensity and activity. Typically, energetic tracks feel fast, loud, and noisy): Mean - {energy_mean}, Median - {energy_median}, Std - {energy_std}. '
        f'Danceability (describes how suitable a track is for dancing. A value of 0.0 is least danceable and 1.0 is most danceable.): Mean - {danceability_mean}, Median - {danceability_median}, Std - {danceability_std}. '
    )
    print(prompt)

    client = anthropic.Anthropic(
        api_key=os.getenv("ANTHROPIC_API_KEY"),
    )
    response_text = 'Error Getting Analysis'
    try:
        message = client.messages.create(
            model="claude-3-haiku-20240307",
            max_tokens=4000,
            temperature=0.5,
            system="You are an insightful music taste analyzer. Talk to me like a person and don't use big words. Don't use any filler words or connection phrase (like 'furthermore'). Use stripped to the core language and try to start sentences with 'You'",
            messages=[
                {"role": "user", "content": prompt}
            ]
        )
        if message.content:
            response_text = message.content[0].text
        else:
            response_text = "No response received from Claude API."
    except anthropic.APIConnectionError as e:
        print("The server could not be reached")
        print(e.__cause__)  # an underlying Exception, likely raised within httpx.
    except anthropic.RateLimitError as e:
        print("A 429 status code was received; we should back off a bit.")
    except anthropic.APIStatusError as e:
        print("Another non-200-range status code was received")
        print(e.status_code)
        print(e.response)
        
    return response_text