"""
Movie Recommendation System views.

The recommendation model is a set of files on disk produced by
``training/train.py``. It can take a while to load, so it is loaded once per
process in a background thread and the UI polls ``/api/model-status/`` for
progress. Everything in this module is read-only once the model is loaded.
"""
import json
import logging
import pickle
import threading
import time
from datetime import date
from difflib import get_close_matches
from pathlib import Path
from urllib.parse import quote, quote_plus

import numpy as np
import pandas as pd
from django.conf import settings
from django.contrib.admin.views.decorators import staff_member_required
from django.core.cache import cache
from django.db.models import Avg
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods

from . import tmdb_service as tmdb
from .models import Movie

logger = logging.getLogger(__name__)

# Files that must exist for a directory to count as a trained model.
REQUIRED_ARTIFACTS = ('config.json', 'title_to_idx.json', 'movie_metadata.parquet')

# Upper bounds on user-supplied input, applied before any expensive work.
MAX_QUERY_LENGTH = 200
MAX_AUTOCOMPLETE_RESULTS = 20
RECENCY_BONUS = 0.1
RECENCY_WINDOW_YEARS = 15

SEARCH_CACHE_TIMEOUT = 300  # seconds


class ModelLoadError(RuntimeError):
    """Raised when the recommendation model cannot be loaded."""


def _as_list(value) -> list:
    """Normalise a metadata cell to a plain list.

    Parquet list columns come back as numpy arrays rather than Python lists,
    so an ``isinstance(value, list)`` test silently discards every genre.
    """
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return list(value)
    if isinstance(value, np.ndarray):
        return value.tolist()
    return []


# The trainer lowercases genres and strips spaces so they work as TF-IDF tokens,
# and that same column is saved for display. These two are the only TMDB genres
# that need more than title-casing to read properly.
_GENRE_LABELS = {'sciencefiction': 'Science Fiction', 'tvmovie': 'TV Movie'}


VIETNAMESE_GENRES = {
    'action': ('Hành động', ('hanh dong', 'hành động')),
    'adventure': ('Phiêu lưu', ('phieu luu', 'phiêu lưu')),
    'animation': ('Hoạt hình', ('hoat hinh', 'hoạt hình')),
    'comedy': ('Hài', ('hai', 'hài')),
    'crime': ('Hình sự', ('hinh su', 'hình sự')),
    'documentary': ('Tài liệu', ('tai lieu', 'tài liệu')),
    'drama': ('Chính kịch', ('chinh kich', 'chính kịch')),
    'family': ('Gia đình', ('gia dinh', 'gia đình')),
    'fantasy': ('Giả tưởng', ('gia tuong', 'giả tưởng')),
    'history': ('Lịch sử', ('lich su', 'lịch sử')),
    'horror': ('Kinh dị', ('kinh di', 'kinh dị')),
    'music': ('Nhạc', ('nhac', 'nhạc')),
    'mystery': ('Bí ẩn', ('bi an', 'bí ẩn')),
    'romance': ('Lãng mạn', ('lang man', 'lãng mạn')),
    'sciencefiction': ('Khoa học viễn tưởng', ('khoa hoc vien tuong', 'khoa học viễn tưởng')),
    'tvmovie': ('Phim truyền hình', ('phim truyen hinh', 'phim truyền hình')),
    'thriller': ('Gây cấn', ('gay can', 'gây cấn')),
    'war': ('Chiến tranh', ('chien tranh', 'chiến tranh')),
    'western': ('Miền Tây', ('mien tay', 'miền tây')),
}


def _genre_key(value):
    text = str(value or '').strip().casefold()
    return ''.join(ch for ch in text if ch.isalnum())


def _normalize_vietnamese_genre(value):
    """Map an English or Vietnamese genre name to canonical search and display forms."""
    key = _genre_key(value)
    for canonical, (label, aliases) in VIETNAMESE_GENRES.items():
        if key in {_genre_key(canonical), _genre_key(label), *(_genre_key(alias) for alias in aliases)}:
            return canonical, label
    return None, str(value or '').strip()


