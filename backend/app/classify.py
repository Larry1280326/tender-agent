"""招標分類：判斷是否香港 + 是否政府部門（用嚟過濾「香港非政府」招標）。

策略（hybrid）：
1. 關鍵字快速過濾（標題／slug 含政府部門字眼 → 政府；含外國訊號 → 非香港）。
2. 邊界／模糊案例可選用 Jina Reader 抽取招標方後再分類（deep_check）。
"""
from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor

from . import config
from .services import reader
from .services.common import TTLCache

logger = logging.getLogger(__name__)

# 政府部門關鍵字（正體中文 + 英文）。故意唔包含法定機構（醫院管理局、大學、房委會等）。
# 避免用單字「署/處/局/司」做 keyword（非政府機構名都常含「辦事處/秘書處」）。
GOV_ZH = (
    "政府", "部門", "懲教署", "水務署", "屋宇署", "建築署", "衞生署", "衛生署",
    "入境事務處", "海關", "警務處", "消防處", "庫務署", "政府物流服務署", "地政總署",
    "渠務署", "路政署", "機電工程署", "海事處", "民航處", "天文台", "稅務局",
    "差餉物業估價署", "土地註冊處", "政府統計處", "政府產業署", "教育局", "勞工處",
    "社會福利署", "房屋署", "運輸署", "環境保護署", "政府新聞處", "效率促進辦公室",
    "數碼政府", "民政事務總署", "康樂及文化事務署", "食物環境衞生署", "食物環境衛生署",
    "漁農自然護理署", "律政司", "保安局", "發展局", "運輸及物流局", "房屋局",
    "醫務衞生局", "商務及經濟發展局", "創新科技及工業局", "環境及生態局",
    "財經事務及庫務局", "政府飛行服務隊", "知識產權署", "公司註冊處", "土木工程拓展署"
)
GOV_EN = (
    "government", "govhk", "department of", "correctional services",
    "water supplies", "buildings department", "architectural services",
    "leisure and cultural services", "food and environmental hygiene",
    "immigration", "customs", "police", "fire services", "treasury",
    "housing department", "transport department", "environmental protection",
    "education bureau", "labour department", "social welfare", "government flying service", "civil engineering and development department"
)

# 外國／非香港訊號
FOREIGN_ZH = ("新加坡", "台灣", "新北市", "臺北", "臺北市", "內地", "中國內地", "廣州", "深圳", "上海", "北京")
FOREIGN_EN = ("singapore", "taiwan", "mainland china", "new taipei", "mas building", "hdb")

# 非港機構關鍵字（用喺 issuer／全文過濾）。刻意唔落短縮寫（hdb/lta/ura），
# 以免 substring 誤傷「rural/natural」等字。
FOREIGN_ISSUER_ZH = (
    "新加坡", "馬來西亞", "台灣", "臺灣", "臺北", "新北市", "內地", "中國內地",
    "澳门", "澳門", "泰國", "越南", "印尼", "菲律賓", "日本", "韓國", "澳洲",
    "新西蘭", "紐西蘭", "印度", "國務院",
)
FOREIGN_ISSUER_EN = (
    "ministry of", "singapore", "malaysia", "taiwan", "mainland china",
    "macau", "macao", "thailand", "vietnam", "indonesia", "philippines",
    "japan", "korea", "australia", "new zealand", "india",
    "kementerian", "jabatan", "temasek", "mindef", "imda", "govtech",
)


def is_hk(rec: dict) -> bool:
    text = ((rec.get("title_zh") or "") + " " + (rec.get("title_en") or "") + " " + (rec.get("url") or "")).lower()
    if len(rec.get("url", "")) < 1: # Filter out the ones with no URL, as they are likely not valid tenders
        return  False
    for kw in FOREIGN_ZH:
        if kw in text:  # URL 冇空格就唔係外國招標
            return False
    for kw in FOREIGN_EN:
        if kw in text:
            return False
    return True


def is_gov(rec: dict) -> bool:
    tz = (rec.get("title_zh") or "").lower()
    te = (rec.get("title_en") or "").lower()
    if rec.get("issuer") in GOV_ZH or rec.get("issuer") in GOV_EN: # check issuer first (if available)
        return True 
    for kw in GOV_ZH:
        if kw in tz or kw in rec.get("issuer", ""):
            return True
    for kw in GOV_EN:
        if kw in te or kw in rec.get("issuer", ""):
            return True
    return False


