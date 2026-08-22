"""Cache-aside + background stale-while-revalidate helper backed by Redis.

Usage pattern (see neurocom_backend.services.daraz_service.get_all_products):

    def get_all_products(access_token: str) -> DarazGetAllProductsResponse:
        body = get_or_refresh(
            cache_key=f"daraz:products:{fingerprint(access_token)}",
            fetch_raw_fn=lambda: _fetch_all_products_raw(access_token),
            transform_fn=_clean_products_payload,
        )
        return DarazGetAllProductsResponse.model_validate(body)

First request for a key: fetched synchronously, transformed, and cached.
Every later request: the cached (already-transformed) value is returned
immediately, while a background thread re-fetches the *raw* live data and
compares its hash against what was cached last time (deep,
order-independent JSON comparison). `transform_fn` — which can be
expensive (e.g. HTML cleanup, full model validation) — only runs again if
the raw data actually changed; a no-op refresh is just a cheap hash
comparison, not a full re-transform. So the request that triggers the
refresh still gets the (possibly stale) cached data, and the *next* request
after that gets the updated data.

Note on why the comparison is hash-based and done on the *raw* payload
rather than the transformed one: transforms like HTML-to-text cleanup are
CPU-bound, and Python's GIL means CPU-bound work on a background thread
still stalls the foreground request thread. Keeping the background
comparison to a cheap hash (and only paying for the real transform when
data has actually changed) keeps cache hits fast even while a background
revalidation is in flight.
"""

import hashlib
import json
import logging
import threading
from typing import Any, Callable, Optional

import redis

from neurocom_backend.utils.settings import (
    REDIS_HOST,
    REDIS_PORT,
    REDIS_USERNAME,
    REDIS_PASSWORD,
    REDIS_SSL,
    DARAZ_CACHE_TTL_SECONDS,
)

logger = logging.getLogger(__name__)

_redis_client: Optional["redis.Redis"] = None
_client_lock = threading.Lock()


def get_redis_client() -> "redis.Redis":
    global _redis_client
    if _redis_client is None:
        with _client_lock:
            if _redis_client is None:
                _redis_client = redis.Redis(
                    host=REDIS_HOST,
                    port=REDIS_PORT,
                    username=REDIS_USERNAME,
                    password=REDIS_PASSWORD,
                    ssl=REDIS_SSL,
                    decode_responses=True,
                    socket_connect_timeout=5,
                    socket_timeout=5,
                )
    return _redis_client


def fingerprint(value: str) -> str:
    """Short, non-reversible key fragment for e.g. access tokens, so raw
    secrets never end up as/in Redis key names."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def _canonicalize(value: Any) -> Any:
    """Recursively normalize a JSON-able structure so two payloads that
    differ only in dict key order or list/array element order compare as
    equal. Dicts are order-independent by nature (JSON objects); this makes
    lists order-independent too, since APIs like Daraz's don't guarantee a
    stable ordering for collections such as `products` or `skus` between
    calls even when the underlying data hasn't changed.
    """
    if isinstance(value, dict):
        return {key: _canonicalize(val) for key, val in sorted(value.items(), key=lambda kv: kv[0])}
    if isinstance(value, list):
        items = [_canonicalize(item) for item in value]
        items.sort(key=lambda item: json.dumps(item, sort_keys=True, default=str))
        return items
    return value


def canonical_dumps(data: Any) -> str:
    return json.dumps(_canonicalize(data), sort_keys=True, separators=(",", ":"), default=str)


def content_hash(data: Any) -> str:
    return hashlib.sha256(canonical_dumps(data).encode("utf-8")).hexdigest()


def data_matches(a: Any, b: Any) -> bool:
    """Deep, order-independent equality check for two JSON-able payloads."""
    return content_hash(a) == content_hash(b)


def _store(client: "redis.Redis", cache_key: str, raw_data: Any, value: Any, ttl_seconds: int) -> None:
    entry = {"hash": content_hash(raw_data), "value": value}
    client.set(cache_key, json.dumps(entry, default=str), ex=ttl_seconds)


def _background_refresh(
    client: "redis.Redis",
    cache_key: str,
    cached_hash: str,
    fetch_raw_fn: Callable[[], Any],
    transform_fn: Callable[[Any], Any],
    ttl_seconds: int,
    lock_seconds: int,
) -> None:
    # Lock acquisition happens here, inside the background thread, rather
    # than on the request path. Every Redis round trip costs real latency
    # (can easily be 100-200ms+ to a managed/cloud instance); a cache-hit
    # request should only ever pay for the one GET that serves it, not also
    # wait on a SET for a lock it doesn't need the result of.
    lock_key = f"{cache_key}:refresh-lock"
    got_lock = client.set(lock_key, "1", nx=True, ex=lock_seconds)
    if not got_lock:
        return
    try:
        raw_data = fetch_raw_fn()
        raw_data_hash = content_hash(raw_data)
        print(raw_data_hash, cached_hash)
        if raw_data_hash == cached_hash:
            # Data hasn't changed — just extend the TTL so a busy key
            # doesn't expire and force a slow synchronous refetch. No need
            # to pay for transform_fn again.
            client.expire(cache_key, ttl_seconds)
        else:
            value = transform_fn(raw_data)
            _store(client, cache_key, raw_data, value, ttl_seconds)
            logger.info("redis_cache: refreshed stale key %s", cache_key)
    except Exception:
        logger.exception("redis_cache: background refresh failed for key %s", cache_key)
    finally:
        client.delete(lock_key)


def get_or_refresh(
    cache_key: str,
    fetch_raw_fn: Callable[[], Any],
    transform_fn: Callable[[Any], Any] = lambda raw: raw,
    ttl_seconds: int = DARAZ_CACHE_TTL_SECONDS,
    lock_seconds: int = 30,
    enable_background_refresh: bool = True,
) -> Any:
    """Cache-aside read with optional background stale-while-revalidate.

    - Cache miss (or corrupted entry): fetch the raw data synchronously,
      run `transform_fn` on it once, cache `{hash, value}`, and return the
      transformed value.
    - Cache hit: return the cached (already-transformed) value immediately
      after a single Redis round trip. If `enable_background_refresh` is
      True (the default), a background thread is kicked off to consider
      refreshing; it acquires a short-lived Redis lock itself (so
      concurrent requests don't pile up duplicate refreshes) and, only if
      it wins the lock, re-fetches raw live data, hashes it, and runs
      `transform_fn` + swaps the cache entry in only if the hash actually
      differs from what's cached. Set `enable_background_refresh=False` for
      expensive fetches (e.g. many sequential upstream calls) where a
      cache hit should stay a single Redis round trip with no extra work
      kicked off in the background.
    """
    client = get_redis_client()
    cached_raw = client.get(cache_key)

    entry: Optional[dict] = None
    if cached_raw is not None:
        try:
            parsed = json.loads(cached_raw)
            if isinstance(parsed, dict) and "hash" in parsed and "value" in parsed:
                entry = parsed
                print("data served from cache...", entry)
        except (TypeError, ValueError):
            entry = None

    if entry is None:
        raw_data = fetch_raw_fn()
        value = transform_fn(raw_data)
        _store(client, cache_key, raw_data, value, ttl_seconds)
        return value

    if enable_background_refresh:
        threading.Thread(
            target=_background_refresh,
            args=(client, cache_key, entry["hash"], fetch_raw_fn, transform_fn, ttl_seconds, lock_seconds),
            daemon=True,
        ).start()

    return entry["value"]
