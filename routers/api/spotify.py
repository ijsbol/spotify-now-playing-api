import base64
from os import getenv
import time
from typing import Final, cast

from aiohttp import ClientSession
from dotenv import load_dotenv
from fastapi import APIRouter, Request
from starlette.responses import JSONResponse


load_dotenv()


router = APIRouter()


NOW_PLAYING_ENDPOINT: Final[str] = "https://api.spotify.com/v1/me/player/currently-playing"
TOKEN_ENDPOINT: Final[str] = "https://accounts.spotify.com/api/token"
CLIENT_ID = cast(str, getenv("SPOTIFY_CLIENT_ID"))
CLIENT_SECRET = cast(str, getenv("SPOTIFY_CLIENT_SECRET"))
REFRESH_TOKEN = cast(str, getenv("SPOTIFY_ISABELLE_REFRESH_TOKEN"))
MAX_TIME_DELTA_BETWEEN_REFRESHES: Final[int] = 60 * 60  # 1 hour


global isabelle_token_last_refreshed
global current_isabelle_token
isabelle_token_last_refreshed: float = 0
current_isabelle_token: str = ""


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
            return JSONResponse(
                status_code=resp.status,
                headers={
                    "Access-Control-Allow-Origin": "*",
                },
                content=await resp.json(),
            )