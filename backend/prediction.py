"""
Probability Prediction Engine — "Promax" version.

Combines multiple statistical models to estimate the likelihood of each
lô number (00-99) appearing on the next draw for a given region.

Models used (each emits a 100-vector of [0,1] scores, normalized):
  1. Empirical frequency        — long-window appearance rate
  2. Recency-weighted frequency — exponential decay weighting recent days
  3. Poisson gap (overdue)      — P(at least one in `gap` days | base rate)
  4. Markov transition          — P(lô tomorrow | lô set today/yesterday)
  5. Temperature (z-score)      — hot vs cold deviation
  6. Pair pattern               — co-occurrence with recent lô
  7. Streak / consecutive boost — recent consecutive days raise probability

Final score = weighted sum, then softmax-normalized → probability distribution
across 100 lô that sums to 1.0. Per-lô confidence reported as variance across models.
"""

from __future__ import annotations
import math
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Dict, List

from database import get_connection


# ═══════════════════════════════════════════════════════════
# DATA LOADING
# ═══════════════════════════════════════════════════════════

def _load_history(region: str, days: int = 60) -> Dict[str, Dict[str, int]]:
    """
    Load lô daily counts for a region over the last `days` days.
    Returns: { date_str: { lo_number: count } }
    """
    conn = get_connection()
    cursor = conn.cursor()
    cutoff = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
    cursor.execute('''
        SELECT date, lo_number, count
        FROM lo_daily
        WHERE region = ? AND date >= ?
        ORDER BY date ASC
    ''', (region, cutoff))
    history: Dict[str, Dict[str, int]] = defaultdict(dict)
    for row in cursor.fetchall():
        history[row['date']][row['lo_number']] = row['count']
    conn.close()
    return dict(history)


def _all_los() -> List[str]:
    return [f'{i:02d}' for i in range(100)]


# ═══════════════════════════════════════════════════════════
# MODEL 1: EMPIRICAL FREQUENCY
# ═══════════════════════════════════════════════════════════

def model_frequency(history: Dict[str, Dict[str, int]]) -> Dict[str, float]:
    """Long-window per-day appearance rate, normalized."""
    total_days = max(1, len(history))
    counts = {lo: 0 for lo in _all_los()}
    for day in history.values():
        for lo in day:
            counts[lo] += 1                    # appearance days, not raw count
    return {lo: counts[lo] / total_days for lo in counts}


# ═══════════════════════════════════════════════════════════
# MODEL 2: RECENCY-WEIGHTED FREQUENCY (exponential decay)
# ═══════════════════════════════════════════════════════════

def model_recency(history: Dict[str, Dict[str, int]], half_life: float = 7.0) -> Dict[str, float]:
    """
    Exponentially-weighted appearance rate.
    Days closer to today are weighted more (half-life days).
    """
    if not history:
        return {lo: 0.0 for lo in _all_los()}

    dates = sorted(history.keys())
    last_date = datetime.strptime(dates[-1], '%Y-%m-%d')
    decay = math.log(2) / half_life

    counts = {lo: 0.0 for lo in _all_los()}
    weight_sum = 0.0
    for date_str in dates:
        d = datetime.strptime(date_str, '%Y-%m-%d')
        age = (last_date - d).days
        w = math.exp(-decay * age)
        weight_sum += w
        for lo in history[date_str]:
            counts[lo] += w

    if weight_sum == 0:
        return {lo: 0.0 for lo in _all_los()}
    return {lo: counts[lo] / weight_sum for lo in counts}


# ═══════════════════════════════════════════════════════════
# MODEL 3: POISSON GAP (overdue probability)
# ═══════════════════════════════════════════════════════════

def model_poisson_gap(history: Dict[str, Dict[str, int]]) -> Dict[str, float]:
    """
    For each lô, calculate P(it appears tomorrow | gap days since last).
    Using Poisson assumption: P(at least 1 in next day | rate λ) = 1 - exp(-λ).
    The longer the gap, the more "overdue" — but only relative to its base rate.
    """
    base = model_frequency(history)
    if not history:
        return {lo: 0.0 for lo in _all_los()}

    dates = sorted(history.keys())
    last_date_str = dates[-1]
    last_date = datetime.strptime(last_date_str, '%Y-%m-%d')

    # last_seen[lo] = most recent date lô appeared
    last_seen: Dict[str, datetime] = {}
    for date_str in dates:
        d = datetime.strptime(date_str, '%Y-%m-%d')
        for lo in history[date_str]:
            last_seen[lo] = d

    out = {}
    for lo in _all_los():
        rate = base[lo]
        if rate <= 0:
            out[lo] = 0.0
            continue
        if lo in last_seen:
            gap = (last_date - last_seen[lo]).days + 1   # +1 = predicting tomorrow
        else:
            gap = len(history)
        # P(at least one event in gap+1 days): 1 - exp(-rate * (gap+1))
        # But we want delta vs base — how much is it "due"
        out[lo] = 1.0 - math.exp(-rate * gap)
    return out


