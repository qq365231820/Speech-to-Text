import copy
import json
import os
from pathlib import Path
from urllib.parse import urlparse

PROVIDERS = {
    "讯飞": dict(asr_url="wss://iat.cn-huabei-1.xf-yun.com/v1", asr_model="slm",
                 text_url="https://spark-api-open.xf-yun.com/v1/chat/completions", text_model="lite"),
    "阿里云": dict(asr_url="wss://dashscope.aliyuncs.com/api-ws/v1/inference", asr_model="fun-asr-realtime",
                  text_url="https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions", text_model="qwen-turbo"),
    "腾讯云": dict(asr_url="wss://asr.cloud.tencent.com/asr/v2", asr_model="16k_zh_large",
                  text_url="https://api.hunyuan.cloud.tencent.com/v1/chat/completions", text_model="hunyuan-lite"),
    "火山引擎": dict(asr_url="https://openspeech.bytedance.com/api/v3/auc/bigmodel/recognize/flash", asr_model="bigmodel",
                    text_url="https://ark.cn-beijing.volces.com/api/v3/chat/completions", text_model=""),
    "自定义": dict(asr_url="", asr_model="", text_url="", text_model=""),
}
SECRET_FIELDS = ("api_key", "api_secret", "text_key")

def defaults():
    profiles = copy.deepcopy(PROVIDERS)
    for profile in profiles.values():
        profile.update(app_id="", api_key="", api_secret="", text_key="")
    return dict(provider="阿里云", offline=False, hotkey="f8", trigger="hold", output="sentence",
                silence_ms=800, threshold=350, max_segment_s=15, max_record_s=300,
                idle_seconds=60, microphone="", offline_asr="", offline_llm="",
                offline_device="cpu", profiles=profiles)

def endpoint(url, websocket=False):
    parsed = urlparse(url)
    allowed = ("wss",) if websocket else ("https",)
    if parsed.scheme not in allowed or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
        raise ValueError("接口必须使用安全的 HTTPS/WSS 地址，不能包含账号密码或片段")
    return url

def validate(cfg):
    from .hotkeys import parse_hotkey
    parse_hotkey(cfg["hotkey"])
    if cfg["provider"] not in PROVIDERS or cfg["trigger"] not in ("hold", "toggle") or cfg["output"] not in ("sentence", "final"):
        raise ValueError("模式配置无效")
    for name, lo, hi in (("silence_ms", 300, 3000), ("threshold", 50, 5000),
                         ("max_segment_s", 3, 25), ("max_record_s", 10, 600), ("idle_seconds", 5, 600)):
        if not lo <= int(cfg[name]) <= hi:
            raise ValueError(f"{name} 必须在 {lo}–{hi} 之间")
    if cfg["offline_device"] not in ("cpu", "cuda"):
        raise ValueError("离线设备应为 cpu 或 cuda")

def ready(cfg):
    validate(cfg)
    if cfg["offline"]:
        if not Path(cfg["offline_asr"]).is_dir() or not cfg["offline_asr"]:
            raise ValueError("请先配置已下载的本地识别模型目录")
        return
    name = cfg["provider"]
    p = cfg["profiles"][name]
    endpoint(p["asr_url"], name in ("讯飞", "阿里云", "腾讯云"))
    if not p["api_key"]:
        raise ValueError("请先填写语音识别 API 密钥")
    if name in ("讯飞", "腾讯云") and (not p["api_secret"] or not p["app_id"]):
        raise ValueError("该供应商还需要 App ID 和 API Secret / SecretKey")

class ConfigStore:
    def __init__(self, path=None):
        self.path = Path(path) if path else Path(os.getenv("LOCALAPPDATA", ".")) / "LuoyangVoice" / "settings.json"

    def load(self):
        cfg = defaults()
        if not self.path.exists():
            return cfg
        from .win32 import unprotect
        data = json.loads(self.path.read_text(encoding="utf-8"))
        profiles = data.pop("profiles", {})
        cfg.update(data)
        for name, profile in profiles.items():
            if name not in cfg["profiles"]:
                continue
            for field in SECRET_FIELDS:
                if profile.get(field):
                    profile[field] = unprotect(profile[field])
            cfg["profiles"][name].update(profile)
        validate(cfg)
        return cfg

    def save(self, cfg):
        from .win32 import protect
        validate(cfg)
        data = copy.deepcopy(cfg)
        for profile in data["profiles"].values():
            for field in SECRET_FIELDS:
                if profile.get(field):
                    profile[field] = protect(profile[field])
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, self.path)