def _expand_vietnamese_description(description):
    """Expand Vietnamese genre and plot concepts for the English-trained TF-IDF vectorizer."""
    cleaned = ' '.join(str(description or '').split())
    expanded = cleaned.casefold()

    for canonical, (label, aliases) in VIETNAMESE_GENRES.items():
        genre_terms = {label.casefold(), canonical, canonical.replace('sciencefiction', 'science fiction')}
        genre_terms.update(alias.casefold() for alias in aliases)
        if any(term in expanded for term in genre_terms if term):
            expanded += f' {canonical.replace("sciencefiction", "science fiction")}'
            if canonical == 'sciencefiction':
                expanded += ' science fiction sci-fi futuristic space alien'
            elif canonical == 'horror':
                expanded += ' horror ghost supernatural monster scary'
            elif canonical == 'romance':
                expanded += ' romance love relationship'
            elif canonical == 'comedy':
                expanded += ' comedy funny humor'
            elif canonical == 'animation':
                expanded += ' animation animated cartoon'
            elif canonical == 'documentary':
                expanded += ' documentary real life biography'
            elif canonical == 'family':
                expanded += ' family children child parents'
            elif canonical == 'action':
                expanded += ' action fight battle superhero'
            elif canonical == 'adventure':
                expanded += ' adventure journey expedition'
            elif canonical == 'thriller':
                expanded += ' thriller suspense tension crime'

    concept_map = {
        'không gian': 'space',
        'phi hành': 'astronaut spacecraft space',
        'du hành': 'travel journey',
        'thời gian': 'time travel',
        'hố sâu': 'wormhole black hole',
        'trái đất': 'earth planet',
        'ngoài hành tinh': 'alien extraterrestrial planet',
        'người ngoài hành tinh': 'alien extraterrestrial',
        'robot': 'robot artificial intelligence',
        'trí tuệ nhân tạo': 'artificial intelligence machine',
        'ma': 'ghost paranormal supernatural',
        'linh hồn': 'ghost spirit supernatural',
        'zombie': 'zombie undead',
        'ma cà rồng': 'vampire',
        'gia đình': 'family father mother child',
        'tình yêu': 'romance love',
        'chiến tranh': 'war soldier army',
        'cướp': 'thief robbery',
        'tội phạm': 'crime criminal',
        'cứu nhân loại': 'save world humanity',
        'thảm họa': 'disaster apocalypse',
        'khủng long': 'dinosaur',
        'phép thuật': 'magic fantasy',
        'huyền bí': 'magic supernatural fantasy',
    }
    for vietnamese, english in concept_map.items():
        if vietnamese in expanded:
            expanded += ' ' + english

    return expanded


def _genre_label(genre) -> str:
    """Display form of a stored genre: ``sciencefiction`` becomes ``Science Fiction``."""
    text = str(genre).strip()
    if text != text.lower():
        return text  # already display-cased
    return _GENRE_LABELS.get(text, text.title())


def _clean(value, default='Unknown'):
    """Return a display-safe scalar, collapsing NaN/None to a default."""
    if value is None:
        return default
    try:
        if pd.isna(value):
            return default
    except (TypeError, ValueError):
        pass
    return value


def _number(value) -> float | None:
    """Return a float for a numeric cell, or None when it is missing."""
    try:
        if value is None or pd.isna(value):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _year(release_date) -> str:
    """Extract a 4-digit year from a release date cell."""
    text = str(_clean(release_date, ''))
    return text[:4] if len(text) >= 4 and text[:4].isdigit() else ''


