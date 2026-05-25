import asyncio
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

ALL_REGIONS = ["gangnam", "hongdae", "myeongdong", "busan", "jeju"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory="static"), name="static")


@app.on_event("startup")
async def warmup_cache():
    """启动时后台预热所有地区缓存，保证结果稳定。"""
    if not has_naver_key():
        return
    async def _warm(region: str):
        if _read_cache(region) is None:
            data = await fetch_from_naver(region)
            _write_cache(region, data)
    await asyncio.gather(*[_warm(r) for r in ALL_REGIONS])

SEED_FILE  = Path("data/clinics_seed.json")
# CACHE_DIR 优先使用环境变量指定的持久磁盘路径（Render），否则使用本地
CACHE_DIR  = Path(os.getenv("CACHE_DIR", "data/cache"))

# 内存缓存：作为文件缓存的二级加速
_mem_cache: Dict[str, List[Dict]] = {}


def load_seed_data() -> List[Dict]:
    if SEED_FILE.exists():
        with open(SEED_FILE, encoding="utf-8") as f:
            return json.load(f)
    return []


def _cache_path(region: str) -> Path:
    return CACHE_DIR / f"{region}.json"


def _read_cache(region: str) -> Optional[List[Dict]]:
    if region in _mem_cache:
        return _mem_cache[region]
    path = _cache_path(region)
    if path.exists():
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        _mem_cache[region] = data
        return data
    return None


def _write_cache(region: str, data: List[Dict]) -> None:
    _mem_cache[region] = data
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        with open(_cache_path(region), "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
    except OSError:
        pass  # 磁盘不可写时仅保留内存缓存


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
            all_regions = ALL_REGIONS
            all_clinics: List[Dict] = []
            for r in all_regions:
                cached = _read_cache(r)
                if cached:
                    all_clinics.extend(cached)
            clinics = filter_clinics(all_clinics, region, category)
        else:
            cached = _read_cache(region)
            if cached is None:
                cached = await fetch_from_naver(region)
                _write_cache(region, cached)
            clinics = filter_clinics(cached, region, category)
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
