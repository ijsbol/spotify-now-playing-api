/*
The MIT License (MIT)

Copyright (c) 2023-present Isabelle Phoebe

Permission is hereby granted, free of charge, to any person obtaining a
copy of this software and associated documentation files (the "Software"),
to deal in the Software without restriction, including without limitation
the rights to use, copy, modify, merge, publish, distribute, sublicense,
and/or sell copies of the Software, and to permit persons to whom the
Software is furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in
all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS
OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER
DEALINGS IN THE SOFTWARE.
*/

import "dotenv/config"
import fs from "fs"
import axios from "axios"
import {Router, Request, Response} from "express"

const NOW_PLAYING_ENDPOINT = "https://api.spotify.com/v1/me/player/currently-playing"
const TOKEN_ENDPOINT = "https://accounts.spotify.com/api/token"
const CLIENT_ID = process.env.SPOTIFY_CLIENT_ID
const CLIENT_SECRET = process.env.SPOTIFY_CLIENT_SECRET
const REFRESH_TOKEN = process.env.SPOTIFY_USER_REFRESH_TOKEN
const SPOTIFY_SP_DC = process.env.SPOTIFY_SP_DC
const SPOTIFY_SP_KEY = process.env.SPOTIFY_SP_KEY
const MAX_TIME_DELTA_BETWEEN_REFRESHES = 60 * 60 * 1000  // 1 hour
const DEFAULT_CACHE_EXPIRE_SECONDS = 12 * 60 * 60 * 1000  // 12 hours
const LYRIC_OFFSET_PADDING = 10_000  // 10 seconds (10,000ms)
const SPOTIFY_API_AUTH_TOKEN = Buffer.from(`${CLIENT_ID}:${CLIENT_SECRET}`).toString("base64")


fs.writeFileSync("cache.json", JSON.stringify({}))


interface LyricCache {
	track_id: string,
	lyrics: any
}

export const router = Router()


/** Get the cache for the provided pointer. */
function cache_get(ref: string) {
	const cache = JSON.parse(fs.readFileSync("cache.json").toString())
	return cache[ref]
}


/** Update the cache for the provided pointer. */
function cache_update(ref: string, data: any) {
	const cache = JSON.parse(fs.readFileSync("cache.json").toString())
	cache[ref] = data
	fs.writeFileSync("cache.json", JSON.stringify(cache))
	return data
}

async function get_user_token(): Promise<string> {
	const user_token_last_refreshed: number = cache_get("user_token_last_refreshed") ?? 0
	let current_user_token: string = cache_get("current_user_token") ?? ""
	if(Date.now() - user_token_last_refreshed > MAX_TIME_DELTA_BETWEEN_REFRESHES) {
		const resp = await axios({
			url: TOKEN_ENDPOINT,
			method: "POST",
			headers: {
				"Authorization": `Basic ${SPOTIFY_API_AUTH_TOKEN}`,
				"Content-Type": "application/x-www-form-urlencoded"
			},
			params: {
				"grant_type": "refresh_token",
				"refresh_token": REFRESH_TOKEN
			}
		})
		const json = resp.data
		cache_update("user_token_last_refreshed", Date.now())
		current_user_token = cache_update("current_user_token", json.access_token)
	}
	return current_user_token
}


async function get_lyric_api_token(): Promise<string> {
	let lyric_api_token_expires_at: number = cache_get("lyric_api_token_expires_at") ?? 0
	let current_lyric_api_token: string = cache_get("current_lyric_api_token") ?? ""
	if(Date.now() > (lyric_api_token_expires_at - LYRIC_OFFSET_PADDING)) {
		const headers = {"FAKEHEADERs": "TODO"}
		const resp = await axios({
			url: "https://open.spotify.com/get_access_token",
			method: "GET",
			headers: {
				...headers,
				"Cookie": `sp_dc=${SPOTIFY_SP_DC}; sp_key=${SPOTIFY_SP_KEY};`
			},
			params: {
				"reason": "web-player",
				"productType": "web-player"
			}
		})
		const json = resp.data
		lyric_api_token_expires_at = cache_update("lyric_api_token_expires_at", json.accessTokenExpirationTimestampMs)
		current_lyric_api_token = cache_update("current_lyric_api_token", json.accesstoken)
	}
	return current_lyric_api_token
}


async function get_lyrics_from_api(track_id: string) {
	const lyric_cache: LyricCache = cache_get("lyric_cache") ?? {track_id: "", lyrics: null}
	if(lyric_cache.track_id === track_id)
		return lyric_cache.lyrics

	const lyric_api_token = await get_lyric_api_token()
	lyric_cache.track_id = track_id
	const resp = await axios({
		url: `https://spclient.wg.spotify.com/color-lyrics/v2/track/${track_id}?format=json&vocalRemoval=false`,
		method: "GET",
		headers: {
			"App-Platform": "WebPlayer",
			"Authorization": `Bearer ${lyric_api_token}`,
		},
		transformRequest: (data, headers) => {
			["User-Agent", "Accept-Encoding"].forEach(header => delete headers[header])
			return data
		}
	})
	if(resp.status === 404) {
		lyric_cache.lyrics = null
	} else {
		lyric_cache.lyrics = resp.data.lyrics
	}
	cache_update("lyric_cache", lyric_cache)
	return lyric_cache.lyrics
}


async function get_lyrics_at_time(track_id: string, time_ms: number): Promise<string> {
	const lyrics = await get_lyrics_from_api(track_id)
	let found_words = "No lyrics found"
	let found_words_start_time = 0
	let _found_words = found_words
	let _found_words_start_time = found_words_start_time

	// No lyrics found
	if(lyrics == null || lyrics.lines.length === 0)
		return found_words

	let line_number = 0
	while(
		_found_words_start_time < time_ms
		&& lyrics.lines.length > line_number
	) {
		found_words = _found_words
		found_words_start_time = _found_words_start_time
		_found_words = lyrics.lines[line_number].words
		_found_words_start_time = parseInt(lyrics.lines[line_number].startTimeMs)
		line_number += 1
	}

	return found_words
}


/** Get users currently playing Spotify song. */
router.get("/spotify/now-playing", async function get_spotify_now_playing(request: Request, response: Response) {
	const bearer_token = await get_user_token()

	const resp = await axios({
		url: NOW_PLAYING_ENDPOINT,
		headers: {
			"Authorization": `Bearer ${bearer_token}`
		}
	})
	if(resp.headers["Content-Type"] !== "application/json") {
		return response
			.status(412)
			.header("Access-Control-Allow-Origin", "*")
			.json({"status": "No song playing"})
	}
	const spotify_data: Record<string, any> = resp.data
	const track_id: string = spotify_data.item.id
	const time_ms: number = spotify_data.progress_ms
	let current_lyric = "Lyric fetching disabled."
	if(request.query.include_lyrics !== "false")
		current_lyric = await get_lyrics_at_time(track_id, time_ms)
	return response
		.status(resp.status)
		.header("Access-Control-Allow-Origin", "*")
		.json({
			"song_data": spotify_data,
			"current_lyric": current_lyric
		})
})