class MovieRecommender:
    """Content-based recommender backed by pre-computed similarity artifacts."""

    def __init__(self, model_dir, progress_callback=None):
        self.model_dir = Path(model_dir)
        self.metadata = None
        self.config = None
        self.title_to_idx = {}
        # Lowercased title -> canonical title, for fast case-insensitive lookup.
        self._lower_to_title = {}
        self._titles: list[str] = []
        # Exactly one of these is populated, cheapest representation first.
        self._neighbor_idx = None      # (n, k) int array of pre-computed neighbours
        self._neighbor_scores = None   # (n, k) float array of matching scores
        self._similarity_sparse = None  # scipy sparse matrix, never densified
        self._similarity_dense = None   # memory-mapped (n, n) array
        self._tfidf_vectorizer = None
        self._svd_model = None
        self._load(progress_callback)

    # ------------------------------------------------------------------ load

    def _load(self, progress_callback=None):
        def report(pct):
            if progress_callback:
                progress_callback(pct)

        logger.info("Loading recommendation model from %s", self.model_dir)
        report(10)

        self.metadata = pd.read_parquet(self.model_dir / 'movie_metadata.parquet')
        report(35)

        self._load_similarity()
        report(70)

        with open(self.model_dir / 'title_to_idx.json', encoding='utf-8') as handle:
            self.title_to_idx = json.load(handle)
        self._titles = list(self.title_to_idx.keys())
        self._lower_to_title = {title.lower(): title for title in self._titles}
        report(90)

        with open(self.model_dir / 'config.json', encoding='utf-8') as handle:
            self.config = json.load(handle)

        vectorizer_path = self.model_dir / 'tfidf_vectorizer.pkl'
        if vectorizer_path.exists():
            with open(vectorizer_path, 'rb') as handle:
                self._tfidf_vectorizer = pickle.load(handle)

        svd_path = self.model_dir / 'svd_model.pkl'
        if svd_path.exists():
            with open(svd_path, 'rb') as handle:
                self._svd_model = pickle.load(handle)
        report(100)

        logger.info("Loaded %s movies successfully", f"{self.movie_count:,}")

    def _load_similarity(self):
        """Load similarity data in the most memory-efficient form available.

        Densifying a full similarity matrix costs ``n * n * 4`` bytes -- 10 GB
        for a 50k-movie model -- which is why neither the sparse matrix nor the
        dense one is ever read into memory whole.
        """
        neighbors_idx = self.model_dir / 'neighbors_idx.npy'
        neighbors_scores = self.model_dir / 'neighbors_scores.npy'
        sparse_path = self.model_dir / 'similarity_matrix.npz'
        dense_path = self.model_dir / 'similarity_matrix.npy'

        if neighbors_idx.exists() and neighbors_scores.exists():
            self._neighbor_idx = np.load(neighbors_idx, mmap_mode='r')
            self._neighbor_scores = np.load(neighbors_scores, mmap_mode='r')
            logger.info("Using pre-computed top-%d neighbours", self._neighbor_idx.shape[1])
        elif sparse_path.exists():
            from scipy.sparse import load_npz

            # Kept sparse: a single row is materialised per request.
            self._similarity_sparse = load_npz(sparse_path).tocsr()
            logger.info("Using sparse similarity matrix %s", self._similarity_sparse.shape)
        elif dense_path.exists():
            # Memory-mapped so the OS pages in only the row being read.
            self._similarity_dense = np.load(dense_path, mmap_mode='r')
            logger.info("Using memory-mapped similarity matrix %s", self._similarity_dense.shape)
        else:
            raise ModelLoadError(
                f"No similarity data found in {self.model_dir}. Expected one of "
                "neighbors_idx.npy, similarity_matrix.npz or similarity_matrix.npy."
            )

    # --------------------------------------------------------------- lookups

    @property
    def movie_count(self) -> int:
        if self.config and 'n_movies' in self.config:
            return int(self.config['n_movies'])
        return len(self._titles)

    def find_movie(self, title: str) -> str | None:
        """Resolve user input to a known title, cheapest strategy first."""
        query = title.strip()
        if not query:
            return None

        lowered = query.lower()

        # 1. Exact match (case-insensitive) -- what autocomplete selections give us.
        exact = self._lower_to_title.get(lowered)
        if exact:
            return exact

        # 2. Prefix, then substring. Prefer the shortest match, which is almost
        #    always the base film rather than a sequel or a making-of feature.
        prefix, substring = [], []
        for candidate in self._titles:
            candidate_lower = candidate.lower()
            if candidate_lower.startswith(lowered):
                prefix.append(candidate)
            elif lowered in candidate_lower:
                substring.append(candidate)
        if prefix:
            return min(prefix, key=len)
        if substring:
            return min(substring, key=len)

        # 3. Fuzzy match as a last resort, narrowed to titles of a similar
        #    length so difflib is not run across the whole catalogue.
        matches = self._fuzzy_title_matches(query, n=1, cutoff=0.6)
        return matches[0] if matches else None

    def _fuzzy_title_matches(self, query: str, n: int, cutoff: float) -> list[str]:
        cleaned = query.strip().lower()
        if not cleaned:
            return []

        length_window = range(max(1, len(cleaned) - 6), len(cleaned) + 7)
        candidates = [title for title in self._titles if len(title) in length_window]
        normalized_titles = {title.lower(): title for title in candidates}
        matches = get_close_matches(
            cleaned, list(normalized_titles), n=n, cutoff=cutoff
        )
        return [normalized_titles[match] for match in matches]

    def suggest(self, query: str, n: int = 5) -> list[str]:
        """Titles to offer after a failed search.

        find_movie already resolves anything matching by prefix, substring or a
        close fuzzy match, so by the time we get here only a looser threshold
        has any chance of helping -- hence the lower cutoff.
        """
        cleaned = query.strip()
        if not cleaned:
            return []
        matches = get_close_matches(cleaned, self._titles, n=n, cutoff=0.4)
        if matches:
            return matches
        # Last resort: match on any single word the visitor typed.
        words = [w for w in cleaned.lower().split() if len(w) > 2]
        hits = []
        for candidate in self._titles:
            lowered = candidate.lower()
            if any(word in lowered for word in words):
                hits.append(candidate)
                if len(hits) >= n:
                    break
        return hits

    def search_movies(self, query: str, n: int = MAX_AUTOCOMPLETE_RESULTS) -> list[str]:
        """Search titles by prefix, substring, then fuzzy match for autocomplete."""
        cleaned = query.strip()
        lowered = cleaned.lower()
        if not lowered:
            return []

        prefix, substring = [], []
        for candidate in self._titles:
            candidate_lower = candidate.lower()
            if candidate_lower.startswith(lowered):
                prefix.append(candidate)
            elif lowered in candidate_lower:
                substring.append(candidate)
            if len(prefix) >= n:
                break

        prefix.sort(key=len)
        substring.sort(key=len)
        matches = (prefix + substring)[:n]
        if matches:
            return matches
        return self._fuzzy_title_matches(cleaned, n=n, cutoff=0.6)

    # ------------------------------------------------------- recommendations

    def _candidate_neighbours(self, movie_idx: int, limit: int):
        """Return (indices, scores) of the most similar movies, best first."""
        if self._neighbor_idx is not None:
            indices = np.asarray(self._neighbor_idx[movie_idx])
            scores = np.asarray(self._neighbor_scores[movie_idx])
            keep = indices != movie_idx
            return indices[keep][:limit], scores[keep][:limit]

        if self._similarity_sparse is not None:
            row = self._similarity_sparse[movie_idx].toarray().ravel()
        else:
            row = np.asarray(self._similarity_dense[movie_idx], dtype=np.float32)

        row = row.copy()
        row[movie_idx] = -np.inf  # never recommend the movie itself

        # argpartition is O(n) against the O(n log n) of a full sort, which
        # matters a great deal when n is in the tens of thousands.
        take = int(min(limit, row.size - 1))
        if take <= 0:
            return np.empty(0, dtype=int), np.empty(0, dtype=np.float32)
        if take < row.size:
            candidates = np.argpartition(-row, take - 1)[:take]
        else:
            candidates = np.arange(row.size)
        candidates = candidates[np.argsort(-row[candidates], kind='stable')]
        return candidates, row[candidates]

    def _movie_payload(self, idx: int, score: float) -> dict:
        movie = self.metadata.iloc[int(idx)]
        title = str(movie['title'])
        imdb_id = _clean(movie.get('imdb_id'), None)
        poster_path = _clean(movie.get('poster_path'), None)
        rating = _number(movie.get('vote_average'))
        votes = _number(movie.get('vote_count'))
        overview = str(_clean(movie.get('overview'), ''))
        genres = [_genre_label(g) for g in _as_list(movie.get('genres'))[:3]]

        return {
            'id': int(movie['id']),
            'title': title,
            'release_date': _clean(movie.get('release_date')),
            'year': _year(movie.get('release_date')),
            'production': _clean(movie.get('primary_company')),
            'genre_list': genres,
            'genres': ', '.join(genres) or 'N/A',
            'rating': f"{rating:.1f}/10" if rating is not None else 'N/A',
            'rating_value': round(rating, 1) if rating is not None else None,
            'votes': f"{int(votes):,}" if votes is not None else 'N/A',
            'similarity_score': f"{float(score):.3f}",
            'similarity_percent': max(0, min(100, round(float(score) * 100))),
            'overview': (overview[:180].rstrip() + '...') if len(overview) > 180 else overview,
            'imdb_id': imdb_id,
            'poster_url': f"https://image.tmdb.org/t/p/w342{poster_path}" if poster_path else None,
            'google_link': 'https://www.google.com/search?q=' + quote_plus(f"{title} movie"),
            'imdb_link': f"https://www.imdb.com/title/{quote(str(imdb_id))}/" if imdb_id else None,
        }

    def _recency_bonus(self, idx: int, current_year: int) -> float:
        year = _year(self.metadata.iloc[int(idx)].get('release_date'))
        if not year:
            return 0.0
        age = max(0, current_year - int(year))
        return RECENCY_BONUS * max(0.0, 1.0 - age / RECENCY_WINDOW_YEARS)

    def recommend_by_description(self, description: str, n: int = 15) -> dict:
        """Rank movies by semantic text similarity to a free-form plot description."""
        cleaned = ' '.join(str(description or '').split())
        if len(cleaned) < 10:
            return {'error': 'Vui lòng nhập mô tả phim dài hơn 10 ký tự.'}

        if self._tfidf_vectorizer is None:
            return {'error': 'Model hiện tại chưa hỗ trợ tìm kiếm theo mô tả.'}

        expanded_query = _expand_vietnamese_description(cleaned)

        documents = []
        for _, movie in self.metadata.iterrows():
            genres = ' '.join(
                str(genre).replace('sciencefiction', 'science fiction')
                for genre in _as_list(movie.get('genres'))
            )
            overview = str(_clean(movie.get('overview'), ''))
            documents.append(f'{genres} {overview}')

        movie_vectors = self._tfidf_vectorizer.transform(documents)
        query_vector = self._tfidf_vectorizer.transform([expanded_query])

        if self._svd_model is not None:
            movie_vectors = self._svd_model.transform(movie_vectors)
            query_vector = self._svd_model.transform(query_vector)

        movie_arrays = (
            movie_vectors.toarray()
            if hasattr(movie_vectors, 'toarray')
            else np.asarray(movie_vectors)
        )
        query_arrays = (
            query_vector.toarray()
            if hasattr(query_vector, 'toarray')
            else np.asarray(query_vector)
        )
        movie_norms = np.linalg.norm(movie_arrays, axis=1)
        query_norm = float(np.linalg.norm(query_arrays[0]))

        if query_norm == 0:
            return {'error': 'Mô tả này chưa đủ từ khóa để phân tích.'}

        dot_products = np.asarray(movie_arrays @ query_arrays[0]).ravel()
        scores = np.divide(
            dot_products,
            movie_norms * float(query_norm),
            out=np.zeros_like(dot_products, dtype=np.float64),
            where=(movie_norms * float(query_norm)) != 0,
        )

        take = min(max(int(n), 1), len(scores))
        candidate_indices = np.argpartition(-scores, take - 1)[:take]
        candidate_indices = candidate_indices[
            np.argsort(-scores[candidate_indices], kind='stable')
        ]

        recommendations = []
        for idx in candidate_indices:
            payload = self._movie_payload(int(idx), float(scores[int(idx)]))
            recommendations.append(payload)

        return {
            'query_movie': cleaned,
            'source_movie': {
                'title': 'Mô tả phim của bạn',
                'year': '',
                'production': 'Phân tích nội dung',
                'rating': '',
                'genres': 'TF-IDF · cosine similarity',
                'poster_url': None,
            },
            'recommendations': recommendations,
        }

    def get_recommendations(self, movie_title: str, n: int = 15,
                            min_rating: float | None = None) -> dict:
        """Recommend movies similar to ``movie_title``."""
        matched_title = self.find_movie(movie_title)
        if not matched_title:
            return {
                'error': f"We couldn't find a movie matching “{movie_title}”.",
                'suggestions': self.suggest(movie_title, 5),
            }

        movie_idx = int(self.title_to_idx[matched_title])
        source = self.metadata.iloc[movie_idx]

        # Over-fetch so rating filters and the recency boost have candidates
        # beyond the most similar few titles.
        pool = n * 4 + 25
        indices, scores = self._candidate_neighbours(movie_idx, pool)
        current_year = date.today().year
        ranked_candidates = sorted(
            zip(indices, scores, strict=False),
            key=lambda item: (
                float(item[1]) + self._recency_bonus(int(item[0]), current_year)
            ),
            reverse=True,
        )

        recommendations = []
        for idx, score in ranked_candidates:
            if len(recommendations) >= n:
                break
            if min_rating is not None:
                rating = _number(self.metadata.iloc[int(idx)].get('vote_average'))
                if rating is None or rating < min_rating:
                    continue
            recommendations.append(self._movie_payload(idx, score))

        source_rating = _number(source.get('vote_average'))
        return {
            'query_movie': matched_title,
            'source_movie': {
                'title': matched_title,
                'year': _year(source.get('release_date')),
                'production': _clean(source.get('primary_company')),
                'rating': f"{source_rating:.1f}/10" if source_rating is not None else 'N/A',
                'genres': ', '.join(_genre_label(g) for g in _as_list(source.get('genres'))[:3]) or 'N/A',
                'poster_url': (
                    f"https://image.tmdb.org/t/p/w342{_clean(source.get('poster_path'), '')}"
                    if _clean(source.get('poster_path'), None) else None
                ),
            },
            'recommendations': recommendations,
        }


