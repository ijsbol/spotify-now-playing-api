from os import getenv
from typing import Final, cast
from fastapi import FastAPI
from starlette.middleware.sessions import SessionMiddleware

from routers.api.spotify import router as get_spotify_current_song_router


SESSION_MIDDLEWARE_SECRET_KEY: Final[str] = cast(str, getenv("SESSION_MIDDLEWARE_SECRET_KEY"))


app = FastAPI()

app.add_middleware(
    middleware_class=SessionMiddleware,
    secret_key=SESSION_MIDDLEWARE_SECRET_KEY,
)

app.include_router(get_spotify_current_song_router, prefix="")
