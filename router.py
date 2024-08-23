from os import getenv
from typing import Final, cast
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from routers.api.spotify import router as get_spotify_current_song_router


app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(get_spotify_current_song_router, prefix="")
