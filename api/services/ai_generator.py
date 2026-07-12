"""AI 策略生成器 — 支援 Gemini（雲端）與 Ollama（本機 GPU）兩種後端

環境變數：
  AI_PROVIDER      gemini | ollama（預設：有 GEMINI_API_KEY 就用 gemini，否則 ollama）
  GEMINI_API_KEY   Gemini API 金鑰
  GEMINI_MODEL     Gemini 模型（預設 gemini-2.5-flash）
  OLLAMA_BASE_URL  Ollama 服務位址（預設 http://localhost:11434）
  OLLAMA_MODEL     Ollama 模型（預設 qwen2.5:14b）
"""

from __future__ import annotations

import json
import os
import re
from typing import Optional

import requests

from stock_strategies import loader


SYSTEM_PROMPT = """你是台股量化選股策略設計師。使用者會用自然語言描述他想要的選股風格，
你的工作是把它翻成一份**符合 schema 的策略 JSON**。

## 嚴格規則
- 你只能回覆一份 JSON，不要 markdown code fence、不要說明文字、不要前後綴
- 必須包含 `name`、`description`、`params` 三個頂層欄位
- `params` 內所有鍵都必須來自下方白名單；型別必須正確
- weight_fundamental + weight_technical + weight_backtest 加總應 ≈ 1
- target_return 與 stop_loss 都是小數（例如 0.10 表示 10%）

## params 白名單與型別
{
  "eps_threshold": float,            // 最近年度 EPS 最小值需 > 此數，台股常見 2~10
  "roe_threshold": float,            // 最近年度 ROE 最小值需 > 此數 (%)，常見 8~25
  "fundamental_pass_required": bool, // 是否強制基本面要過才能 BUY
  "backtest_years": int,             // 1~10
  "hold_days": int,                  // 1~120
  "min_tech_score_for_signal": int,  // 0~100，回測時技術分達多少算訊號
  "target_return": float,            // 0.01~0.5
  "stop_loss": float,                // 0.01~0.5
  "weight_fundamental": float,
  "weight_technical": float,
  "weight_backtest": float,
  "min_total_score_for_buy": int,    // 0~100
  "min_tech_score_for_buy": int,     // 0~100
  "use_ma_alignment": bool,
  "use_bollinger_bounce": bool,
  "use_kd_golden_cross": bool,
  "use_macd_bullish": bool,
  "use_volume_patterns": bool,
  "market_filter_enabled": bool,
  "market_filter_ma_period": int     // 5~120
}

## 設計指引
- 偏短線 / 動能 → backtest_years 2-3、hold_days 5-10、target +5~8%、stop -3~5%、技術權重高
- 偏存股 / 價值 → EPS/ROE 門檻提高、backtest_years 5、hold_days 60+、基本面權重高
- 偏保守 → 基本面強制要過、min_total_score 75+、停損縮緊到 -3~5%
- 偏激進 / 抓飆股 → 量價型態打開、技術權重 0.5+、target 拉到 +15~20%
"""


def _extract_json(text: str) -> dict:
    """從模型回覆抽出第一個 JSON 物件"""
    text = re.sub(r"^```(?:json)?\s*", "", text.strip())
    text = re.sub(r"\s*```$", "", text.strip())
    s, e = text.find("{"), text.rfind("}")
    if s == -1 or e == -1 or e <= s:
        raise ValueError(f"模型回覆找不到 JSON: {text[:200]}")
    return json.loads(text[s : e + 1])


def _active_provider() -> str:
    explicit = os.environ.get("AI_PROVIDER", "").lower()
    if explicit in ("gemini", "ollama"):
        return explicit
    return "gemini" if os.environ.get("GEMINI_API_KEY") else "ollama"


def _call_gemini(full_prompt: str) -> str:
    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        raise RuntimeError("未設定 GEMINI_API_KEY 環境變數")
    try:
        import google.generativeai as genai
    except ImportError as e:
        raise RuntimeError("缺少 google-generativeai 套件，請 `uv add google-generativeai`") from e

    genai.configure(api_key=api_key)
    model_name = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
    model = genai.GenerativeModel(
        model_name,
        system_instruction=SYSTEM_PROMPT,
        generation_config={"temperature": 0.4, "response_mime_type": "application/json"},
    )
    resp = model.generate_content(full_prompt)
    return getattr(resp, "text", None) or ""


def _call_ollama(full_prompt: str) -> str:
    base_url = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
    model = os.environ.get("OLLAMA_MODEL", "qwen2.5:14b")
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": full_prompt},
        ],
        "stream": False,
        "options": {"temperature": 0.4},
    }
    resp = requests.post(f"{base_url}/v1/chat/completions", json=payload, timeout=120)
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


def generate_strategy_with_ai(user_prompt: str, name: Optional[str] = None) -> dict:
    """把使用者自然語言描述轉為策略 JSON，驗證後回傳乾淨版本。

    不寫檔；前端拿到後讓使用者預覽，按「儲存」才打 POST /api/strategies。
    """
    provider = _active_provider()

    full_prompt = (
        f"使用者描述：\n{user_prompt}\n\n"
        "請輸出一份符合 schema 的策略 JSON。"
    )
    if name:
        full_prompt += f" 策略名稱請使用：「{name}」。"

    if provider == "gemini":
        text = _call_gemini(full_prompt)
    else:
        text = _call_ollama(full_prompt)

    data = _extract_json(text)
    data["source"] = "ai"
    if name and not data.get("name"):
        data["name"] = name

    return loader.validate_strategy(data)
