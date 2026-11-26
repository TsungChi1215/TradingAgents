"""Gemini 圖片理解／文字模型防護。僅加固既有程式的選模、請求與診斷。"""
from __future__ import annotations

import copy
import hashlib
import json
import logging
import re
import threading
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

VERSION = "圖片OCR裁切單模型防護-20261126-v3"
_LOCK = threading.RLock()
_COOLDOWN = {}
_LOG = logging.getLogger("radar.ai_model_guard")
_FORBIDDEN = ("image", "imagen", "nano-banana", "audio", "tts", "embedding", "live", "robot", "computer-use", "deep-research", "research")


class ModelGuardError(RuntimeError):
    code = "本機防護"


class ModelQuotaZero(ModelGuardError):
    code = 429
    guard_logged = True


class ModelCoolingDown(ModelGuardError):
    code = "暫停重試"
    guard_logged = True


def _setting(ns, name, default=None):
    import os
    value = os.environ.get(name, default)
    try:
        value = ns["st"].secrets.get(name, value)
    except Exception:
        pass
    return value


def _keys(ns):
    try:
        return [str(k) for k in ns["get_gemini_api_keys"]() if k]
    except Exception:
        return []


def _redact(value, ns):
    text = str(value)
    for key in _keys(ns):
        text = text.replace(key, "[金鑰已隱藏]")
    text = re.sub(r"(?i)([?&](?:key|api_key|token|access_token)=)[^&\s]+", r"\1[已隱藏]", text)
    text = re.sub(r"(?i)(bearer\s+)[A-Za-z0-9._~+/-]+", r"\1[已隱藏]", text)
    text = re.sub(r"AIza[A-Za-z0-9_-]{20,}", "[金鑰已隱藏]", text)
    return text[:1800]


def _state(ns):
    try:
        return ns["st"].session_state
    except Exception:
        return {}


