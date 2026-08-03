from fastapi.middleware.cors import CORSMiddleware
import time
from fastapi import FastAPI
import httpx
import asyncio
import subprocess
import json
from database import get_connection, init_db
from passlib.context import CryptContext
from pydantic import BaseModel

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

init_db()

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
CACHE = {}
CACHE_TTL = 300


class UserSignup(BaseModel):
    email: str
    password: str


class SaveDataset(BaseModel):
    user_email: str
    title: str
    source: str
    source_url: str


@app.get("/")
def home():
    return {"message": "Neuroity backend chal raha hai!"}


async def fetch_github(client, q):
    try:
        response = await client.get(
            "https://api.github.com/search/repositories",
            params={"q": f"{q} dataset"},
            timeout=5.0
        )
        return {"ok": True, "data": response.json()}
    except Exception as e:
        return {"ok": False, "error": str(e)}


async def fetch_zenodo(client, q):
    try:
        response = await client.get(
            "https://zenodo.org/api/records",
            params={"q": q, "size": 10},
            timeout=5.0
        )
        return {"ok": True, "data": response.json()}
    except Exception as e:
        return {"ok": False, "error": str(e)}


async def fetch_openml(client, q):
    try:
        response = await client.get(
            f"https://www.openml.org/api/v1/json/data/list/data_name/{q}/limit/10",
            timeout=5.0
        )
        return {"ok": True, "data": response.json()}
    except Exception as e:
        return {"ok": False, "error": str(e)}


async def fetch_huggingface(client, q):
    try:
        response = await client.get(
            "https://huggingface.co/api/datasets",
            params={"search": q, "limit": 10},
            timeout=5.0
        )
        return {"ok": True, "data": response.json()}
    except Exception as e:
        return {"ok": False, "error": str(e)}


async def fetch_figshare(client, q):
    try:
        response = await client.post(
            "https://api.figshare.com/v2/articles/search",
            json={"search_for": q, "page_size": 10},
            timeout=5.0
        )
        return {"ok": True, "data": response.json()}
    except Exception as e:
        return {"ok": False, "error": str(e)}


async def fetch_uci(client, q):
    try:
        response = await client.get(
            "https://archive.ics.uci.edu/api/dataset/list",
            params={"search": q},
            timeout=5.0
        )
        # Pehle check karo status code aur content valid JSON hai ya nahi
        if response.status_code != 200:
            return {"ok": False, "error": f"HTTP {response.status_code} - endpoint may be outdated"}

        try:
            data = response.json()
        except Exception:
            return {"ok": False, "error": "Response was not valid JSON (endpoint likely changed)"}

        return {"ok": True, "data": data}
    except Exception as e:
        return {"ok": False, "error": str(e)}


async def fetch_openneuro(client, q):
    # OpenNeuro REST/GraphQL hybrid endpoint use kar rahe hain
    try:
        graphql_query = """
        query Search($q: String) {
          datasets(query: $q, first: 10) {
            edges {
              node {
                id
                latestSnapshot {
                  description {
                    Name
                  }
                }
              }
            }
          }
        }
        """
        response = await client.post(
            "https://openneuro.org/crn/graphql",
            json={"query": graphql_query, "variables": {"q": q}},
            timeout=5.0
        )
        return {"ok": True, "data": response.json()}
    except Exception as e:
        return {"ok": False, "error": str(e)}

import subprocess
import csv
from io import StringIO

async def fetch_kaggle(query: str):
    print("fetch_kaggle called")
    try:
        print("Before subprocess")
        result = subprocess.run(
            ["kaggle", "datasets", "list", "-s", query, "--csv"],
            capture_output=True,
            text=True
        )
        print("After subprocess")
        print("Return Code:", result.returncode)
        print("STDOUT:", result.stdout[:300])
        print("STDERR:", result.stderr)

        if result.returncode != 0:
            return []

        reader = csv.DictReader(StringIO(result.stdout))
        datasets = []
        for row in reader:
            datasets.append({
                "title": row.get("title", ""),
                "description": "",
                "source": "kaggle",
                "source_url": f"https://www.kaggle.com/datasets/{row.get('ref', '')}",
                "download_url": f"https://www.kaggle.com/datasets/{row.get('ref', '')}",
                "license": None,
                "updated_at": None,
                "downloads": 0
            })
        print("Kaggle datasets found:", len(datasets))
        return datasets
    except Exception as e:
        print("Kaggle Error:", e)
        return []