# ---------------------------------------------------------------------------
# Process-wide model loading
#
# Loading happens once per worker process, in a daemon thread, behind a lock so
# concurrent first requests cannot each kick off their own load.
# ---------------------------------------------------------------------------

_LOCK = threading.Lock()
_RECOMMENDER: MovieRecommender | None = None
_LOADING_THREAD: threading.Thread | None = None
_PROGRESS = 0
_LOAD_ERROR: str | None = None
_GENERATION = 0
_LAST_ATTEMPT = 0.0

# How long to wait before looking for a model again after finding none. This
# lets a model trained while the server is running be picked up on a refresh,
# without retrying the filesystem on every single request.
MISSING_MODEL_RETRY_SECONDS = 15.0


def _resolve_model_dir() -> Path | None:
    """Return the first directory that actually contains a trained model."""
    base_dir = Path(settings.BASE_DIR)
    configured_dir = Path(settings.MODEL_DIR)
    candidates = []
    if (
        getattr(settings, 'MODEL_DIR_AUTO', False)
        and configured_dir.resolve() == (base_dir / 'models').resolve()
    ):
        candidates.extend(sorted(
            (path for path in base_dir.glob('models_tmdb_*') if path.is_dir()),
            key=lambda path: path.name,
            reverse=True,
        ))
    candidates.append(configured_dir)
    # Kept for backwards compatibility with earlier documented locations.
    for extra in ('models', 'demo_model', 'static', 'training/models'):
        candidate = base_dir / extra
        if candidate not in candidates:
            candidates.append(candidate)

    for candidate in candidates:
        if all((candidate / artifact).exists() for artifact in REQUIRED_ARTIFACTS):
            return candidate

    logger.warning(
        "No model found. Looked in: %s. Set MODEL_DIR or run training/train.py.",
        ', '.join(str(c) for c in candidates),
    )
    return None