def _emit(ns, stage, context=None, **details):
    event = {"時間": datetime.now(ZoneInfo("Asia/Taipei")).isoformat(timespec="seconds"), "階段": stage, **(context or {}), **details}
    def sanitize(value):
        if isinstance(value, (str, Exception)):
            return _redact(value, ns)
        if isinstance(value, dict):
            return {str(k): sanitize(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [sanitize(v) for v in value]
        return value
    event = sanitize(event)
    event.setdefault("摘要", event.get("中文說明", event.get("原因", event.get("說明", ""))))
    state = _state(ns)
    events = state.setdefault("peer_analysis_diagnostics_v2", [])
    events.append(event)
    if len(events) > 80:
        del events[:-80]
    _LOG.warning("AI模型防護 %s", json.dumps(event, ensure_ascii=False, default=str))
    return event


def _name(model):
    return str(model or "").removeprefix("models/").strip()


def _model_allowed(name, metadata=None):
    n = _name(name).lower()
    if not n.startswith("gemini-"):
        return False
    if any(part in n for part in _FORBIDDEN):
        return False
    # Limit automatic selection to general Flash/Pro text model families.
    if not re.search(r"(?:^|-)(?:flash|pro)(?:-|$)", n):
        return False
    if metadata is not None:
        outputs = getattr(metadata, "supported_output_modalities", None)
        inputs = getattr(metadata, "supported_input_modalities", None)
        if outputs:
            values = {str(v).upper().rsplit(".", 1)[-1] for v in outputs}
            if "TEXT" not in values or "IMAGE" in values or "AUDIO" in values:
                return False
        if inputs:
            values = {str(v).upper().rsplit(".", 1)[-1] for v in inputs}
            if "IMAGE" not in values:
                return False
    return True


def _code(error):
    value = getattr(error, "code", getattr(error, "status_code", None))
    try:
        return int(value)
    except (ValueError, TypeError):
        match = re.search(r"\b(400|401|403|404|408|429|500|502|503|504)\b", str(error))
        return int(match.group(1)) if match else None


def classify_error(error):
    text = str(error).lower()
    code = _code(error)
    if isinstance(error, ModelQuotaZero):
        return "MODEL_QUOTA_ZERO"
    # 'remaining: 0' is NOT the same as a configured quota limit of zero.
    zero_limit = bool(re.search(r"[\"']?(?:limit|quota_limit_value)[\"']?\s*[:=]\s*[\"']?0(?:\.0)?(?![\d.])", text))
    if (code == 429 or "resource_exhausted" in text) and zero_limit:
        return "MODEL_QUOTA_ZERO"
    if code == 429 or "resource_exhausted" in text:
        if any(word in text for word in ("requestsperday", "requests_per_day", "per_day", "per day", "daily", "每日")):
            return "DAILY_QUOTA"
        return "RATE_LIMIT"
    if code in (401, 403):
        return "ACCESS_ERROR"
    if code == 404 or "not_found" in text:
        return "NOT_FOUND"
    if code in (500, 502, 503, 504):
        return "SERVICE_ERROR"
    return "OTHER_ERROR"


def _message(kind):
    return {
        "MODEL_QUOTA_ZERO": "此專案／模型的回應顯示配額上限為0；不代表所有模型或所有金鑰的額度耗盡。",
        "DAILY_QUOTA": "此專案／模型的每日限制已觸發；不是帳戶全部模型的總額度判定。",
        "RATE_LIMIT": "此專案／模型觸發速率或未明確分類的配額限制；已停止本次密集重試。",
        "ACCESS_ERROR": "金鑰、服務端點或專案權限不允許此次操作；未改用其他金鑰繞過。",
        "NOT_FOUND": "此次端點找不到要求的模型／資源；需核對實際模型與API。",
        "SERVICE_ERROR": "上游服務暫時失敗；不代表配額耗盡。",
        "OTHER_ERROR": "此次成交表格OCR未完成，請查看辨識模式與去識別化錯誤摘要；尚未進入解盤階段。",
    }[kind]


def _identity(ns, api_key, mode):
    fingerprint = hashlib.sha256(str(api_key).encode()).hexdigest()[:12] if api_key else "未提供API金鑰"
    keys = _keys(ns)
    index = keys.index(api_key) + 1 if api_key in keys else None
    labels = _setting(ns, "AI_KEY_PROJECT_LABELS", [])
    if isinstance(labels, str):
        labels = [x.strip() for x in labels.split(",")]
    label = str(labels[index - 1]).strip() if index and isinstance(labels, (list, tuple)) and index <= len(labels) else ""
    # A configured label is not an API-verified project ID.
    return {
        "金鑰序號": index or "未對應到設定清單",
        "金鑰指紋": fingerprint,
        "專案標籤（人工設定）": label or "未設定；不由金鑰猜測專案",
        "連線模式": mode,
        "專案對應已驗證": False,
    }


def _scope(context):
    label = context.get("專案標籤（人工設定）", "")
    identity = "label:" + label if label and not label.startswith("未設定") else "key:" + str(context.get("金鑰指紋"))
    return context.get("連線模式"), identity


def _blocked(context, model):
    token = (*_scope(context), _name(model))
    with _LOCK:
        item = _COOLDOWN.get(token)
        if item and item[0] > time.time():
            return item
        _COOLDOWN.pop(token, None)
    return None


def _pause(context, model, kind):
    seconds = {"MODEL_QUOTA_ZERO": 3600, "RATE_LIMIT": 90, "NOT_FOUND": 3600, "SERVICE_ERROR": 30, "ACCESS_ERROR": 300}.get(kind, 60)
    if kind == "DAILY_QUOTA":
        now = datetime.now(ZoneInfo("America/Los_Angeles"))
        midnight = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        seconds = max(60, midnight.timestamp() - time.time())
    token = (*_scope(context), _name(model))
    with _LOCK:
        if len(_COOLDOWN) > 512:
            expired = [k for k, v in _COOLDOWN.items() if v[0] <= time.time()]
            for k in expired:
                _COOLDOWN.pop(k, None)
            if len(_COOLDOWN) > 512:
                _COOLDOWN.pop(next(iter(_COOLDOWN)))
        _COOLDOWN[token] = (time.time() + seconds, kind)
    return seconds


def _rank(name):
    n = name.lower()
    version = re.search(r"gemini-(\d+)(?:\.(\d+))?", n)
    version = tuple(map(int, (version.group(1), version.group(2) or "0"))) if version else (0, 0)
    return ("preview" in n or "experimental" in n or "-exp" in n, "flash" not in n, "lite" in n, -version[0], -version[1], n)


def select_models(client, ns):
    context = getattr(client, "guard_context", {})
    _state(ns)["ai_guard_current_context"] = context
    try:
        discovered = {}
        rejected = []
        for model in client.models.list():
            name = _name(getattr(model, "name", ""))
            actions = {str(a).lower().replace("_", "") for a in (getattr(model, "supported_actions", None) or [])}
            if "generatecontent" not in actions or not _model_allowed(name, model):
                rejected.append(name)
                continue
            discovered[name] = model
    except Exception as error:
        _emit(ns, "模型清單查詢失敗", context, 狀態碼=_code(error), 錯誤分類=classify_error(error), 摘要=_redact(error, ns), 處理="未盲試預設舊模型；降級為本機")
        return []
    configured = _setting(ns, "AI_TEXT_VISION_MODELS", None)
    if not configured:
        configured = _setting(ns, "PEER_GEMINI_MODEL", "")
    if isinstance(configured, str):
        configured = [v.strip() for v in configured.split(",") if v.strip()]
    if configured and not isinstance(configured, (list, tuple)):
        _emit(ns, "模型設定格式不符", context, 處理="模型設定須為名稱字串或名稱清單；未送出生成請求")
        return []
    order = [_name(v) for v in configured] if configured else sorted(discovered, key=_rank)
    selected = []
    for name in order:
        if name not in discovered:
            _emit(ns, "排除模型", context, 模型=name, 原因="不在此次端點列出的合適文字模型候選中；未送出生成請求")
            continue
        cooling = _blocked(context, name)
        if cooling:
            _emit(ns, "跳過暫停模型", context, 模型=name, 錯誤分類=cooling[1], 剩餘秒數=max(0, int(cooling[0] - time.time())))
            continue
        if name not in selected:
            selected.append(name)
        if len(selected) == 1:
            break
    _emit(ns, "完成模型篩選", context, 候選模型=selected, 排除的圖片或非本任務模型數=len(rejected), 配額已驗證=False, 說明="列出模型不代表有可用配額；未由用量圖推測剩餘額度")
    return selected


class _GuardModels:
    def __init__(self, base, ns, context):
        self._base, self._ns, self._context = base, ns, context

    def __getattr__(self, name):
        return getattr(self._base, name)

    def generate_content(self, *args, **kwargs):
        ns, context = self._ns, self._context
        model = _name(kwargs.get("model", ""))
        _state(ns)["ai_guard_current_context"] = context
        if not _model_allowed(model):
            _emit(ns, "生成請求已攔截", context, 模型=model, 原因="圖片生成／語音／嵌入或非一般文字模型，不適用此辨識流程")
            raise ModelGuardError("模型不適用此圖片理解與文字覆盤流程，未向Google送出生成請求")
        cooling = _blocked(context, model)
        if cooling:
            _emit(ns, "生成請求暫停", context, 模型=model, 錯誤分類=cooling[1], 剩餘秒數=max(0, int(cooling[0] - time.time())))
            raise ModelCoolingDown("此模型仍在本機冷卻期，未再次送出；可檢查其他已列出的候選模型")
        # Enforce text output. Do not ask an image-generation model to produce JSON.
        config = kwargs.get("config")
        if config is None:
            kwargs["config"] = {"response_modalities": ["TEXT"]}
        elif isinstance(config, dict):
            kwargs["config"] = {**config, "response_modalities": ["TEXT"]}
        elif hasattr(config, "model_copy"):
            kwargs["config"] = config.model_copy(update={"response_modalities": ["TEXT"]})
        else:
            cloned = copy.copy(config)
            try:
                cloned.response_modalities = ["TEXT"]
                kwargs["config"] = cloned
            except Exception:
                pass
        _emit(ns, "送出生成請求", context, 模型=model, 說明="使用此候選嘗試；不保證配額可用")
        started = time.monotonic()
        try:
            result = self._base.generate_content(*args, **kwargs)
        except Exception as error:
            kind = classify_error(error)
            wait = _pause(context, model, kind)
            _emit(ns, "生成請求失敗", context, 模型=model, 狀態碼=_code(error), 錯誤分類=kind, 中文說明=_message(kind), 本機暫停秒數=int(wait), 摘要=_redact(error, ns))
            if kind == "MODEL_QUOTA_ZERO":
                # Domain exception preserves HTTP status while permitting the existing v2 loop
                # to try its next listed model. It never rotates API keys internally.
                raise ModelQuotaZero("此模型配額上限為零，已暫停重送；不代表其他模型額度用完，可嘗試下一個已列出的合適模型") from None
            raise
        _emit(ns, "生成請求成功", context, 模型=model, 狀態碼=200, 耗時秒數=round(time.monotonic() - started, 2))
        return result


class _GuardClient:
    def __init__(self, base, ns, context):
        self._base = base
        self.guard_context = context
        self.models = _GuardModels(base.models, ns, context)

    def __getattr__(self, name):
        return getattr(self._base, name)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        if hasattr(self._base, "close"):
            self._base.close()


class _GuardSDK:
    def __init__(self, base, ns):
        self._base = base
        self._ns = ns

    def __getattr__(self, name):
        return getattr(self._base, name)

    def Client(self, *args, **kwargs):
        mode = "vertex" if kwargs.get("vertexai") else "gemini"
        context = _identity(self._ns, str(kwargs.get("api_key", "")), mode)
        _state(self._ns)["ai_guard_current_context"] = context
        try:
            base = self._base.Client(*args, **kwargs)
        except Exception as error:
            _emit(self._ns, "客戶端初始化失敗", context, 狀態碼=_code(error), 摘要=_redact(error, self._ns))
            raise
        return _GuardClient(base, self._ns, context)


def install_ai_model_guard(namespace):
    """Call after the v2 functions are defined, before `with tab_review:`."""
    if "_peer_v2_models" not in namespace or "_peer_v2_log" not in namespace:
        raise RuntimeError("此局部更新需要目前的『逐筆核對／證據式覆盤第二版』；未自動退回或覆蓋舊程式")
    sdk = namespace.get("genai")
    if sdk is not None:
        while isinstance(sdk, _GuardSDK):
            sdk = sdk._base
        namespace["genai"] = _GuardSDK(sdk, namespace)
    namespace["_peer_v2_models"] = lambda client, keys: select_models(client, namespace)
    if "_get_candidate_models" in namespace:
        namespace["_get_candidate_models"] = lambda client: select_models(client, namespace)
    def peer_log(stage, model, mode, error, keys=()):
        context = dict(_state(namespace).get("ai_guard_current_context", {}))
        if getattr(error, "guard_logged", False):
            events = _state(namespace).get("peer_analysis_diagnostics_v2", [])
            if events:
                return events[-1]
        kind = classify_error(error)
        return _emit(namespace, stage, context, 模型=_name(model), 連線模式=mode, 狀態碼=_code(error), 錯誤分類=kind, 摘要=_redact(error, namespace), 中文說明=_message(kind))
    namespace["_peer_v2_log"] = peer_log
    old_friendly = namespace.get("_friendly_ai_error")
    if getattr(old_friendly, "_ai_guard_wrapper", False):
        old_friendly = getattr(old_friendly, "_ai_guard_original", None)
    def friendly(errors):
        text = " | ".join(str(e) for e in errors)
        if "配額上限為零" in text or "配額上限為0" in text:
            return _message("MODEL_QUOTA_ZERO")
        kind = classify_error(RuntimeError(text))
        if kind != "OTHER_ERROR":
            return _message(kind)
        return old_friendly(errors) if old_friendly else _message(kind)
    friendly._ai_guard_wrapper = True
    friendly._ai_guard_original = old_friendly
    namespace["_friendly_ai_error"] = friendly
    namespace["AI_MODEL_GUARD_VERSION"] = VERSION
    return VERSION
