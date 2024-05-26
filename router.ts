import express from "express"

import { router as get_spotify_current_song_router } from "./routers/api/spotify";


const app = express()

app.use("/", get_spotify_current_song_router)

app.listen(7900, "127.0.0.1")