def _load_model():
    """Background worker: load the model and publish progress."""
    global _RECOMMENDER, _PROGRESS, _LOAD_ERROR, _GENERATION

    model_dir = _resolve_model_dir()
    if model_dir is None:
        with _LOCK:
            _LOAD_ERROR = 'missing'
        return

    try:
        def progress(value):
            global _PROGRESS
            _PROGRESS = value

        recommender = MovieRecommender(model_dir, progress)
    except Exception:
        logger.exception("Failed to load recommendation model from %s", model_dir)
        with _LOCK:
            _LOAD_ERROR = 'error'
        return

    with _LOCK:
        _RECOMMENDER = recommender
        _PROGRESS = 100
        _LOAD_ERROR = None
        _GENERATION += 1
    logger.info("Recommendation model ready")


def _start_model_loading():
    """Kick off the background load once, and only once, per process."""
    global _LOADING_THREAD, _PROGRESS, _LOAD_ERROR, _LAST_ATTEMPT

    with _LOCK:
        if _RECOMMENDER is not None:
            return
        if _LOADING_THREAD is not None and _LOADING_THREAD.is_alive():
            return
        if _LOAD_ERROR == 'error':
            # A load was attempted and blew up. Retrying on every request would
            # just hammer the logs; a restart is the right recovery here.
            return
        if _LOAD_ERROR == 'missing':
            if time.monotonic() - _LAST_ATTEMPT < MISSING_MODEL_RETRY_SECONDS:
                return
            _LOAD_ERROR = None
        _LAST_ATTEMPT = time.monotonic()
        _PROGRESS = 0
        _LOADING_THREAD = threading.Thread(
            target=_load_model, name='model-loader', daemon=True
        )
        logger.info("Starting model load in the background")
        _LOADING_THREAD.start()


