# Neuroity Dataset Search Engine

A backend API that aggregates dataset search results from multiple external sources into a single, unified response format. Built as part of the Neuroity backend intern assignment.

## What this project does

Instead of manually searching Kaggle, GitHub, Zenodo, HuggingFace, etc. one by one, this API lets you send **one search query** and get back a combined, cleaned-up list of matching datasets from multiple sources — all in the same format.

## Tech Stack

- **Python 3**
- **FastAPI** — web framework for building the API
- **httpx** — for making async HTTP requests to external APIs
- **asyncio** — for running multiple API calls in parallel (non-blocking)
- **SQLite** — lightweight database for users, saved datasets, and search history
- **passlib + bcrypt** — secure password hashing

## Sources Integrated (Phase 1)

| Source | Status | Notes |
|---|---|---|
| GitHub | ✅ Done | Uses GitHub Search API, filtered by "dataset" keyword |
| Zenodo | ✅ Done | Uses Zenodo REST API for scientific data records |
| OpenML | ✅ Done | Uses OpenML's classic REST API (data_name path-based search) |
| HuggingFace Datasets | ✅ Done | Uses HuggingFace Hub's public datasets search API |
| Figshare | ✅ Done | Uses Figshare API v2 (POST-based search) |
| UCI ML Repository | ✅ Done | Uses UCI's modernized dataset list API |
| OpenNeuro | ✅ Done | Uses OpenNeuro's GraphQL endpoint |
| Kaggle | ✅ Done | Uses the official Kaggle CLI tool (via subprocess) with local API credentials, rather than embedding keys in code |
| PhysioNet | 🔜 Planned | No simple public search API; most data requires credentialed/licensed access |
| Google Dataset Search | ❌ Not feasible | No public API available; would require scraping, which is fragile and against ToS |

**8 out of 10 sources from the original spec are integrated and working.**

## How to run this project

1. **Install dependencies:**
   ```
   pip install -r requirements.txt
   ```

2. **Run the server:**
   ```
   uvicorn main:app --reload
   ```

3. **Open your browser** and go to:
   ```
   http://127.0.0.1:8000
   ```

   For interactive API testing, visit:
   ```
   http://127.0.0.1:8000/docs
   ```

## API Endpoints

### 1. Home
```
GET /
```
Simple health check. Confirms the server is running.

### 2. Search (main feature)
```
GET /api/v1/search?q=eeg
```
Searches all 8 integrated sources **in parallel** (using `asyncio.gather`) and returns a combined, standardized list of results. Results are cached in-memory for a few minutes to avoid re-hitting external APIs for repeated identical queries.

**Optional filter — search only one source:**
```
GET /api/v1/search?q=eeg&source=github
GET /api/v1/search?q=eeg&source=zenodo
GET /api/v1/search?q=iris&source=openml
```

**Optional sorting:**
```
GET /api/v1/search?q=eeg&sort=latest
GET /api/v1/search?q=eeg&sort=downloads
GET /api/v1/search?q=eeg&sort=alphabetical
```

**Optional pagination:**
```
GET /api/v1/search?q=eeg&page=2&limit=5
```

**Sample response format:**
```json
{
  "success": true,
  "query": "eeg",
  "total_results": 60,
  "page": 1,
  "limit": 10,
  "total_pages": 6,
  "results": [
    {
      "title": "EEG-Datasets",
      "description": "A list of all public EEG-datasets",
      "source": "github",
      "source_url": "https://github.com/meagmohit/EEG-Datasets",
      "download_url": "https://github.com/meagmohit/EEG-Datasets",
      "license": null,
      "updated_at": "2026-07-18T12:48:09Z"
    }
  ],
  "meta": {
    "source_status": {
      "github": "ok",
      "zenodo": "ok",
      "openml": "ok",
      "huggingface": "ok",
      "figshare": "ok"
    },
    "sort": "relevance"
  }
}
```

### 3. Dataset Details
```
GET /api/v1/datasets/{dataset_id}?source=github
GET /api/v1/datasets/{dataset_id}?source=zenodo
```
Fetches full detail for a single dataset from a specific source (currently supports GitHub and Zenodo lookups by ID).

