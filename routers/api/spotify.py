import base64
from os import getenv
import time
from typing import Any, Dict, Final, TypedDict, cast

from aiohttp import ClientSession
from dotenv import load_dotenv
from fastapi import APIRouter, Request
from fake_headers import Headers
from starlette.responses import JSONResponse


load_dotenv()


router = APIRouter()


class LyricCache(TypedDict):
    track_id: str
    lyrics: Any


NOW_PLAYING_ENDPOINT: Final[str] = "https://api.spotify.com/v1/me/player/currently-playing"
TOKEN_ENDPOINT: Final[str] = "https://accounts.spotify.com/api/token"
CLIENT_ID = cast(str, getenv("SPOTIFY_CLIENT_ID"))
CLIENT_SECRET = cast(str, getenv("SPOTIFY_CLIENT_SECRET"))
REFRESH_TOKEN = cast(str, getenv("SPOTIFY_ISABELLE_REFRESH_TOKEN"))
SPOTIFY_SP_DC = cast(str, getenv("SPOTIFY_SP_DC"))
SPOTIFY_SP_KEY = cast(str, getenv("SPOTIFY_SP_KEY"))
MAX_TIME_DELTA_BETWEEN_REFRESHES: Final[int] = 60 * 60  # 1 hour


global isabelle_token_last_refreshed
global lyric_api_token_expires_at
global current_isabelle_token
global current_lyric_api_token
isabelle_token_last_refreshed: float = 0
lyric_api_token_expires_at: float = 0
current_isabelle_token: str = ""
current_lyric_api_token: str = ""


global lyric_cache
lyric_cache: LyricCache = LyricCache(track_id="", lyrics=None)


def generate_auth() -> str:
    return base64.b64encode(f"{CLIENT_ID}:{CLIENT_SECRET}".encode("ascii")).decode("utf-8")


async def get_isabelle_token() -> str:
    global isabelle_token_last_refreshed
    global current_isabelle_token
    if (time.time() - isabelle_token_last_refreshed) > MAX_TIME_DELTA_BETWEEN_REFRESHES:
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
                isabelle_token_last_refreshed = time.time()
                current_isabelle_token = json["access_token"]
    return current_isabelle_token



async def get_lyric_api_token() -> str:
    global lyric_api_token_expires_at
    global current_lyric_api_token
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
                lyric_api_token_expires_at = json["accessTokenExpirationTimestampMs"]
                current_lyric_api_token = json["accessToken"]
    return current_lyric_api_token


async def get_lyrics_from_api(track_id: str) -> Any:
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
                json = await resp.json()
                lyric_cache["lyrics"] = json["lyrics"]
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
    """ Get Isabelles currently playing Spotify song. """

    bearer_token = await get_isabelle_token()

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
