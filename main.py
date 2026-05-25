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

ALL_REGIONS     = ["gangnam", "hongdae", "myeongdong"]
ALL_CATEGORIES  = ["整形外科", "皮肤科"]
_CATEGORY_KEY   = {"整形外科": "plastic", "皮肤科": "skin"}

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory="static"), name="static")


@app.on_event("startup")
async def warmup_cache():
    """启动时逐个预热地区×分类缓存，避免并发触发 Naver 限速。"""
    if not has_naver_key():
        return
    async def _do_warmup():
        for region in ALL_REGIONS:
            for category in ALL_CATEGORIES:
                if _read_cache(region, category) is None:
                    data = await fetch_from_naver(region, category)
                    _write_cache(region, category, data)
                    await asyncio.sleep(2)
    asyncio.ensure_future(_do_warmup())

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


def _cache_path(region: str, category: str) -> Path:
    return CACHE_DIR / f"{region}_{_CATEGORY_KEY[category]}.json"


def _mem_key(region: str, category: str) -> str:
    return f"{region}_{category}"


def _read_cache(region: str, category: str) -> Optional[List[Dict]]:
    key = _mem_key(region, category)
    if key in _mem_cache:
        return _mem_cache[key]
    path = _cache_path(region, category)
    if path.exists():
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        _mem_cache[key] = data
        return data
    return None


def _write_cache(region: str, category: str, data: List[Dict]) -> None:
    key = _mem_key(region, category)
    _mem_cache[key] = data
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        with open(_cache_path(region, category), "w", encoding="utf-8") as f:
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
        regions_to_load = ALL_REGIONS if region == "all" else [region]
        cats_to_load    = ALL_CATEGORIES if category == "all" else [category]

        seen: Dict[str, Dict] = {}
        for r in regions_to_load:
            for c in cats_to_load:
                cached = _read_cache(r, c)
                if cached is None:
                    cached = await fetch_from_naver(r, c)
                    _write_cache(r, c, cached)
                for clinic in cached:
                    name_ko = clinic.get("name_ko", "")
                    if name_ko not in seen:
                        seen[name_ko] = clinic
        clinics = list(seen.values())
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
        ]
    }


@app.get("/api/categories")
async def get_categories():
    return {
        "categories": [
            {"code": "all",    "name": "全部分类"},
            {"code": "整形外科", "name": "整形外科"},
            {"code": "皮肤科",  "name": "皮肤科"},
        ]
    }