@app.get("/api/v1/search")
async def search(q: str, source: str = None, sort: str = "relevance", page: int = 1, limit: int = 10, user_email: str = None):
    cache_key = f"{q}_{source}_{sort}_{page}_{limit}_{user_email}"

    if cache_key in CACHE:
        cached = CACHE[cache_key]

        if time.time() - cached["timestamp"] < CACHE_TTL:
            print("✅ Cache HIT")
            return cached["response"]

    print("❌ Cache MISS")
    async with httpx.AsyncClient() as client:
        github_result, zenodo_result, openml_result, hf_result, figshare_result, uci_result, openneuro_result,kaggle_result = await asyncio.gather(
            fetch_github(client, q),
            fetch_zenodo(client, q),
            fetch_openml(client, q),
            fetch_huggingface(client, q),
            fetch_figshare(client, q),
            fetch_uci(client, q),
            fetch_openneuro(client, q),
            fetch_kaggle(q),
        )

    clean_results = []
    source_status = {}

    if github_result["ok"]:
        for item in github_result["data"].get("items", []):
            clean_results.append({
                "title": item.get("name"),
                "description": item.get("description"),
                "source": "github",
                "source_url": item.get("html_url"),
                "download_url": item.get("html_url"),
                "license": item.get("license", {}).get("name") if item.get("license") else None,
                "updated_at": item.get("updated_at"),
                "downloads": item.get("stargazers_count", 0)
            })
        source_status["github"] = "ok"
    else:
        source_status["github"] = f"failed: {github_result['error']}"

    if zenodo_result["ok"]:
        for item in zenodo_result["data"].get("hits", {}).get("hits", []):
            metadata = item.get("metadata", {})
            clean_results.append({
                "title": metadata.get("title"),
                "description": metadata.get("description"),
                "source": "zenodo",
                "source_url": item.get("links", {}).get("self_html"),
                "download_url": item.get("links", {}).get("self_html"),
                "license": metadata.get("license", {}).get("id") if metadata.get("license") else None,
                "updated_at": metadata.get("publication_date"),
                "downloads": 0
            })
        source_status["zenodo"] = "ok"
    else:
        source_status["zenodo"] = f"failed: {zenodo_result['error']}"

    if openml_result["ok"]:
        try:
            datasets = openml_result["data"].get("data", {}).get("dataset", [])
            for item in datasets:
                did = item.get("did")
                clean_results.append({
                    "title": item.get("name"),
                    "description": None,
                    "source": "openml",
                    "source_url": f"https://www.openml.org/d/{did}",
                    "download_url": f"https://www.openml.org/d/{did}",
                    "license": None,
                    "updated_at": None,
                    "downloads": 0
                })
            source_status["openml"] = "ok"
        except Exception as e:
            source_status["openml"] = f"failed to parse: {str(e)}"
    else:
        source_status["openml"] = f"failed: {openml_result['error']}"

    if hf_result["ok"]:
        try:
            for item in hf_result["data"]:
                dataset_id = item.get("id")
                clean_results.append({
                    "title": dataset_id,
                    "description": None,
                    "source": "huggingface",
                    "source_url": f"https://huggingface.co/datasets/{dataset_id}",
                    "download_url": f"https://huggingface.co/datasets/{dataset_id}",
                    "license": None,
                    "updated_at": item.get("lastModified"),
                    "downloads": item.get("downloads", 0)
                })
            source_status["huggingface"] = "ok"
        except Exception as e:
            source_status["huggingface"] = f"failed to parse: {str(e)}"
    else:
        source_status["huggingface"] = f"failed: {hf_result['error']}"

    if figshare_result["ok"]:
        try:
            for item in figshare_result["data"]:
                clean_results.append({
                    "title": item.get("title"),
                    "description": None,
                    "source": "figshare",
                    "source_url": item.get("url_public_html"),
                    "download_url": item.get("url_public_html"),
                    "license": None,
                    "updated_at": item.get("published_date"),
                    "downloads": 0
                })
            source_status["figshare"] = "ok"
        except Exception as e:
            source_status["figshare"] = f"failed to parse: {str(e)}"
    else:
        source_status["figshare"] = f"failed: {figshare_result['error']}"

    if uci_result["ok"]:
        try:
            datasets = uci_result["data"].get("data", [])
            for item in datasets:
                uci_id = item.get("id")
                clean_results.append({
                    "title": item.get("name"),
                    "description": item.get("abstract"),
                    "source": "uci",
                    "source_url": f"https://archive.ics.uci.edu/dataset/{uci_id}",
                    "download_url": f"https://archive.ics.uci.edu/dataset/{uci_id}",
                    "license": None,
                    "updated_at": None,
                    "downloads": 0
                })
            source_status["uci"] = "ok"
        except Exception as e:
            source_status["uci"] = f"failed to parse: {str(e)}"
    else:
        source_status["uci"] = f"failed: {uci_result['error']}"

    # OpenNeuro results ko saaf karo
    if openneuro_result["ok"]:
        try:
            edges = openneuro_result["data"].get("data", {}).get("datasets", {}).get("edges", [])
            for edge in edges:
                node = edge.get("node", {})
                dataset_id = node.get("id")
                name = node.get("latestSnapshot", {}).get("description", {}).get("Name")
                clean_results.append({
                    "title": name,
                    "description": None,
                    "source": "openneuro",
                    "source_url": f"https://openneuro.org/datasets/{dataset_id}",
                    "download_url": f"https://openneuro.org/datasets/{dataset_id}",
                    "license": None,
                    "updated_at": None,
                    "downloads": 0
                })
            source_status["openneuro"] = "ok"
        except Exception as e:
            source_status["openneuro"] = f"failed to parse: {str(e)}"
    else:
        source_status["openneuro"] = f"failed: {openneuro_result['error']}"
    
    if kaggle_result:
        clean_results.extend(kaggle_result)
        source_status["Kaggle"] = "Success"
    else:
        source_status["Kaggle"] = "No Results"

    if sort == "latest":
        clean_results.sort(key=lambda r: r["updated_at"] or "", reverse=True)
    elif sort == "downloads":
        clean_results.sort(key=lambda r: r["downloads"], reverse=True)
    elif sort == "alphabetical":
        clean_results.sort(key=lambda r: (r["title"] or "").lower())
       
    total = len(clean_results)
    start = (page - 1) * limit
    end = start + limit
    paginated_results = clean_results[start:end]

    
    return {
        "success": True,
        "query": q,
        "total_results": total,
        "page": page,
        "limit": limit,
        "total_pages": (total + limit - 1) // limit,
        "results": paginated_results,
        "meta": {
            "source_status": source_status,
            "sort": sort
        }
    }


