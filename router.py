from fastapi import FastAPI

from routers.api.spotify import router as get_spotify_current_song_router


app = FastAPI()

app.include_router(get_spotify_current_song_router, prefix="")
