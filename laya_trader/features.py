"""Laya 입력 피처: 전략 틱봉(ST/JMA) + 호가 + MarketEye 종목간 비교.
규칙: idx 봉까지의 데이터만 사용(미래 참조 금지) -> 장중 판단과 장후 재현이 같은 값."""
import math

SCHEMA = "st_entry_v1"


def hm2min(t):
    t = int(t)
    return (t // 100) * 60 + t % 100


def _r(x, n=4):
    return None if x is None or not math.isfinite(x) else round(x, n)


def _pct(a, b):
    return (a / b - 1) * 100 if b else None


def _f(x, spec, suffix=""):
    return "n/a" if x is None else format(x, spec) + suffix


def day_refs(bars, idx):
    """당일 첫 index, 정규장 시가, 전일 KRX 종가, 당일(정규장) 고저 - idx까지"""
    d = bars[idx]["date"]
    i0 = idx
    while i0 > 0 and bars[i0 - 1]["date"] == d:
        i0 -= 1
    today = bars[i0:idx + 1]
    reg = [b for b in today if b["session"] in ("reg", "close")]
    base = reg or today
    prev_close = None
    for j in range(i0 - 1, -1, -1):
        if bars[j]["session"] in ("reg", "close"):
            prev_close = bars[j]["c"]
            break
    return i0, base[0]["o"], prev_close, max(b["h"] for b in base), min(b["l"] for b in base)


def bar_features(bars, ind, idx):
    b = bars[idx]
    st, jm = ind["st"][idx], ind["jma"][idx]
    if st is None or jm is None:
        raise ValueError("지표 계산 구간 밖(day_ok=False 또는 워밍업 부족)")
    start = ind["start"]
    i0, day_open, prev_close, hi, lo = day_refs(bars, idx)
    c, atr = b["c"], st["atr"]
    since, k = 0, idx
    while k > start and ind["st"][k] and ind["st"][k]["turn"] == 0:
        k -= 1
        since += 1
    ups = sum(1 for k in range(max(i0, start), idx + 1)
              if ind["st"][k] and ind["st"][k]["turn"] == 1 and bars[k]["session"] == "reg")

    def ret(n):
        return _pct(c, bars[idx - n]["c"]) if idx - n >= start else None
    vols = [x["v"] for x in bars[max(start, idx - 20):idx]]
    vavg = sum(vols) / len(vols) if vols else 0
    return {
        "date": b["date"], "seq": b["seq"], "t": b["t"], "session": b["session"], "close": c,
        "min_from_open": hm2min(b["t"]) - 540,
        "st_up": st["up"], "st_turn": st["turn"], "bars_since_turn": since, "ups_today": ups,
        "dist_st_atr": (c - st["v"]) / atr if atr else None,
        "atr_pct": atr / c * 100 if c else None,
        "jma_dir": jm["dir"], "jma_slope": jm["slope"], "jma_gap_pct": _pct(c, jm["v"]),
        "jma_bp3": (jm["v"] / ind["jma"][idx - 3]["v"] - 1) * 10000 if idx - 3 >= start and ind["jma"][idx - 3] else None,
        "chg_open_pct": _pct(c, day_open), "chg_prev_pct": _pct(c, prev_close),
        "day_pos": min(1.0, max(0.0, (c - lo) / (hi - lo))) if hi > lo else 0.5,
        "r1": ret(1), "r3": ret(3), "r10": ret(10),
        "vol_ratio": b["v"] / vavg if vavg else None,
        "span5_min": hm2min(b["t"]) - hm2min(bars[idx - 5]["t"]) if idx - 5 >= i0 else None,
        "body_pct": _pct(c, b["o"]),
        "upper_wick_pct": (b["h"] - max(b["o"], c)) / c * 100 if c else None,
    }


def orderbook_features(ob):
    if not ob or not ob.get("asks"):
        return {}
    a, bd = ob["asks"], ob["bids"]
    a1, b1 = a[0]["price"], bd[0]["price"]
    qa5, qb5 = sum(x["qty"] for x in a[:5]), sum(x["qty"] for x in bd[:5])
    ta_, tb = ob.get("total_ask") or 0, ob.get("total_bid") or 0
    mid = (a1 + b1) / 2 if a1 and b1 else None
    return {"ob_time": ob.get("time"), "spread_pct": (a1 - b1) / mid * 100 if mid else None,
            "imb5": (qb5 - qa5) / (qb5 + qa5) if qb5 + qa5 else None,
            "imb_total": (tb - ta_) / (tb + ta_) if tb + ta_ else None,
            "ask1_qty": a[0]["qty"], "bid1_qty": bd[0]["qty"]}


def peer_features(code, rows):
    rows = [r for r in rows or [] if r.get("price")]
    me = next((r for r in rows if r["code"] == code), None)
    if not me or len(rows) < 2:
        return {"peer_n": len(rows)}

    def pctile(key):
        v = me.get(key) or 0
        return sum(1 for r in rows if (r.get(key) or 0) < v) / (len(rows) - 1)
    rates = sorted(r.get("rate") or 0 for r in rows)
    return {"peer_n": len(rows), "rate": me.get("rate"), "rate_pctile": pctile("rate"),
            "value_pctile": pctile("value"), "peer_rate_median": rates[len(rates) // 2]}


def to_state(code, name, kind, period, f):
    """Laya 입력(짧은 영어 문장). 1024토큰 한도(질문 포함) 안에 들어가도록 압축"""
    tf = f"{period}-tick" if kind == "T" else f"{period}-minute"
    if f["st_turn"] == 1:
        sig = f"SuperTrend just turned UP on {tf} bar"
    elif f["st_turn"] == -1:
        sig = f"SuperTrend just turned DOWN on {tf} bar"
    else:
        sig = "SuperTrend {} on {} bar for {} bars".format("UP" if f["st_up"] else "DOWN", tf, f["bars_since_turn"])
    t = f["t"]
    s = {
        "symbol": (code + " " + (name or "")).strip(),
        "signal": sig + ", regular-session up-turns today {}".format(f["ups_today"]),
        "time": "{:02d}:{:02d}, {} min after 09:00, session {}".format(t // 100, t % 100, f["min_from_open"], f["session"]),
        "price": "vs open {}, vs prev close {}, day range position {}".format(
            _f(f["chg_open_pct"], "+.2f", "%"), _f(f["chg_prev_pct"], "+.2f", "%"), _f(f["day_pos"], ".0%")),
        "trend": "close {} ATR from SuperTrend, ATR {}, JMA {} 3-bar {}, close {} vs JMA".format(
            _f(f["dist_st_atr"], "+.2f"), _f(f["atr_pct"], ".2f", "%"),
            "rising" if f["jma_dir"] > 0 else "falling", _f(f["jma_bp3"], "+.1f", "bp"), _f(f["jma_gap_pct"], "+.2f", "%")),
        "momentum": "returns 1/3/10 bars {}/{}/{}, volume x{} of 20-bar avg, last 5 bars took {} min".format(
            _f(f["r1"], "+.2f", "%"), _f(f["r3"], "+.2f", "%"), _f(f["r10"], "+.2f", "%"),
            _f(f["vol_ratio"], ".1f"), _f(f["span5_min"], "d")),
    }
    if f.get("imb5") is not None:
        s["orderbook"] = "bid-ask imbalance top5 {}, total {}, spread {}".format(
            _f(f["imb5"], "+.2f"), _f(f.get("imb_total"), "+.2f"), _f(f.get("spread_pct"), ".3f", "%"))
    if f.get("rate_pctile") is not None:
        s["peers"] = "change {} ranks above {} of {} watched stocks, trade value above {}, peer median {}".format(
            _f(f["rate"], "+.2f", "%"), _f(f["rate_pctile"], ".0%"), f["peer_n"],
            _f(f["value_pctile"], ".0%"), _f(f["peer_rate_median"], "+.2f", "%"))
    return s


def window(bars, ind, idx, n=40):
    """재현용: 판단 시점까지 최근 n봉 [date, seq, t, o, h, l, c, v, st, st_up, jma]"""
    out = []
    for k in range(max(0, idx - n + 1), idx + 1):
        b, s, j = bars[k], ind["st"][k], ind["jma"][k]
        out.append([b["date"], b["seq"], b["t"], b["o"], b["h"], b["l"], b["c"], b["v"],
                    s and round(s["v"], 2), s and s["up"], j and j["v"]])
    return out


def build(code, name, kind, period, bars, ind, idx, ob=None, peers=None, win=40):
    f = bar_features(bars, ind, idx)
    f.update(orderbook_features(ob))
    f.update(peer_features(code, peers))
    return {"schema": SCHEMA, "code": code, "kind": kind, "period": period, "params": ind["params"],
            "f": {k: (_r(v) if isinstance(v, float) else v) for k, v in f.items()},
            "state": to_state(code, name, kind, period, f),
            "window": window(bars, ind, idx, win)}


def outcome(bars, ind, idx):
    """기준 평가: 상승전환 봉 종가 진입 -> 다음 ST 하락전환 봉 종가 청산. 당일 전환 없으면 당일 마지막 봉"""
    d, entry = bars[idx]["date"], bars[idx]["c"]
    hi = lo = entry
    k, reason = idx, "day_end"
    for j in range(idx + 1, len(bars)):
        if bars[j]["date"] != d:
            break
        k = j
        hi, lo = max(hi, bars[j]["h"]), min(lo, bars[j]["l"])
        s = ind["st"][j]
        if s and s["turn"] == -1:
            reason = "st_down"
            break
    if reason == "day_end" and bars[k].get("live"):
        reason = "open"
    return {"exit_idx": k, "exit_t": bars[k]["t"], "reason": reason, "bars": k - idx,
            "ret_pct": _r(_pct(bars[k]["c"], entry), 3),
            "mfe_pct": _r(_pct(hi, entry), 3), "mae_pct": _r(_pct(lo, entry), 3)}
