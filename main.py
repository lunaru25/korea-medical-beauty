import json
import os
from pathlib import Path
from typing import Dict, List, Optional

from dotenv import load_dotenv
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from services.naver import fetch_from_naver

load_dotenv()

app = FastAPI(title="韩国医美机构评分排行")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory="static"), name="static")

SEED_FILE = Path("data/clinics_seed.json")

# 内存缓存：key = region，value = 机构列表
# 服务运行期间持久，重启后首次访问时自动重新抓取
_cache: Dict[str, List[Dict]] = {}


def load_seed_data() -> List[Dict]:
    if SEED_FILE.exists():
        with open(SEED_FILE, encoding="utf-8") as f:
            return json.load(f)
    return []


def filter_clinics(clinics: List[Dict], region: str, category: str) -> List[Dict]:
    result = clinics
    if region != "all":
        result = [c for c in result if c.get("region") == region]
    if category != "all":
        result = [c for c in result if c.get("category") == category]
    return result


def has_naver_key() -> bool:
    key = os.getenv("NAVER_CLIENT_ID", "")
    return bool(key and key != "your_naver_client_id")


@app.get("/")
async def root():
    return FileResponse("static/index.html")


@app.get("/api/clinics")
async def get_clinics(
    region: str = Query("all"),
    category: str = Query("all"),
    sort: str = Query("rating"),
    q: Optional[str] = Query(None),
):
    if has_naver_key():
        if region == "all":
            all_regions = ["gangnam", "hongdae", "myeongdong", "busan", "jeju"]
            all_clinics: List[Dict] = []
            for r in all_regions:
                if r in _cache:
                    all_clinics.extend(_cache[r])
            clinics = filter_clinics(all_clinics, region, category)
        else:
            if region not in _cache:
                _cache[region] = await fetch_from_naver(region)
            clinics = filter_clinics(_cache[region], region, category)
        source = "naver_api"
    else:
        clinics = filter_clinics(load_seed_data(), region, category)
        source = "demo"

    if q:
        q_lower = q.lower()
        clinics = [
            c for c in clinics
            if q_lower in c.get("name_zh", "").lower()
            or q_lower in c.get("name_ko", "").lower()
            or q_lower in c.get("address_zh", "").lower()
            or any(q_lower in tag for tag in c.get("tags", []))
        ]

    key = "rating" if sort == "rating" else "review_count"
    clinics.sort(key=lambda x: x.get(key, 0), reverse=True)

    return JSONResponse({"clinics": clinics, "total": len(clinics), "source": source})


@app.get("/api/status")
async def get_status():
    return {"has_naver_key": has_naver_key()}


@app.get("/api/regions")
async def get_regions():
    return {
        "regions": [
            {"code": "all",        "name": "全部地区"},
            {"code": "gangnam",    "name": "首尔·江南"},
            {"code": "hongdae",    "name": "首尔·弘大"},
            {"code": "myeongdong", "name": "首尔·明洞"},
            {"code": "busan",      "name": "釜山"},
            {"code": "jeju",       "name": "济州岛"},
        ]
    }


@app.get("/api/categories")
async def get_categories():
    return {
        "categories": [
            {"code": "all",    "name": "全部分类"},
            {"code": "整形外科", "name": "整形外科"},
            {"code": "皮肤科",  "name": "皮肤科"},
            {"code": "牙科美容", "name": "牙科美容"},
        ]
    }