# ═══════════════════════════════════════════════════════════
# MODEL 4: MARKOV TRANSITION (1-day lag)
# ═══════════════════════════════════════════════════════════

def model_markov(history: Dict[str, Dict[str, int]]) -> Dict[str, float]:
    """
    P(lô X tomorrow | lô set Y today) — averaged.
    Builds a transition matrix from consecutive day pairs.
    """
    if len(history) < 2:
        return {lo: 0.0 for lo in _all_los()}

    dates = sorted(history.keys())
    # transitions[from_lo][to_lo] = count
    transitions: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
    from_totals: Dict[str, int] = defaultdict(int)

    for i in range(len(dates) - 1):
        today_set = set(history[dates[i]].keys())
        next_set = set(history[dates[i + 1]].keys())
        for f in today_set:
            from_totals[f] += 1
            for t in next_set:
                transitions[f][t] += 1

    last_set = set(history[dates[-1]].keys())
    if not last_set:
        return {lo: 0.0 for lo in _all_los()}

    out = {lo: 0.0 for lo in _all_los()}
    for f in last_set:
        denom = from_totals.get(f, 0)
        if denom == 0:
            continue
        for t in _all_los():
            out[t] += transitions[f][t] / denom

    # Average across the contributing today-lô
    n = len(last_set)
    return {lo: out[lo] / n for lo in out}


# ═══════════════════════════════════════════════════════════
# MODEL 5: TEMPERATURE (z-score recent vs base)
# ═══════════════════════════════════════════════════════════

def model_temperature(history: Dict[str, Dict[str, int]], window: int = 7) -> Dict[str, float]:
    """
    Z-score of last `window` days frequency vs long-term base.
    Higher = "hotter" lately. Mapped to (0, 1) via sigmoid.
    """
    if not history:
        return {lo: 0.5 for lo in _all_los()}

    dates = sorted(history.keys())
    recent_dates = dates[-window:]
    if not recent_dates:
        return {lo: 0.5 for lo in _all_los()}

    recent_history = {d: history[d] for d in recent_dates}
    recent_freq = model_frequency(recent_history)
    base_freq = model_frequency(history)

    # Sample std using base rates as reference
    base_values = list(base_freq.values())
    mean_b = sum(base_values) / len(base_values)
    var_b = sum((x - mean_b) ** 2 for x in base_values) / max(1, len(base_values) - 1)
    std_b = math.sqrt(var_b) if var_b > 0 else 1e-9

    out = {}
    for lo in _all_los():
        z = (recent_freq[lo] - base_freq[lo]) / std_b
        # sigmoid → (0, 1); 0.5 = neutral
        out[lo] = 1.0 / (1.0 + math.exp(-z))
    return out


# ═══════════════════════════════════════════════════════════
# MODEL 6: PAIR / CO-OCCURRENCE
# ═══════════════════════════════════════════════════════════

def model_pair(history: Dict[str, Dict[str, int]]) -> Dict[str, float]:
    """
    Score lô based on co-occurrence with recent lô set.
    P(X | Y in same draw) averaged across recent lô.
    """
    if not history:
        return {lo: 0.0 for lo in _all_los()}

    dates = sorted(history.keys())
    co_occur: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
    appearances: Dict[str, int] = defaultdict(int)

    for date_str in dates:
        day_set = list(history[date_str].keys())
        for lo in day_set:
            appearances[lo] += 1
        for i in range(len(day_set)):
            for j in range(len(day_set)):
                if i != j:
                    co_occur[day_set[i]][day_set[j]] += 1

    last_set = list(history[dates[-1]].keys())
    if not last_set:
        return {lo: 0.0 for lo in _all_los()}

    out = {lo: 0.0 for lo in _all_los()}
    for partner in last_set:
        denom = appearances.get(partner, 0)
        if denom == 0:
            continue
        for lo in _all_los():
            out[lo] += co_occur[partner][lo] / denom

    n = len(last_set)
    return {lo: out[lo] / n for lo in out}


# ═══════════════════════════════════════════════════════════
# MODEL 7: STREAK BOOST (consecutive momentum)
# ═══════════════════════════════════════════════════════════

