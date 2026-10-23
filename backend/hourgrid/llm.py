"""Optional natural-language layer on top of the trading agents, via Hugging Face.

- instruct(): turns "sell my surplus but never below Rs 4" into agent preferences (JSON)
- ask(): answers "why did you sell at 1 PM?" from the agent's own order/fill log

Uses the Hugging Face Inference Providers router (OpenAI-compatible) with HF_TOKEN.
Without a token, or if the call fails, a rule-based parser/template answers instead,
so the demo never depends on the network.
"""
from __future__ import annotations

import json
import logging
import re

import requests

from . import tariffs
from .config import settings

log = logging.getLogger("hourgrid.llm")

PREF_SCHEMA = """{
  "participate": bool,            // false = stop trading entirely
  "min_sell_price": number|null,  // currency/kWh floor when selling surplus; null = let agent decide
  "max_buy_price": number|null,   // currency/kWh cap when buying; null = let agent decide
  "sell_share": number,           // 0..1, share of forecast surplus to offer
  "prefer_green": bool,           // true = pay up to the grid price to get neighbour solar
  "aggressiveness": number        // 0..1, 0 = trade at fair middle price, 1 = hold out for best price
}"""


def _chat(messages: list[dict], max_tokens: int = 400, json_mode: bool = False) -> str:
    body = {"model": settings.hf_model, "messages": messages, "max_tokens": max_tokens, "temperature": 0.2}
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    r = requests.post(
        f"{settings.hf_base_url}/chat/completions",
        headers={"Authorization": f"Bearer {settings.hf_token}"}, json=body, timeout=30,
    )
    if r.status_code >= 400 and json_mode:  # some providers reject response_format
        body.pop("response_format")
        r = requests.post(f"{settings.hf_base_url}/chat/completions",
                          headers={"Authorization": f"Bearer {settings.hf_token}"}, json=body, timeout=30)
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]


def _extract_json(text: str) -> dict:
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise ValueError("no JSON in model output")
    return json.loads(m.group(0))


def _clean(prefs: dict, current: dict) -> dict:
    out = dict(current)
    for k in ("participate", "prefer_green"):
        if k in prefs and isinstance(prefs[k], bool):
            out[k] = prefs[k]
    for k in ("min_sell_price", "max_buy_price"):
        if k in prefs:
            v = prefs[k]
            out[k] = None if v in (None, "null", "") else round(min(max(float(v), 0.0), 20.0), 2)
    for k in ("sell_share", "aggressiveness"):
        if k in prefs and prefs[k] is not None:
            out[k] = round(min(max(float(prefs[k]), 0.0), 1.0), 2)
    return out


# ---------------------------------------------------------------- rule-based fallback
def _rules(text: str, current: dict) -> tuple[dict, str]:
    t = text.lower()
    p = dict(current)
    notes = []
    nums = [float(x) for x in re.findall(r"(?:rs\.?|₹|inr|tl|₺|try|€|eur|ct)?\s*(\d+(?:[.,]\d+)?)", t.replace(",", "."))]
    if re.search(r"\b(stop|pause|don'?t trade|opt out)\b", t):
        p["participate"] = False
        notes.append("paused trading")
    if re.search(r"\b(start|resume|enable)\b", t):
        p["participate"] = True
        notes.append("resumed trading")
    if re.search(r"(never|not|don'?t) .*below|at least|minimum|min\b", t) and nums:
        p["min_sell_price"] = nums[0]
        notes.append(f"won't sell below {tariffs.PROFILE.symbol}{nums[0]:.2f}/kWh")
    if re.search(r"(never|not|don'?t) .*(above|more than)|at most|maximum|max\b|budget", t) and nums:
        p["max_buy_price"] = nums[-1]
        notes.append(f"won't buy above {tariffs.PROFILE.symbol}{nums[-1]:.2f}/kWh")
    m = re.search(r"(\d{1,3})\s*%", t)
    if m and re.search(r"sell|offer|surplus", t):
        p["sell_share"] = min(1.0, int(m.group(1)) / 100)
        notes.append(f"offers {int(m.group(1))}% of surplus")
    if re.search(r"green|solar only|clean|neighbou?r", t) and re.search(r"buy|prefer|want|use", t):
        p["prefer_green"] = True
        notes.append("prefers neighbour solar")
    if re.search(r"cheap|save money|lowest", t):
        p["prefer_green"] = False
        p["aggressiveness"] = 0.7
        notes.append("hunts for the lowest price")
    if re.search(r"best price|maximi[sz]e|profit|earn more", t):
        p["aggressiveness"] = 0.9
        notes.append("holds out for higher sell prices")
    reply = ("Got it: " + ", ".join(notes) + ".") if notes else \
        "I couldn't map that to a setting. Try e.g. 'never sell below 4' or 'prefer neighbour solar'."
    return p, reply