### 4. Suggestions (autocomplete)
```
GET /api/v1/suggestions?q=eeg
```
Returns keyword suggestions that match the query. Currently uses a fixed keyword list (would connect to real search analytics in a production system).

### 5. Trending
```
GET /api/v1/trending
```
Returns a list of currently trending/popular search terms. Currently uses static sample data (would be powered by real usage analytics in production).

### 6. Signup (create account)
```
POST /api/v1/signup
```
Body (JSON):
```json
{
  "email": "user@example.com",
  "password": "yourpassword"
}
```
Creates a new user. Passwords are **never stored as plain text** — they're hashed using `bcrypt` via `passlib` before being saved to the database.

### 7. Login
```
POST /api/v1/login
```
Body (JSON):
```json
{
  "email": "user@example.com",
  "password": "yourpassword"
}
```
Verifies the email exists and the password matches the stored hash.

### 8. Saved Datasets (Bookmarks)
```
POST /api/v1/saved
```
Body: `{"user_email": "...", "title": "...", "source": "...", "source_url": "..."}` — bookmarks a dataset for a user.

```
GET /api/v1/saved?user_email=...
```
Returns all datasets a user has bookmarked.

```
DELETE /api/v1/saved/{dataset_id}
```
Removes a bookmarked dataset.

### 9. Search History
```
GET /api/v1/history?user_email=...
```
Returns a user's past searches, most recent first.

```
DELETE /api/v1/history?user_email=...
```
Clears a user's search history.

**Note:** Passing `user_email` as a query param to `/api/v1/search` automatically logs that search into the user's history.

## Database

Uses **SQLite** (`neuroity.db`), a lightweight file-based database that needs no separate server/installation. Three tables:
- `users` — id, email, password_hash, created_at
- `saved_datasets` — id, user_email, title, source, source_url, saved_at
- `search_history` — id, user_email, query, searched_at

Database setup logic lives in `database.py`.

## Architecture Decisions

- **Async/parallel requests:** All 8 sources are queried at the same time using `asyncio.gather`, not one after another. Total wait time is roughly the time of the *slowest* source, not the sum of all of them — matching the assignment's requirement for non-blocking concurrent processing.
- **Standardized response schema:** Every result, regardless of source, is mapped into the same fields (`title`, `description`, `source`, `source_url`, `download_url`, `license`, `updated_at`, `downloads`) so consumers never have to handle different formats per source.
- **In-memory caching:** Identical searches within a short time window are served from an in-memory cache instead of re-querying every external API, reducing load and improving response time for repeated queries.
- **Graceful error handling:** Each source is wrapped in its own try/except with a timeout. If one source fails or times out, the API still returns results from the working sources instead of crashing. A `meta.source_status` field reports which sources succeeded and which failed, so a partial result set is never silently mistaken for a complete one.
- **Kaggle via CLI, not embedded credentials:** Kaggle's API requires authentication for every request, including search. Rather than hardcoding an API key in the source code (a security risk if the repo is public), this project shells out to the official `kaggle` CLI tool, which reads credentials from the user's local `~/.kaggle/kaggle.json` — keeping secrets out of the codebase entirely.
- **Graceful design for scaling:** Adding a new source only requires writing one new `fetch_x()` function and adding it to the `asyncio.gather()` call — the rest of the pipeline (cleaning, filtering, response formatting) already works generically.

## What's not yet implemented (future scope)

- PhysioNet and Google Dataset Search (see notes in the sources table above — both have practical barriers to a simple integration)
- Session/token-based authentication (currently login just verifies credentials; a real app would issue a JWT token so `/saved` and `/history` don't need the email passed manually each time)
- Redis-based caching (currently uses a simple in-memory dictionary, which resets on server restart and won't scale across multiple server instances)

## Setup Note for Kaggle

To use the Kaggle source, the machine running this API needs:
1. The `kaggle` CLI installed (`pip install kaggle`)
2. A valid `kaggle.json` API token placed at `~/.kaggle/kaggle.json` (generate one from Kaggle account settings)

## Author

Built by Ridhika Sharma as part of the Neuroity backend developer internship assignment.
