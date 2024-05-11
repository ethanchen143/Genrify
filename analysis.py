import numpy as np
from collections import Counter
def analyze(data):
    genres = [y for x in data for y in x['genres']]
    counter = Counter(genres)
    fav = counter.most_common(3)
    res = f'Hi! Favorite genres are {fav[0][0]}, {fav[1][0]}, {fav[2][0]}'
    return res