def _get_recommender() -> MovieRecommender | None:
    """Return the loaded recommender, or None while it is unavailable."""
    _start_model_loading()
    return _RECOMMENDER


def _model_state() -> dict:
    """Describe the model's availability for the status and health endpoints."""
    if _RECOMMENDER is not None:
        return {'loaded': True, 'progress': 100, 'status': 'ready'}
    if _LOAD_ERROR == 'missing':
        return {
            'loaded': False,
            'progress': 0,
            'status': 'missing',
            'message': (
                'No recommendation model found. Train one with training/train.py '
                'or point the MODEL_DIR environment variable at an existing model.'
            ),
        }
    if _LOAD_ERROR is not None:
        return {
            'loaded': False,
            'progress': 0,
            'status': 'error',
            'message': 'The recommendation model could not be loaded. Check the server logs.',
        }
    return {'loaded': False, 'progress': _PROGRESS, 'status': 'loading'}


def _reset_for_tests():
    """Clear cached module state. Used by the test suite only."""
    global _RECOMMENDER, _LOADING_THREAD, _PROGRESS, _LOAD_ERROR, _GENERATION
    global _LAST_ATTEMPT
    with _LOCK:
        _RECOMMENDER = None
        _LOADING_THREAD = None
        _PROGRESS = 0
        _LOAD_ERROR = None
        _LAST_ATTEMPT = 0.0
        _GENERATION += 1
    cache.clear()


