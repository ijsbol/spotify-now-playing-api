import base64
import json
from os import getenv
import time
from typing import Any, Final, TypedDict, cast

from aiohttp import ClientSession, ContentTypeError
from dotenv import load_dotenv
from fastapi import APIRouter, Request
from fake_headers import Headers
from starlette.responses import JSONResponse


load_dotenv()


NOW_PLAYING_ENDPOINT: Final[str] = "https://api.spotify.com/v1/me/player/currently-playing"
TOKEN_ENDPOINT: Final[str] = "https://accounts.spotify.com/api/token"
CLIENT_ID: Final[str] = cast(str, getenv("SPOTIFY_CLIENT_ID"))
CLIENT_SECRET: Final[str] = cast(str, getenv("SPOTIFY_CLIENT_SECRET"))
REFRESH_TOKEN: Final[str] = cast(str, getenv("SPOTIFY_USER_REFRESH_TOKEN"))
SPOTIFY_SP_DC: Final[str] = cast(str, getenv("SPOTIFY_SP_DC"))
SPOTIFY_SP_KEY: Final[str] = cast(str, getenv("SPOTIFY_SP_KEY"))
MAX_TIME_DELTA_BETWEEN_REFRESHES: Final[int] = 60 * 60  # 1 hour
DEFAULT_CACHE_EXPIRE_SECONDS: Final[int] = 12 * 60 * 60  # 12 hours


with open("cache.json", "w+") as f:
    json.dump({}, f)


class LyricCache(TypedDict):
    track_id: str
    lyrics: Any


router = APIRouter()


def generate_auth() -> str:
    return base64.b64encode(f"{CLIENT_ID}:{CLIENT_SECRET}".encode("ascii")).decode("utf-8")


def cache_get(ref: str) -> Any:
    """Get the cache for the provided pointer."""
    with open("cache.json", "r") as f:
        cache = json.loads(f.read())
    return cache.get(ref, None)


def cache_update(ref: str, data: Any) -> Any:
    """Update the cache for the provided pointer."""
    with open("cache.json", "r") as f_r:
        cache = json.loads(f_r.read())
        cache[ref] = data
        with open("cache.json", "w") as f_w:
            json.dump(cache, f_w)
    return data


async def get_user_token() -> str:
    user_token_last_refreshed = cache_get("user_token_last_refreshed") or 0
    current_user_token = cache_get("current_user_token") or ""
    if (time.time() - user_token_last_refreshed) > MAX_TIME_DELTA_BETWEEN_REFRESHES:
        auth = generate_auth()
        async with ClientSession() as session:
            async with session.post(
                url=TOKEN_ENDPOINT,
                headers={
                    "Authorization": f"Basic {auth}",
                    "Content-Type": "application/x-www-form-urlencoded",
                },
                params={
                    "grant_type": "refresh_token",
                    "refresh_token": REFRESH_TOKEN,
                },
            ) as resp:
                json = await resp.json()
                cache_update("user_token_last_refreshed", time.time())
                current_user_token = cache_update("current_user_token", json["access_token"])
    return current_user_token


async def get_lyric_api_token() -> str:
    lyric_api_token_expires_at = cache_get("lyric_api_token_expires_at") or 0
    current_lyric_api_token = cache_get("current_lyric_api_token") or ""
    if time.time() > (lyric_api_token_expires_at - 10_000):  # -10s for padding
        headers = Headers().generate()
        async with ClientSession() as session:
            async with session.get(
                url="https://open.spotify.com/get_access_token",
                headers=headers,
                params={
                    "reason": "web-player",
                    "productType": "web-player",
                },
                cookies={
                    "sp_dc": SPOTIFY_SP_DC,
                    "sp_key": SPOTIFY_SP_KEY,
                }
            ) as resp:
                json = await resp.json()
                lyric_api_token_expires_at = cache_update("lyric_api_token_expires_at", json["accessTokenExpirationTimestampMs"])
                current_lyric_api_token = cache_update("current_lyric_api_token", json["accessToken"])
    return current_lyric_api_token


async def get_lyrics_from_api(track_id: str) -> Any:
    lyric_cache = cache_get("lyric_cache") or LyricCache(track_id="", lyrics=None)
    if lyric_cache["track_id"] == track_id:
        return lyric_cache["lyrics"]

    lyric_api_token = await get_lyric_api_token()
    lyric_cache["track_id"] = track_id
    async with ClientSession() as session:
        async with session.get(
            url=f"https://spclient.wg.spotify.com/color-lyrics/v2/track/{track_id}?format=json&vocalRemoval=false",
            headers={
                "App-Platform": "WebPlayer",
                "Authorization": f"Bearer {lyric_api_token}",
            },
            skip_auto_headers=["User-Agent", "Accept-Encoding"],
        ) as resp:
            if resp.status == 404:
                lyric_cache["lyrics"] = None
            else:
                try:
                    json = await resp.json()
                    lyric_cache["lyrics"] = json["lyrics"]
                except ContentTypeError:
                    lyric_cache["lyrics"] = None

    cache_update("lyric_cache", lyric_cache)
    return lyric_cache["lyrics"]


async def get_lyrics_at_time(track_id: str, time_ms: int) -> str:
    lyrics = await get_lyrics_from_api(track_id)
    found_words: str = "No lyrics found"
    found_words_start_time: int = 0
    _found_words = found_words
    _found_words_start_time = found_words_start_time

    # No lyrics found
    if lyrics is None or len(lyrics["lines"]) == 0:
        return found_words

    line_number: int = 0
    while (
        _found_words_start_time < time_ms
        and len(lyrics["lines"]) > line_number
    ):
        found_words = _found_words
        found_words_start_time = _found_words_start_time
        _found_words = lyrics["lines"][line_number]["words"]
        _found_words_start_time = int(lyrics["lines"][line_number]["startTimeMs"])
        line_number += 1

    return found_words


@router.get('/spotify/now-playing')
async def get_spotify_now_playing(request: Request) -> JSONResponse:
    """ Get users currently playing Spotify song. """

    bearer_token = await get_user_token()

    async with ClientSession() as session:
        async with session.get(
            url=NOW_PLAYING_ENDPOINT,
            headers={
                "Authorization": f"Bearer {bearer_token}",
            },
        ) as resp:
            if "application/json" not in resp.headers.get(
                "content-type", "no content-type header provided",
            ):
                return JSONResponse(
                    status_code=412,
                    headers={"Access-Control-Allow-Origin": "*"},
                    content={"status": "No song playing"}
                )
            spotify_data = await resp.json()
            track_id = spotify_data["item"]["id"]
            time_ms = spotify_data["progress_ms"]
            current_lyric = await get_lyrics_at_time(track_id, time_ms)
            return JSONResponse(
                status_code=resp.status,
                headers={"Access-Control-Allow-Origin": "*"},
                content={
                    "song_data": spotify_data,
                    "current_lyric": current_lyric,
                },
            )