# ---------------------------------------------------------------- public
def instruct(home: dict, text: str, current: dict) -> dict:
    if settings.hf_token:
        try:
            out = _chat([
                {"role": "system", "content":
                    f"You configure a rooftop-solar trading agent for a participant in {settings.site_name}, "
                    f"{tariffs.PROFILE.name}. Prices are in {tariffs.PROFILE.currency} per kWh. Retail tariff periods: "
                    + "; ".join(f"{p['label']} {p['start']:02d}-{p['end']:02d}h {p['price']:.2f}" for p in tariffs.as_dict()["periods"])
                    + f". The grid pays {tariffs.FEED_IN / tariffs.UNIT:.2f} for exported surplus. "
                    f"Return ONLY a JSON object: {{\"prefs\": <changes only>, \"reply\": <one friendly sentence>}}. "
                    f"Pref schema:\n{PREF_SCHEMA}"},
                {"role": "user", "content":
                    f"Home: {home['name']} ({home['role']}, {home['pv_kwp']} kWp solar, EV: {home['has_ev']}).\n"
                    f"Current prefs: {json.dumps(current)}\nInstruction: {text}"},
            ], json_mode=True)
            j = _extract_json(out)
            return {"prefs": _clean(j.get("prefs", {}), current), "reply": str(j.get("reply", ""))[:400],
                    "engine": f"huggingface:{settings.hf_model}"}
        except Exception as e:  # noqa: BLE001
            log.warning("HF instruct failed, falling back: %s", e)
    prefs, reply = _rules(text, current)
    return {"prefs": _clean(prefs, current), "reply": reply, "engine": "rules"}


def ask(home: dict, question: str, context: dict) -> dict:
    if settings.hf_token:
        try:
            out = _chat([
                {"role": "system", "content":
                    "You are the trading agent for a household in a peer-to-peer solar market. Answer the owner's "
                    "question in 2-4 short sentences, using only the log provided. Prices are per kWh in the local currency, energy in Wh. "
                    "Be concrete (times, prices, amounts)."},
                {"role": "user", "content": f"Home: {json.dumps(home)}\nLog: {json.dumps(context)[:6000]}\n"
                                            f"Question: {question}"},
            ])
            return {"answer": out.strip(), "engine": f"huggingface:{settings.hf_model}"}
        except Exception as e:  # noqa: BLE001
            log.warning("HF ask failed, falling back: %s", e)
    o = context.get("recent_orders", [])
    f = context.get("recent_fills", [])
    b = context.get("balance", {})
    lines = []
    if o:
        lines.append(f"Latest decision ({o[0]['time'][11:16]}): {o[0]['reason']}")
    if f:
        x = f[0]
        lines.append(f"Last trade: {'sold' if x['seller'] == home['home_id'] else 'bought'} {x['wh']} Wh at "
                     f"{tariffs.PROFILE.symbol}{x['price']:.2f}/kWh ({x['time'][11:16]}).")
    if b:
        lines.append(f"So far: sold {b.get('sold_wh', 0)} Wh, bought {b.get('bought_wh', 0)} Wh, "
                     f"{b.get('points', 0)} Green Hour points.")
    return {"answer": " ".join(lines) or "No trades yet for this home.", "engine": "template"}