# ---------------------------------------------------------------------------
# Views
# ---------------------------------------------------------------------------

def _base_context(**extra) -> dict:
    state = _model_state()
    context = {
        'model_ready': state['status'] == 'ready',
        'model_status': state['status'],
        'total_movies': _RECOMMENDER.movie_count if _RECOMMENDER else 0,
    }
    context.update(extra)
    return context


@require_http_methods(["GET", "POST"])
def main(request):
    """Redirect GET requests to the catalogue and keep POST recommendations working."""
    if request.method == 'GET':
        target = reverse('recommender:tmdb_browse')
        query_string = request.GET.urlencode()
        if query_string:
            target = f'{target}?{query_string}'
        return redirect(target)
    return _recommend_movies(request)


@require_http_methods(["GET", "POST"])
def recommend_page(request):
    """Render the on-demand recommendation form and handle its submissions."""
    if request.method == 'GET':
        return render(request, 'recommender/recommend.html', {
            'movie_description': request.GET.get('description', '').strip()[:MAX_QUERY_LENGTH],
        })
    return _recommend_movies(request)


def _tmdb_movie_payload(movie):
    poster_path = str(movie.get('poster_path') or '')
    rating = _number(movie.get('vote_average'))
    votes = _number(movie.get('vote_count'))
    release_date = str(movie.get('release_date') or '')
    genres = [
        genre.get('name') or ''
        for genre in movie.get('genres', [])
        if genre.get('name')
    ]
    if not genres:
        genre_names = {
            28: 'Hành động', 12: 'Phiêu lưu', 16: 'Hoạt hình', 35: 'Hài',
            80: 'Hình sự', 99: 'Tài liệu', 18: 'Chính kịch', 10751: 'Gia đình',
            14: 'Giả tưởng', 36: 'Lịch sử', 27: 'Kinh dị', 10402: 'Nhạc',
            9648: 'Bí ẩn', 10749: 'Lãng mạn', 878: 'Khoa học viễn tưởng',
            10770: 'Phim truyền hình', 53: 'Gây cấn', 10752: 'Chiến tranh',
            37: 'Miền Tây',
        }
        genres = [
            genre_names[genre_id]
            for genre_id in movie.get('genre_ids', [])
            if genre_id in genre_names
        ]

    return {
        'id': int(movie['id']),
        'title': str(movie.get('title') or ''),
        'release_date': release_date,
        'year': release_date[:4] if len(release_date) >= 4 else '',
        'genre_list': genres[:3],
        'genres': ', '.join(genres[:3]) or 'N/A',
        'rating': f'{rating:.1f}/10' if rating is not None else 'N/A',
        'rating_value': round(rating, 1) if rating is not None else None,
        'votes': f'{int(votes):,} votes' if votes is not None else 'N/A',
        'poster_url': f'https://image.tmdb.org/t/p/w342{poster_path}' if poster_path else None,
        'similarity_percent': None,
    }


def _tmdb_recommendations(movie_name, limit):
    if not tmdb.settings.TMDB_ACCESS_TOKEN:
        return None

    matches = tmdb.search_movies(movie_name)
    if not matches:
        return None

    wanted = movie_name.strip().casefold()
    source = next(
        (
            movie for movie in matches
            if str(movie.get('title') or '').casefold() == wanted
            or str(movie.get('original_title') or '').casefold() == wanted
        ),
        matches[0],
    )
    tmdb_id = source.get('id')
    if tmdb_id is None:
        return None

    tmdb_id = int(tmdb_id)
    source_details = tmdb.get_movie_details(tmdb_id)
    similar = tmdb.similar_movies(tmdb_id)
    recommendations = []
    for movie in similar:
        if movie.get('adult') is True or not movie.get('title'):
            continue
        payload = _tmdb_movie_payload(movie)
        recommendations.append(payload)
        if len(recommendations) >= limit:
            break

    if not recommendations:
        return None

    source_payload = _tmdb_movie_payload(source_details)
    source_payload.update({
        'title': str(source_details.get('title') or source.get('title') or movie_name),
        'year': str(source_details.get('release_date') or '')[:4],
        'production': ', '.join(
            company.get('name', '')
            for company in source_details.get('production_companies', [])[:2]
            if company.get('name')
        ) or 'N/A',
    })
    return {
        'query_movie': source_payload['title'],
        'source_movie': source_payload,
        'recommendations': recommendations,
    }


def _can_use_tmdb_for_request(request):
    """API recommendations are reserved for authenticated accounts."""
    return (
        request.user.is_authenticated
        and bool(tmdb.settings.TMDB_ACCESS_TOKEN)
    )