@app.get("/api/v1/suggestions")
def suggestions(q: str):
    popular_keywords = [
        "eeg", "ecg", "emotion recognition", "medical imaging",
        "nlp sentiment", "image classification", "stock price",
        "covid dataset", "audio speech", "computer vision"
    ]
    matches = [k for k in popular_keywords if q.lower() in k.lower()]
    return {"success": True, "query": q, "suggestions": matches}


@app.get("/api/v1/trending")
def trending():
    trending_searches = [
        {"query": "eeg stress detection", "search_count": 1240},
        {"query": "covid-19 chest xray", "search_count": 980},
        {"query": "emotion recognition dataset", "search_count": 875},
        {"query": "nlp sentiment analysis", "search_count": 760}
    ]
    return {"success": True, "trending": trending_searches}


@app.post("/api/v1/signup")
def signup(user: UserSignup):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM users WHERE email = ?", (user.email,))
    existing = cursor.fetchone()
    if existing:
        conn.close()
        return {"success": False, "message": "Ye email already registered hai"}

    hashed_password = pwd_context.hash(user.password)

    cursor.execute(
        "INSERT INTO users (email, password_hash) VALUES (?, ?)",
        (user.email, hashed_password)
    )
    conn.commit()
    conn.close()

    return {"success": True, "message": "Signup ho gaya!"}