def _is_foreign_issuer(text: str) -> bool:
    """issuer／全文 是否屬非港機構（關鍵字 substring）。"""
    t = (text or "").lower()
    for kw in FOREIGN_ISSUER_ZH:
        if kw in t:
            return True
    for kw in FOREIGN_ISSUER_EN:
        if kw in t:
            return True
    return False


def classify(rec: dict) -> dict:
    """回傳 {is_hk, is_gov, issuer_hint}。關鍵字先行。"""
    return {
        "is_hk": is_hk(rec),
        "is_gov": is_gov(rec),
        "issuer_hint": "",
    }


_detail_cache = TTLCache(ttl=300.0, maxsize=256)


def _read_detail(rec: dict, retries: int = 1, backoff: float = 1.5) -> str:
    """用 Jina Reader 讀招標詳情頁（markdown）。冇 key／失敗回傳 ""。

    空讀／異常會 retry（Jina 高併發時易 rate-limit 回空），重試後仍空先回 ""。
    成功結果用短 TTL cache，同 session 內重複呼叫唔使再打 Jina。
    """
    url = rec.get("url") or ""
    if not url or not config.JINA_API_KEY:
        return ""
    cached = _detail_cache.get(url)
    if cached is not None:
        logger.info("Jina _read_detail cache HIT (url=%s)", url)
        return cached
    logger.info("Jina _read_detail new fetch (url=%s)", url)
    last = ""
    for attempt in range(retries + 1):
        try:
            text = reader.read(url, config.JINA_API_KEY)
        except Exception:  # noqa: BLE001
            text = ""
        if text:
            _detail_cache.set(url, text)
            return text
        last = text
        if attempt < retries:
            time.sleep(backoff)
    return last


def _deep_issuer(rec: dict) -> str:
    """用 Jina Reader 抽取招標方（邊界案例先做，成本較高）。"""
    text = _read_detail(rec)
    if not text:
        return ""
    return (reader.extract(text).get("issuer") or "").strip()


def filter_non_gov(records: list[dict], deep_check: bool = False) -> list[dict]:
    """只保留香港 + 非政府嘅招標。"""
    out: list[dict] = []
    for rec in records:
        c = classify(rec)
        if not c["is_hk"] or c["is_gov"]:
            continue
        if deep_check:
            issuer = _deep_issuer(rec)
            if issuer and is_gov({"title_zh": issuer, "title_en": issuer, "url": ""}):
                continue
        out.append(rec)
    return out


_DEEP_WORKERS = 8


def _deep_keep(rec: dict) -> tuple[bool, str]:
    """深度檢查單項：讀詳情頁抽 issuer（冇 issuer 就全文），判斷係咪非港機構。

    回傳 (保留, issuer)。俾 filter_hk 用嚟並行跑。
    """
    text = _read_detail(rec)
    issuer = (reader.extract(text).get("issuer") or "").strip() if text else ""
    haystack = issuer or text  # issuer 優先，冇先掃全文
    keep = not (haystack and _is_foreign_issuer(haystack))
    if keep and issuer and is_gov({"title_zh": issuer, "title_en": issuer, "url": ""}):
        keep = False
    return keep, issuer


def filter_hk(records: list[dict], target: int = 10, max_checks: int = 40) -> list[dict]:
    """嚴格過濾：標題/slug 快篩後，並行 Jina 讀頁抽 issuer（冇 issuer 就全文），
    剔除非港機構，直到集齊 target 個（或檢查上限／列表耗盡）。

    以 `_DEEP_WORKERS` 為批大小並行深度檢查，保留原排序與 target/max_checks 語意。
    保留嘅記錄會附上 `issuer`（抽到先有，抽唔到就冇呢個 key）。
    """
    candidates = [r for r in records if is_hk(r) and not is_gov(r)][:max_checks]
    out: list[dict] = []
    with ThreadPoolExecutor(max_workers=_DEEP_WORKERS) as ex:
        for i in range(0, len(candidates), _DEEP_WORKERS):
            chunk = candidates[i : i + _DEEP_WORKERS]
            results = list(ex.map(_deep_keep, chunk))
            for rec, (keep, issuer) in zip(chunk, results):
                if keep:
                    if issuer:
                        rec["issuer"] = issuer
                    out.append(rec)
                    if len(out) >= target:
                        return out
    return out
