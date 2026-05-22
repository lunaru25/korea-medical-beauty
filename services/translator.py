import time
from typing import List

from deep_translator import GoogleTranslator


def translate_ko_to_zh(texts: List[str]) -> List[str]:
    """Translate Korean to Simplified Chinese in small batches to avoid rate limits."""
    if not texts:
        return texts

    results = list(texts)  # start with originals as fallback
    batch_size = 5

    for start in range(0, len(texts), batch_size):
        batch = texts[start:start + batch_size]
        for i, text in enumerate(batch):
            try:
                translated = GoogleTranslator(source="ko", target="zh-CN").translate(text)
                if translated:
                    results[start + i] = translated
            except Exception:
                pass  # keep original on failure
        # small pause between batches to avoid rate limiting
        if start + batch_size < len(texts):
            time.sleep(0.3)

    return results


def translate_single(text_ko: str) -> str:
    return translate_ko_to_zh([text_ko])[0]