@app.post("/api/v1/login")
def login(user: UserSignup):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM users WHERE email = ?", (user.email,))
    db_user = cursor.fetchone()
    conn.close()

    if not db_user:
        return {"success": False, "message": "Email nahi mila"}

    if not pwd_context.verify(user.password, db_user["password_hash"]):
        return {"success": False, "message": "Password galat hai"}

    return {"success": True, "message": "Login successful!"}


@app.post("/api/v1/saved")
def save_dataset(item: SaveDataset):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO saved_datasets (user_email, title, source, source_url) VALUES (?, ?, ?, ?)",
        (item.user_email, item.title, item.source, item.source_url)
    )
    conn.commit()
    conn.close()
    return {"success": True, "message": "Dataset save ho gaya!"}


@app.get("/api/v1/saved")
def get_saved_datasets(user_email: str):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM saved_datasets WHERE user_email = ?", (user_email,))
    rows = cursor.fetchall()
    conn.close()

    results = [dict(row) for row in rows]
    return {"success": True, "user_email": user_email, "saved_datasets": results}


@app.delete("/api/v1/saved/{dataset_id}")
def delete_saved_dataset(dataset_id: int):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM saved_datasets WHERE id = ?", (dataset_id,))
    conn.commit()
    conn.close()
    return {"success": True, "message": "Dataset removed"}


@app.get("/api/v1/history")
def get_search_history(user_email: str):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT * FROM search_history WHERE user_email = ? ORDER BY searched_at DESC",
        (user_email,)
    )
    rows = cursor.fetchall()
    conn.close()

    results = [dict(row) for row in rows]
    return {"success": True, "user_email": user_email, "history": results}


@app.delete("/api/v1/history")
def clear_search_history(user_email: str):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM search_history WHERE user_email = ?", (user_email,))
    conn.commit()
    conn.close()
    return {"success": True, "message": "History clear ho gayi"}
@app.get("/api/v1/datasets/{dataset_id}")
async def dataset_details(dataset_id: str, source: str):
    async with httpx.AsyncClient() as client:

        if source == "github":
            response = await client.get(
                f"https://api.github.com/repos/{dataset_id}"
            )

            if response.status_code != 200:
                return {
                    "success": False,
                    "message": "Dataset not found"
                }

            repo = response.json()

            return {
                "success": True,
                "title": repo.get("name"),
                "description": repo.get("description"),
                "source": "github",
                "author": repo.get("owner", {}).get("login"),
                "license": repo.get("license", {}).get("name") if repo.get("license") else None,
                "download_url": repo.get("html_url"),
                "source_url": repo.get("html_url"),
                "updated_at": repo.get("updated_at")
            }

        elif source == "zenodo":
            response = await client.get(
                f"https://zenodo.org/api/records/{dataset_id}"
            )

            if response.status_code != 200:
                return {
                    "success": False,
                    "message": "Dataset not found"
                }

            item = response.json()
            metadata = item.get("metadata", {})

            return {
                "success": True,
                "title": metadata.get("title"),
                "description": metadata.get("description"),
                "source": "zenodo",
                "author": metadata.get("creators"),
                "license": metadata.get("license"),
                "download_url": item.get("links", {}).get("self_html"),
                "source_url": item.get("links", {}).get("self_html"),
                "updated_at": metadata.get("publication_date")
            }

        return {
            "success": False,
            "message": "Source not supported yet"
        }