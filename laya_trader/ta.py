"""kiwoom-desk addons/chart-indicators/plugins/{supertrend,jma}.ts 1:1 포팅.
서버 계산이 원본(Laya state / 스냅샷 / 백테스트 공통). 차트는 그리기만 한다.
JS 동작 일치: Math.round(0.5 -> +inf), 순차 합산(파이썬 sum 보정합 사용 안 함), C# ToEven 반올림."""
import math

EPS = 2.220446049250313e-16          # Number.EPSILON
ST_UP, ST_DOWN = "#e34a4a", "#3f7fd6"
JMA_UP, JMA_DOWN = "#AB47BC", "#00C853"


def _js_round(x):
    return math.floor(x + 0.5)


def round_even(value, digits):
    if not math.isfinite(value):
        return value
    factor = 10 ** digits
    scaled = value * factor
    fl = math.floor(scaled)
    frac = scaled - fl
    eps = EPS * max(1.0, abs(scaled)) * 4
    if abs(frac - 0.5) <= eps:
        r = fl if fl % 2 == 0 else fl + 1
    else:
        r = _js_round(scaled)
    return r / factor


def _tr(bars, i):
    b = bars[i]
    if i == 0:
        return b["h"] - b["l"]
    pc = bars[i - 1]["c"]
    return max(b["h"] - b["l"], abs(b["h"] - pc), abs(b["l"] - pc))


def supertrend(bars, period=14, mult=2.0):
    period = max(1, int(period))
    mult = max(0.01, float(mult))
    out = [None] * len(bars)
    prev = None
    for i in range(period - 1, len(bars)):
        b = bars[i]
        hl2 = (b["h"] + b["l"]) / 2
        if i == period - 1:
            s = 0
            for k in range(period):
                s += _tr(bars, k)
            atr = s / period
        else:
            atr = (prev["atr"] * (period - 1) + _tr(bars, i)) / period
        bu, bl = hl2 + mult * atr, hl2 - mult * atr
        if prev is None:
            up = b["c"] >= hl2
            st = {"atr": atr, "fu": bu, "fl": bl, "v": bl if up else bu, "up": up}
        else:
            pc = bars[i - 1]["c"]
            fu = bu if (bu < prev["fu"] or pc > prev["fu"]) else prev["fu"]
            fl = bl if (bl > prev["fl"] or pc < prev["fl"]) else prev["fl"]
            if prev["v"] == prev["fu"]:
                v = fu if b["c"] <= fu else fl
            else:
                v = fl if b["c"] >= fl else fu
            st = {"atr": atr, "fu": fu, "fl": fl, "v": v, "up": v == fl}
        turn = 0 if prev is None else (1 if st["up"] and not prev["up"] else (-1 if prev["up"] and not st["up"] else 0))
        out[i] = {"v": float(f"{st['v']:.6f}"), "up": st["up"], "turn": turn, "atr": atr}
        prev = st
    return out


def jma(bars, period=14, phase=50, power=2):
    period = max(1, min(10000, int(period)))
    phase = max(-100, min(100, int(phase)))
    power = max(1, min(10000, int(power)))
    beta = 0.45 * (period - 1) / (0.45 * (period - 1) + 2)
    alpha = beta ** power
    e0 = e1 = e2 = last = warm = 0.0
    direction, count, init = 0, 0, False
    out = []
    for b in bars:
        src = b["c"]
        if not init:
            e0, e1, e2, last, init = src, 0.0, 0.0, src, True
        e0 = (1 - alpha) * src + alpha * e0
        e1 = (src - e0) * (1 - beta) + beta * e1
        e2 = (e0 + (phase / 100 + 1.5) * e1 - last) * ((1 - alpha) ** 2) + (alpha ** 2) * e2
        count += 1
        warm += src
        cur = round_even(warm / count, 4) if count <= period else round_even(e2 + last, 4)
        pv = last
        if cur > pv:
            direction = 1
        elif cur < pv:
            direction = -1
        elif direction == 0:
            direction = 1
        slope = round_even((cur / pv - 1) * 100, 1) if pv != 0 else 0
        last = cur
        out.append({"v": cur, "dir": direction, "slope": slope})
    return out


def compute(bars, st_period=14, st_mult=2.0, jma_period=14, jma_phase=50, jma_power=2):
    """bars와 같은 길이로 정렬된 결과. 잘린 가장 오래된 날(day_ok=False)은 None."""
    start = next((i for i, b in enumerate(bars) if b.get("day_ok", True)), len(bars))
    sub = bars[start:]
    pad = [None] * start
    return {
        "start": start,
        "params": {"st_period": st_period, "st_mult": st_mult,
                   "jma_period": jma_period, "jma_phase": jma_phase, "jma_power": jma_power},
        "st": pad + supertrend(sub, st_period, st_mult),
        "jma": pad + jma(sub, jma_period, jma_phase, jma_power),
    }