def _recommend_movies(request):
    """Generate recommendations only in response to an explicit form submission."""
    description = (
        request.POST.get('movie_description')
        or request.POST.get('movie_name')
        or ''
    ).strip()[:MAX_QUERY_LENGTH]
    if not description:
        return render(request, 'recommender/recommend.html', {
            'error_message': 'Vui lòng mô tả ngắn gọn nội dung phim.',
        })

    recommender = _get_recommender()

    if recommender is None:
        state = _model_state()
        error = None
        if request.method == 'POST':
            error = state.get(
                'message', 'The movie database is still loading. Please try again in a moment.'
            )
        return render(request, 'recommender/recommend.html', {
            'error_message': error,
            'movie_description': description,
        })

    try:
        result = recommender.recommend_by_description(
            description, n=getattr(settings, 'RECOMMENDATION_COUNT', 15)
        )
    except Exception:
        logger.exception("Description recommendation failed")
        return render(request, 'recommender/recommend.html', {
            'movie_description': description,
            'error_message': 'Đã xảy ra lỗi khi tạo gợi ý. Vui lòng thử lại.',
        }, status=500)

    if 'error' in result:
        return render(request, 'recommender/recommend.html', {
            'movie_description': description,
            'error_message': result['error'],
        })

    return render(request, 'recommender/result.html', {
        'input_movie_name': result['query_movie'],
        'source_movie': result['source_movie'],
        'recommended_movies': result['recommendations'],
        'total_recommendations': len(result['recommendations']),
    })


@require_http_methods(["GET"])
def search_movies(request):
    """Autocomplete endpoint used by the search box."""
    query = request.GET.get('q', '').strip()[:MAX_QUERY_LENGTH]

    if len(query) < 2:
        return JsonResponse({'movies': [], 'count': 0})

    recommender = _get_recommender()
    if recommender is None:
        return JsonResponse({'movies': [], 'count': 0, 'loading': True})

    cache_key = f"movie-search:{_GENERATION}:{query.lower()}"
    matches = cache.get(cache_key)
    if matches is None:
        try:
            matches = recommender.search_movies(query, n=MAX_AUTOCOMPLETE_RESULTS)
        except Exception:
            logger.exception("Autocomplete failed for %r", query)
            return JsonResponse({'error': 'Search failed'}, status=500)
        cache.set(cache_key, matches, SEARCH_CACHE_TIMEOUT)

    return JsonResponse({'movies': matches, 'count': len(matches)})


@require_http_methods(["GET"])
def model_status(request):
    """Report model loading progress so the UI can show a real progress bar."""
    _start_model_loading()
    return JsonResponse(_model_state())


@require_http_methods(["GET"])
def health_check(request):
    """Liveness/readiness probe.

    Returns 200 while the model is still loading: a platform health check that
    fails during a slow first load would kill the deploy before it can finish.
    """
    _start_model_loading()
    state = _model_state()

    if state['status'] == 'ready':
        return JsonResponse({
            'status': 'healthy',
            'model_loaded': True,
            'movies_loaded': _RECOMMENDER.movie_count,
            'model_dir': _RECOMMENDER.model_dir.name,
        })

    if state['status'] == 'loading':
        return JsonResponse({
            'status': 'starting',
            'model_loaded': False,
            'progress': state['progress'],
        })

    return JsonResponse({
        'status': 'unhealthy',
        'model_loaded': False,
        'reason': state['status'],
        'message': state.get('message', ''),
    }, status=503)


@staff_member_required
@require_http_methods(["GET"])
def admin_dashboard(request):
    """Show staff a summary of the database catalogue and recommender model."""
    _start_model_loading()
    model_state = _model_state()
    movie_stats = Movie.objects.aggregate(average_rating=Avg('vote_average'))

    return render(request, 'recommender/admin_dashboard.html', {
        'database_movie_count': Movie.objects.count(),
        'average_rating': movie_stats['average_rating'] or 0,
        'recent_movies': Movie.objects.order_by('-created_at')[:5],
        'model_state': model_state,
        'model_movie_count': _RECOMMENDER.movie_count if _RECOMMENDER else 0,
    })


def handler404(request, exception=None):
    return render(request, 'recommender/error.html', {
        'error_icon': '🔍',
        'error_title': 'Page not found',
        'error_message': "That page doesn't exist. Let's get you back to the movies.",
    }, status=404)


def handler500(request):
    return render(request, 'recommender/error.html', {
        'error_icon': '⚠️',
        'error_title': 'Something went wrong',
        'error_message': 'An unexpected error occurred. Please try again in a moment.',
    }, status=500)
