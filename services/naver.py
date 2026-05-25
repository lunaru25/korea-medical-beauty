import asyncio
import math
import os
import re
from typing import Dict, List, Tuple

import httpx
from services.translator import translate_ko_to_zh

LOCAL_API_URL = "https://openapi.naver.com/v1/search/local.json"
BLOG_API_URL  = "https://openapi.naver.com/v1/search/blog.json"

# 每个地区独立配置搜索前缀（覆盖多个商圈）
REGION_CONFIG = {
    "gangnam":    (["강남", "압구정", "청담", "역삼", "신사"], "首尔·江南"),
    "hongdae":    (["홍대", "신촌", "합정", "마포"],           "首尔·弘大"),
    "myeongdong": (["명동", "중구", "을지로"],                  "首尔·明洞"),
}

# 分类专属搜索词：按科室定向搜索
CATEGORY_KEYWORDS: Dict[str, List[str]] = {
    "整形外科": ["성형외과", "쌍꺼풀", "코성형", "윤곽수술", "지방흡입"],
    "皮肤科":   ["피부과", "보톡스", "필러", "레이저", "리프팅", "피부관리"],
}

CATEGORY_MAP = {
    "성형외과": "整形外科",
    "피부과":   "皮肤科",
}

TAG_MAP = {
    "쌍꺼풀": "双眼皮", "코": "隆鼻", "윤곽": "轮廓", "지방흡입": "脂肪吸脂",
    "보톡스": "肉毒素", "필러": "填充", "리프팅": "提拉", "레이저": "激光",
    "여드름": "祛痘", "미백": "美白", "피부관리": "皮肤管理",
}


def _strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text)


def _detect_category(raw: str) -> str:
    for ko, zh in CATEGORY_MAP.items():
        if ko in raw:
            return zh
    return "整形外科"


def _detect_tags(text: str) -> List[str]:
    return [zh for ko, zh in TAG_MAP.items() if ko in text]


def _normalize_ratings(counts: List[int]) -> List[float]:
    """Map blog counts to 3.5–5.0 within this result set (log scale, relative)."""
    if not counts:
        return []
    log_counts = [math.log10(max(c, 1)) for c in counts]
    lo, hi = min(log_counts), max(log_counts)
    result = []
    for lc in log_counts:
        score = 4.5 if hi == lo else 3.5 + (lc - lo) / (hi - lo) * 1.5
        result.append(round(score, 1))
    return result


async def _fetch_local(
    client: httpx.AsyncClient,
    headers: dict,
    query: str,
    sem: asyncio.Semaphore,
) -> List[dict]:
    async with sem:
        try:
            resp = await client.get(
                LOCAL_API_URL,
                params={"query": query, "display": 5, "sort": "comment"},
                headers=headers,
                timeout=10,
            )
            return resp.json().get("items", [])
        except Exception:
            return []


async def _fetch_blog_count(
    client: httpx.AsyncClient,
    headers: dict,
    name: str,
    sem: asyncio.Semaphore,
) -> int:
    async with sem:
        try:
            resp = await client.get(
                BLOG_API_URL,
                params={"query": f"{name} 후기", "display": 1},
                headers=headers,
                timeout=10,
            )
            return resp.json().get("total", 0)
        except Exception:
            return 0


async def fetch_from_naver(region: str, category: str) -> List[Dict]:
    client_id     = os.getenv("NAVER_CLIENT_ID", "")
    client_secret = os.getenv("NAVER_CLIENT_SECRET", "")

    if not client_id or client_id == "your_naver_client_id":
        return []

    prefixes, region_zh = REGION_CONFIG.get(region, REGION_CONFIG["gangnam"])
    keywords = CATEGORY_KEYWORDS.get(category, [])
    headers = {
        "X-Naver-Client-Id": client_id,
        "X-Naver-Client-Secret": client_secret,
    }

    async with httpx.AsyncClient(timeout=15) as client:
        # 1. 所有前缀 × 分类关键词 并发查询（最多5个同时）
        queries = [f"{p} {kw}" for p in prefixes for kw in keywords]
        local_sem = asyncio.Semaphore(5)
        results = await asyncio.gather(
            *[_fetch_local(client, headers, q, local_sem) for q in queries]
        )

        # 2. 合并，按机构名去重，过滤牙科诊所
        seen: Dict[str, dict] = {}
        for items in results:
            for item in items:
                name = _strip_html(item["title"])
                raw_cat = item.get("category", "")
                if "치과" in name or "치과" in raw_cat:
                    continue
                if name not in seen:
                    seen[name] = item

        unique_items = list(seen.values())

        # 3. 限速并发获取博客后记数量（最多5个同时请求，避免触发限速）
        names_ko = [_strip_html(item["title"]) for item in unique_items]
        sem = asyncio.Semaphore(5)
        blog_counts = await asyncio.gather(
            *[_fetch_blog_count(client, headers, name, sem) for name in names_ko]
        )

    # 4. 在结果集内归一化评分（无门槛过滤，全部显示）
    ratings  = _normalize_ratings(list(blog_counts))
    addrs_ko = [item.get("roadAddress") or item.get("address", "") for item in unique_items]
    names_zh = translate_ko_to_zh(names_ko)
    addrs_zh = translate_ko_to_zh(addrs_ko)

    clinics = []
    for i, item in enumerate(unique_items):
        clinics.append({
            "id":           f"naver_{region}_{i}",
            "name_ko":      names_ko[i],
            "name_zh":      names_zh[i],
            "category":     category,
            "region":       region,
            "region_zh":    region_zh,
            "address_ko":   addrs_ko[i],
            "address_zh":   addrs_zh[i],
            "telephone":    item.get("telephone", ""),
            "rating":       ratings[i],
            "review_count": blog_counts[i],
            "link":         item.get("link", ""),
            "tags":         _detect_tags(_strip_html(item.get("description", ""))),
            "is_demo":      False,
        })

    return clinics