def model_streak(history: Dict[str, Dict[str, int]]) -> Dict[str, float]:
    """
    Boost lô that appeared in consecutive recent days.
    """
    if not history:
        return {lo: 0.0 for lo in _all_los()}

    dates = sorted(history.keys())
    out = {lo: 0.0 for lo in _all_los()}

    for lo in _all_los():
        streak = 0
        for date_str in reversed(dates):
            if lo in history[date_str]:
                streak += 1
            else:
                break
        # streak 0=>0, 1=>0.3, 2=>0.55, 3=>0.75, 4+=>0.9
        if streak == 0:
            out[lo] = 0.0
        elif streak == 1:
            out[lo] = 0.3
        elif streak == 2:
            out[lo] = 0.55
        elif streak == 3:
            out[lo] = 0.75
        else:
            out[lo] = 0.9
    return out


# ═══════════════════════════════════════════════════════════
# COMBINE — weighted ensemble + softmax
# ═══════════════════════════════════════════════════════════

WEIGHTS = {
    'frequency':   0.20,
    'recency':     0.25,
    'poisson':     0.15,
    'markov':      0.10,
    'temperature': 0.10,
    'pair':        0.10,
    'streak':      0.10,
}


def _normalize(scores: Dict[str, float]) -> Dict[str, float]:
    """Min-max normalize to [0, 1]."""
    vals = list(scores.values())
    if not vals:
        return scores
    lo, hi = min(vals), max(vals)
    if hi - lo < 1e-12:
        return {k: 0.5 for k in scores}
    return {k: (v - lo) / (hi - lo) for k, v in scores.items()}


def _softmax(scores: Dict[str, float], temperature: float = 0.5) -> Dict[str, float]:
    """Softmax with temperature; lower T = sharper distribution."""
    if temperature <= 0:
        temperature = 1e-6
    vals = [v / temperature for v in scores.values()]
    m = max(vals)
    exps = [math.exp(v - m) for v in vals]
    s = sum(exps)
    return {k: e / s for k, e in zip(scores.keys(), exps)}


def predict(region: str = 'xsmn', window_days: int = 60) -> dict:
    """
    Run the full ensemble and return predictions.
    """
    history = _load_history(region, days=window_days)
    days_loaded = len(history)

    if days_loaded < 5:
        return {
            'region': region,
            'window_days': window_days,
            'days_available': days_loaded,
            'warning': 'Cần ít nhất 5 ngày dữ liệu để dự đoán',
            'predictions': [],
        }

    models = {
        'frequency':   model_frequency(history),
        'recency':     model_recency(history),
        'poisson':     model_poisson_gap(history),
        'markov':      model_markov(history),
        'temperature': model_temperature(history),
        'pair':        model_pair(history),
        'streak':      model_streak(history),
    }
    norm_models = {name: _normalize(m) for name, m in models.items()}

    # Weighted ensemble
    composite: Dict[str, float] = {lo: 0.0 for lo in _all_los()}
    for name, m in norm_models.items():
        w = WEIGHTS.get(name, 0)
        for lo in composite:
            composite[lo] += w * m[lo]

    # Convert to probability distribution via softmax
    probs = _softmax(composite, temperature=0.15)

    # Per-lô variance across models (confidence indicator)
    confidence: Dict[str, float] = {}
    for lo in _all_los():
        scores = [norm_models[name][lo] for name in norm_models]
        mean_s = sum(scores) / len(scores)
        var_s = sum((s - mean_s) ** 2 for s in scores) / len(scores)
        confidence[lo] = 1.0 - math.sqrt(var_s)   # lower variance = higher confidence

    predictions = []
    for lo in _all_los():
        predictions.append({
            'lo_number': lo,
            'probability': round(probs[lo] * 100, 4),     # %
            'composite_score': round(composite[lo], 4),
            'confidence': round(confidence[lo] * 100, 1),  # %
            'breakdown': {name: round(norm_models[name][lo], 4) for name in norm_models},
        })

    predictions.sort(key=lambda x: x['probability'], reverse=True)
    for rank, p in enumerate(predictions, 1):
        p['rank'] = rank

    expected = 100.0 / 100.0  # uniform = 1%
    top_lift = predictions[0]['probability'] / expected if expected > 0 else 0

    return {
        'region': region,
        'window_days': window_days,
        'days_available': days_loaded,
        'model_weights': WEIGHTS,
        'top_lift': round(top_lift, 2),    # how many × uniform the top pick is
        'predictions': predictions,
    }


if __name__ == '__main__':
    import json
    r = predict('xsmn', 60)
    print(f"Region: {r['region']} | Days: {r['days_available']}")
    print(f"Top 10 most likely lô:")
    for p in r['predictions'][:10]:
        print(f"  #{p['rank']}: lô {p['lo_number']} → {p['probability']:.3f}%  "
              f"(conf {p['confidence']}%)")
    print(f"\nBottom 5 least likely:")
    for p in r['predictions'][-5:]:
        print(f"  #{p['rank']}: lô {p['lo_number']} → {p['probability']:.3f}%")
