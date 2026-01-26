(() => {
  const TF_TO_SECONDS = {
    '1m': 60,
    '5m': 300,
    '15m': 900,
    '1h': 3600,
    '4h': 14400,
    '1d': 86400,
  };

  function tfToSeconds(tf) {
    return TF_TO_SECONDS[tf] || 60;
  }

  function normalizeBar(bar) {
    if (!bar) return null;
    const openTime = bar.open_time_ms ?? bar.open_time ?? bar.t ?? null;
    const time = bar.time ?? (openTime !== null ? Math.floor(Number(openTime) / 1000) : null);
    if (!time || time <= 0) return null;
    const open = Number(bar.open ?? bar.open_price ?? bar.o ?? bar.open_price);
    const high = Number(bar.high ?? bar.high_price ?? bar.h ?? bar.high_price);
    const low = Number(bar.low ?? bar.low_price ?? bar.l ?? bar.low_price);
    const close = Number(bar.close ?? bar.close_price ?? bar.c ?? bar.close_price);
    if (!Number.isFinite(open) || !Number.isFinite(high) || !Number.isFinite(low) || !Number.isFinite(close)) {
      return null;
    }
    const volumeRaw = bar.volume ?? bar.v ?? null;
    const volume = volumeRaw !== null ? Number(volumeRaw) : null;
    return { time, open, high, low, close, volume };
  }

  function normalizeBars(bars) {
    if (!Array.isArray(bars)) return [];
    const out = [];
    for (const bar of bars) {
      const normalized = normalizeBar(bar);
      if (normalized) {
        out.push(normalized);
      }
    }
    return out;
  }

  function dedupSort(bars) {
    const map = new Map();
    for (const bar of bars) {
      map.set(bar.time, bar);
    }
    return Array.from(map.values()).sort((a, b) => a.time - b.time);
  }

  function insertWhitespace(bars, tfSec) {
    const sorted = dedupSort(bars);
    if (sorted.length === 0) return [];
    const output = [];
    let lastTime = null;
    for (const bar of sorted) {
      if (lastTime !== null && tfSec > 0 && bar.time > lastTime + tfSec) {
        let cursor = lastTime + tfSec;
        while (cursor < bar.time) {
          output.push({ time: cursor });
          cursor += tfSec;
        }
      }
      output.push(bar);
      lastTime = bar.time;
    }
    return output;
  }

  function gapPlaceholders(prevTime, nextTime, tfSec) {
    if (!prevTime || !nextTime || tfSec <= 0) return [];
    if (nextTime <= prevTime + tfSec) return [];
    const out = [];
    let cursor = prevTime + tfSec;
    while (cursor < nextTime) {
      out.push({ time: cursor });
      cursor += tfSec;
    }
    return out;
  }

  window.ChartAdapter = {
    tfToSeconds,
    normalizeBar,
    normalizeBars,
    insertWhitespace,
    gapPlaceholders,
  };
})();
