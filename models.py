from pydantic import BaseModel
from typing import Optional, List


class Clinic(BaseModel):
    id: str
    name_ko: str
    name_zh: str
    category: str        # 整形外科 / 皮肤科 / 牙科美容
    region: str          # gangnam / hongdae / myeongdong / busan / jeju
    region_zh: str       # 首尔·江南 / 首尔·弘大 / 首尔·明洞 / 釜山 / 济州岛
    address_ko: str
    address_zh: str
    telephone: str
    rating: float        # 0.0 - 5.0
    review_count: int
    link: str
    tags: List[str] = []  # e.g. ["隆鼻", "双眼皮", "轮廓"]
    is_demo: bool = False  # 标记是否为示例数据


class ClinicsResponse(BaseModel):
    clinics: List[Clinic]
    total: int
    source: str  # "naver_api" | "demo"
