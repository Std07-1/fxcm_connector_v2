(() => {
  const chartEl = document.getElementById('chart');
  const statusEl = document.getElementById('status');
  const symbolSelect = document.getElementById('symbol');
  const tfSelect = document.getElementById('tf');
  const modeSelect = document.getElementById('mode');
  const seriesTypeSelect = document.getElementById('series-type');
  const clearBtn = document.getElementById('clear');
  const wsAgeEl = document.getElementById('ws-age');
  const barsRxEl = document.getElementById('bars-rx');
  const currentEl = document.getElementById('current-sub');
  const subscribeBtn = document.getElementById('subscribe');
  const fitBtn = document.getElementById('fit');
  const diagnosticsBtn = document.getElementById('toggle-diagnostics');

  const topbarEl = document.querySelector('.topbar');
  const chartWrapEl = document.querySelector('.chart-wrap');
  const healthBarEl = document.createElement('div');
  healthBarEl.className = 'healthbar';
  if (topbarEl && topbarEl.parentElement) {
    topbarEl.insertAdjacentElement('afterend', healthBarEl);
  }
  const overlayEl = document.createElement('div');
  overlayEl.className = 'health-overlay hidden';
  if (chartWrapEl) {
    chartWrapEl.appendChild(overlayEl);
  }
  const drawerBackdropEl = document.createElement('div');
  drawerBackdropEl.className = 'drawer-backdrop hidden';
  const drawerEl = document.createElement('div');
  drawerEl.className = 'drawer hidden';
  const drawerContentEl = document.createElement('div');
  drawerContentEl.className = 'drawer-content';
  drawerEl.appendChild(drawerContentEl);
  document.body.appendChild(drawerBackdropEl);
  document.body.appendChild(drawerEl);

  function _createHealthBlock(title) {
    const block = document.createElement('div');
    block.className = 'health-block';
    const label = document.createElement('div');
    label.className = 'health-title';
    label.textContent = title;
    const body = document.createElement('div');
    body.className = 'health-body';
    block.appendChild(label);
    block.appendChild(body);
    healthBarEl.appendChild(block);
    return { block, body };
  }

  const statusBlock = _createHealthBlock('СТАТУС');
  const tickBlock = _createHealthBlock('ТІК');
  const wsBlock = _createHealthBlock('WS');
  const uiBlock = _createHealthBlock('UI');
  const finalBlock = _createHealthBlock('FINAL');
  const cmdBlock = _createHealthBlock('CMD');
  const statusBlockEl = statusBlock.body;
  const tickBlockEl = tickBlock.body;
  const wsBlockEl = wsBlock.body;
  const uiBlockEl = uiBlock.body;
  const finalBlockEl = finalBlock.body;
  const cmdBlockEl = cmdBlock.body;

  const STORAGE_KEY = 'ui_lite_settings_v1';
  const DIAG_KEY = 'ui_lite_diagnostics_mode_v1';
  const CMD_SETTINGS_KEY = 'ui_lite_command_settings_v1';
  let lastTimeRange = null;
  let pendingTimeRange = null;
  let appliedTimeRange = false;
  let diagnosticsMode = 'inline';
  let lastCommandAck = null;
  let lastCommandSentAt = 0;
  let ws = null;

  function _normalizeTimeRange(raw) {
    if (!raw || typeof raw !== 'object') return null;
    const from = Number(raw.from);
    const to = Number(raw.to);
    if (!Number.isFinite(from) || !Number.isFinite(to)) return null;
    if (to <= from) return null;
    return { from, to };
  }

  function loadSettings() {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (!raw) return {};
      const parsed = JSON.parse(raw);
      return parsed && typeof parsed === 'object' ? parsed : {};
    } catch {
      return {};
    }
  }

  function loadCommandSettings() {
    try {
      const raw = localStorage.getItem(CMD_SETTINGS_KEY);
      if (!raw) return {};
      const parsed = JSON.parse(raw);
      return parsed && typeof parsed === 'object' ? parsed : {};
    } catch {
      return {};
    }
  }

  function saveCommandSettings(values) {
    try {
      localStorage.setItem(CMD_SETTINGS_KEY, JSON.stringify(values || {}));
    } catch {
      // ignore
    }
  }

  function saveSettings() {
    const payload = {
      symbol: currentSymbol(),
      tf: currentTf(),
      mode: currentMode(),
      seriesType: seriesTypeSelect ? String(seriesTypeSelect.value || 'candle') : 'candle',
      timeRange: lastTimeRange ? { from: lastTimeRange.from, to: lastTimeRange.to } : null,
    };
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(payload));
    } catch {
      // ignore
    }
  }

  function applySettings() {
    const settings = loadSettings();
    if (settings.symbol && symbolSelect) {
      symbolSelect.value = String(settings.symbol);
    }
    if (settings.tf && tfSelect) {
      tfSelect.value = String(settings.tf);
    }
    if (settings.mode && modeSelect) {
      modeSelect.value = String(settings.mode);
    }
    if (settings.seriesType && seriesTypeSelect) {
      seriesTypeSelect.value = String(settings.seriesType);
    }
    pendingTimeRange = _normalizeTimeRange(settings.timeRange);
    appliedTimeRange = false;
  }

  function _setDiagnosticsMode(mode) {
    diagnosticsMode = mode;
    if (!healthBarEl) return;
    healthBarEl.classList.remove('overlay');
    healthBarEl.classList.remove('hidden');
    if (mode === 'hidden') {
      healthBarEl.classList.add('hidden');
    } else if (mode === 'overlay') {
      healthBarEl.classList.add('overlay');
    }
    if (mode === 'overlay' && chartWrapEl) {
      chartWrapEl.appendChild(healthBarEl);
    } else if (topbarEl && topbarEl.parentElement) {
      topbarEl.insertAdjacentElement('afterend', healthBarEl);
    }
    try {
      localStorage.setItem(DIAG_KEY, mode);
    } catch {
      // ignore
    }
    if (diagnosticsBtn) {
      const label = mode === 'overlay' ? 'Діагностика: overlay' : mode === 'hidden' ? 'Діагностика: hidden' : 'Діагностика: inline';
      diagnosticsBtn.textContent = label;
    }
  }

  function _cycleDiagnosticsMode() {
    const next = diagnosticsMode === 'inline' ? 'overlay' : diagnosticsMode === 'overlay' ? 'hidden' : 'inline';
    _setDiagnosticsMode(next);
  }

  function _badge(text, kind) {
    return `<span class="badge ${kind}">${text}</span>`;
  }

  function _fmt(value) {
    if (value === null || value === undefined) return '-';
    if (Number.isFinite(value)) return String(Math.round(Number(value)));
    return String(value);
  }

  function _parseUtcMs(value) {
    if (!value) return null;
    const ts = Date.parse(String(value));
    return Number.isFinite(ts) ? ts : null;
  }

  function _formatUtc(value) {
    const ts = _parseUtcMs(value);
    if (!ts) return '-';
    const iso = new Date(ts).toISOString();
    const date = iso.slice(0, 10);
    const time = iso.slice(11, 16);
    return `${date} ${time} UTC`;
  }

  function _formatUtcMs(ms) {
    if (!Number.isFinite(ms) || ms <= 0) return '-';
    const iso = new Date(Number(ms)).toISOString();
    const date = iso.slice(0, 10);
    const time = iso.slice(11, 16);
    return `${date} ${time} UTC`;
  }

  function _formatDuration(ms) {
    if (!Number.isFinite(ms) || ms === null) return '-';
    const total = Math.max(0, Math.floor(ms / 1000));
    const h = Math.floor(total / 3600);
    const m = Math.floor((total % 3600) / 60);
    const s = total % 60;
    return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
  }

  function _escape(value) {
    const str = String(value ?? '');
    return str.replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  }

  function _renderDrawer(status) {
    if (!drawerContentEl) return;
    const degraded = Array.isArray(status?.degraded) ? status.degraded : [];
    const errors = Array.isArray(status?.errors) ? status.errors.slice(-20) : [];
    const lastCmd = status?.last_command || {};
    const degradedList = degraded.length
      ? `<ul>${degraded.map((d) => `<li>${_escape(d)}</li>`).join('')}</ul>`
      : '<div class="drawer-empty">Немає degraded</div>';
    const errorsList = errors.length
      ? `<ul>${errors.map((e) => {
        const code = _escape(e.code || '-');
        const msg = _escape(e.message || '-');
        const ts = _escape(e.ts || e.ts_ms || '-');
        const ctx = _escape(JSON.stringify(e.context || {}));
        return `<li><strong>${code}</strong> ${msg}<div class="drawer-meta">${ts} • ${ctx}</div></li>`;
      }).join('')}</ul>`
      : '<div class="drawer-empty">Немає помилок</div>';
    const cmdBlock = `
      <div class="drawer-cmd">
        <div><strong>CMD</strong>: ${_escape(lastCmd.cmd || '-')}</div>
        <div><strong>REQ</strong>: ${_escape(lastCmd.req_id || '-')}</div>
        <div><strong>STATE</strong>: ${_escape(lastCmd.state || '-')}</div>
      </div>
    `;
    const cmdSettings = loadCommandSettings();
    const lookbackDays = Number(cmdSettings.lookbackDays || 7);
    const backfillDays = Number(cmdSettings.backfillDays || 7);
    const windowHours = Number(cmdSettings.windowHours || 24);
    const commandStatus = lastCommandAck ? _escape(lastCommandAck) : 'Очікує на команду';
    drawerContentEl.innerHTML = `
      <div class="drawer-section">
        <div class="drawer-title">DEGRADED</div>
        ${degradedList}
      </div>
      <div class="drawer-section">
        <div class="drawer-title">ERRORS</div>
        ${errorsList}
      </div>
      <div class="drawer-section">
        <div class="drawer-title">КОМАНДИ (локально)</div>
        <div class="drawer-cmd-controls">
          <label>Warmup days
            <input id="cmd-lookback" type="number" min="1" value="${_escape(lookbackDays)}" />
          </label>
          <label>Backfill days
            <input id="cmd-backfill" type="number" min="1" value="${_escape(backfillDays)}" />
          </label>
          <label>Window hours
            <input id="cmd-window" type="number" min="1" value="${_escape(windowHours)}" />
          </label>
          <div class="drawer-cmd-actions">
            <button id="cmd-warmup">Warmup</button>
            <button id="cmd-backfill">Backfill</button>
            <button id="cmd-republish">Republish tail</button>
            <button id="cmd-bootstrap">Bootstrap</button>
          </div>
          <div class="drawer-cmd-status" id="cmd-status">${commandStatus}</div>
        </div>
      </div>
      <div class="drawer-section">
        <div class="drawer-title">LAST COMMAND</div>
        ${cmdBlock}
      </div>
    `;
    _bindCommandControls();
  }

  function _buildUtcIso(daysBack) {
    const ms = Date.now() - Number(daysBack) * 24 * 60 * 60 * 1000;
    return new Date(ms).toISOString().slice(0, 19) + 'Z';
  }

  function _updateCommandStatus(text) {
    lastCommandAck = text;
    const el = document.getElementById('cmd-status');
    if (el) {
      el.textContent = text;
    }
  }

  function _sendCommand(cmd, args) {
    if (!ws || ws.readyState !== WebSocket.OPEN) {
      _updateCommandStatus('WS недоступний');
      return;
    }
    lastCommandSentAt = Date.now();
    _updateCommandStatus(`Відправлено: ${cmd}`);
    ws.send(JSON.stringify({ type: 'command', cmd, args }));
  }

  function _bindCommandControls() {
    const lookbackEl = document.getElementById('cmd-lookback');
    const backfillEl = document.getElementById('cmd-backfill');
    const windowEl = document.getElementById('cmd-window');
    const warmupBtn = document.getElementById('cmd-warmup');
    const backfillBtn = document.getElementById('cmd-backfill');
    const republishBtn = document.getElementById('cmd-republish');
    const bootstrapBtn = document.getElementById('cmd-bootstrap');
    if (!lookbackEl || !backfillEl || !windowEl) return;

    const persist = () => {
      saveCommandSettings({
        lookbackDays: Number(lookbackEl.value || 7),
        backfillDays: Number(backfillEl.value || 7),
        windowHours: Number(windowEl.value || 24),
      });
    };
    lookbackEl.addEventListener('change', persist);
    backfillEl.addEventListener('change', persist);
    windowEl.addEventListener('change', persist);

    if (warmupBtn) {
      warmupBtn.addEventListener('click', () => {
        persist();
        _sendCommand('fxcm_warmup', {
          symbols: [currentSymbol()],
          lookback_days: Number(lookbackEl.value || 7),
          publish: true,
          window_hours: Number(windowEl.value || 24),
        });
      });
    }
    if (backfillBtn) {
      backfillBtn.addEventListener('click', () => {
        persist();
        const days = Number(backfillEl.value || 7);
        _sendCommand('fxcm_backfill', {
          symbol: currentSymbol(),
          start_utc: _buildUtcIso(days),
          end_utc: new Date().toISOString().slice(0, 19) + 'Z',
          publish: true,
          window_hours: Number(windowEl.value || 24),
        });
      });
    }
    if (republishBtn) {
      republishBtn.addEventListener('click', () => {
        persist();
        _sendCommand('fxcm_republish_tail', {
          symbol: currentSymbol(),
          timeframes: ['1m'],
          window_hours: Number(windowEl.value || 24),
          force: true,
        });
      });
    }
    if (bootstrapBtn) {
      bootstrapBtn.addEventListener('click', () => {
        persist();
        const days = Number(backfillEl.value || 7);
        _sendCommand('fxcm_bootstrap', {
          warmup: {
            symbols: [currentSymbol()],
            lookback_days: Number(lookbackEl.value || 7),
            publish: true,
            window_hours: Number(windowEl.value || 24),
          },
          backfill: {
            symbol: currentSymbol(),
            start_utc: _buildUtcIso(days),
            end_utc: new Date().toISOString().slice(0, 19) + 'Z',
            publish: true,
            window_hours: Number(windowEl.value || 24),
          },
          republish_tail: {
            symbol: currentSymbol(),
            timeframes: ['1m'],
            window_hours: Number(windowEl.value || 24),
            force: true,
          },
        });
      });
    }
  }

  function _openDrawer(status) {
    _renderDrawer(status || {});
    drawerBackdropEl.classList.remove('hidden');
    drawerEl.classList.remove('hidden');
  }

  function _closeDrawer() {
    drawerBackdropEl.classList.add('hidden');
    drawerEl.classList.add('hidden');
  }

  function _renderStatusBlock(status, health) {
    const degraded = Array.isArray(status?.degraded) ? status.degraded : [];
    const errors = Array.isArray(status?.errors) ? status.errors.length : 0;
    const lastState = status?.last_command?.state || '-';
    const statusOk = health?.status_ok === true;
    const statusStale = health?.status_stale === true;
    const statusAge = statusAgeDisplayMs;
    const statusErr = health?.last_status_error_short || '';
    const badges = degraded.length
      ? degraded.slice(0, 3).map((tag) => _badge(String(tag), 'warn')).join('')
      : _badge('OK', 'ok');
    let statusBadge = _badge('OK', 'ok');
    if (!statusOk) {
      statusBadge = _badge('N/A', 'na');
    } else if (statusStale) {
      statusBadge = _badge('STALE', 'stale');
    }
    const marketOpen = status?.market?.is_open;
    const nextOpenRaw = status?.market?.next_open_utc || '-';
    const nextOpen = _formatUtc(nextOpenRaw);
    const nextOpenMs = _parseUtcMs(nextOpenRaw);
    const eta = nextOpenMs ? _formatDuration(nextOpenMs - Date.now()) : '-';
    const marketBadge = marketOpen === false ? _badge('Ринок закритий', 'warn') : _badge('Ринок відкритий', 'ok');
    statusBlockEl.innerHTML = `
      <div class="health-row">
        <span class="health-label">СТАТУС</span>${statusBadge}
      </div>
      <div class="health-row">
        <span class="health-label">AGE</span>${_badge(_fmt(statusAge), 'neutral')}
      </div>
      <div class="health-row">
        <span class="health-label">ПОМИЛКИ</span>${_badge(String(errors), errors ? 'error' : 'ok')}
      </div>
      <div class="health-row">
        <span class="health-label">ДЕГРАДАЦІЯ</span>${badges}
      </div>
      <div class="health-row">
        <span class="health-label">ОСТАННЯ КОМАНДА</span>${_badge(String(lastState), 'neutral')}
      </div>
      <div class="health-row">
        <span class="health-label">РИНок</span>${marketBadge}
      </div>
      <div class="health-row">
        <span class="health-label">NEXT OPEN</span>${_badge(String(nextOpen), 'neutral')}
      </div>
      <div class="health-row">
        <span class="health-label">TIME TO OPEN</span>${_badge(String(eta), 'neutral')}
      </div>
      ${statusErr ? `<div class="health-row"><span class="health-label">ERR</span>${_badge(String(statusErr), 'error')}</div>` : ''}
    `;
  }

  function _renderTickBlock(status) {
    const price = status?.price || {};
    const tickSkew = _fmt(price.tick_skew_ms);
    const drops = _fmt(price.ticks_dropped_1m);
    const lastEvent = Number(price.last_tick_event_ms || 0);
    const age = lastEvent > 0 ? _fmt(Date.now() - lastEvent) : '-';
    const tickBadge = lastEvent > 0 ? _badge(age, 'neutral') : _badge('N/A', 'na');
    tickBlockEl.innerHTML = `
      <div class="health-row">
        <span class="health-label">СК’Ю</span>${_badge(tickSkew, 'neutral')}
      </div>
      <div class="health-row">
        <span class="health-label">DROPS</span>${_badge(drops, drops !== '-' && Number(drops) > 0 ? 'warn' : 'ok')}
      </div>
      <div class="health-row">
        <span class="health-label">ОСТАННІЙ ТІК</span>${tickBadge}
      </div>
    `;
  }

  function _renderWsBlock() {
    const wsAge = wsAgeDisplayMs;
    const dataAge = lastBarUpdateMs > 0 ? Date.now() - lastBarUpdateMs : null;
    const dataBadge = dataAge !== null && dataAge > 5000 ? _badge('STALE', 'stale') : _badge('OK', 'ok');
    wsBlockEl.innerHTML = `
      <div class="health-row">
        <span class="health-label">WS AGE</span>${_badge(_fmt(wsAge), wsAge !== null && wsAge > 5000 ? 'warn' : 'ok')}
      </div>
      <div class="health-row">
        <span class="health-label">BARS</span>${_badge(String(barsRxTotal), 'neutral')}
      </div>
      <div class="health-row">
        <span class="health-label">DATA</span>${dataBadge}
      </div>
    `;
  }

  function _renderUiBlock(ui) {
    const ohlcvInvalid = _fmt(ui?.ohlcv_inbound_invalid_total ?? 0);
    const statusInvalid = _fmt(ui?.status_invalid_total ?? 0);
    uiBlockEl.innerHTML = `
      <div class="health-row">
        <span class="health-label">OHLCV INVALID</span>${_badge(String(ohlcvInvalid), Number(ohlcvInvalid) > 0 ? 'warn' : 'ok')}
      </div>
      <div class="health-row">
        <span class="health-label">STATUS INVALID</span>${_badge(String(statusInvalid), Number(statusInvalid) > 0 ? 'warn' : 'ok')}
      </div>
    `;
  }

  function _renderFinalBlock(status) {
    const final1m = status?.ohlcv_final_1m || {};
    const coverage = status?.ohlcv?.final_1m || {};
    const republish = status?.republish || {};
    const tailSummary = status?.tail_guard_summary || {};
    const tf1m = tailSummary?.tf_states?.['1m'] || {};
    const lastClose = Number(final1m.last_complete_bar_ms || 0);
    const lagMs = _fmt(final1m.lag_ms);
    const coverageOk = coverage.coverage_ok === true;
    const coverageDays = _fmt(coverage.coverage_days);
    const retentionDays = _fmt(coverage.retention_target_days);
    const republishState = republish.state || '-';
    const republishBatches = _fmt(republish.published_batches);
    const tailState = tf1m.state || '-';
    const tailMissing = _fmt(tf1m.missing_bars ?? 0);
    finalBlockEl.innerHTML = `
      <div class="health-row">
        <span class="health-label">FINAL 1m</span>${_badge(_formatUtcMs(lastClose), lastClose > 0 ? 'neutral' : 'na')}
      </div>
      <div class="health-row">
        <span class="health-label">LAG</span>${_badge(String(lagMs), lagMs !== '-' ? 'neutral' : 'na')}
      </div>
      <div class="health-row">
        <span class="health-label">COVERAGE</span>${_badge(`${coverageDays}/${retentionDays}`, coverageOk ? 'ok' : 'warn')}
      </div>
      <div class="health-row">
        <span class="health-label">REPUBLISH</span>${_badge(`${_escape(republishState)} • ${republishBatches}`, republishState === 'ok' ? 'ok' : 'neutral')}
      </div>
      <div class="health-row">
        <span class="health-label">TAIL 1m</span>${_badge(`${_escape(tailState)} • ${tailMissing}`, tailState === 'ok' ? 'ok' : 'warn')}
      </div>
    `;
  }

  function _renderCommandBlock(status) {
    const lastCmd = status?.last_command || {};
    const bus = status?.command_bus || {};
    const busState = bus.state || '-';
    const busErr = bus.last_error?.code || '-';
    const cmdName = lastCmd.cmd || '-';
    const cmdState = lastCmd.state || '-';
    cmdBlockEl.innerHTML = `
      <div class="health-row">
        <span class="health-label">BUS</span>${_badge(_escape(busState), busState === 'running' ? 'ok' : 'warn')}
      </div>
      <div class="health-row">
        <span class="health-label">BUS ERR</span>${_badge(_escape(busErr), busErr !== '-' ? 'warn' : 'ok')}
      </div>
      <div class="health-row">
        <span class="health-label">CMD</span>${_badge(_escape(cmdName), 'neutral')}
      </div>
      <div class="health-row">
        <span class="health-label">STATE</span>${_badge(_escape(cmdState), cmdState === 'ok' ? 'ok' : cmdState === 'error' ? 'error' : 'neutral')}
      </div>
    `;
  }

  function _updateOverlay(status) {
    const degraded = Array.isArray(status?.degraded) ? status.degraded : [];
    const previewPaused = status?.price?.preview_paused === true;
    const reasons = [];
    if (degraded.includes('tick_event_time_unavailable')) {
      reasons.push('tick_event_time_unavailable');
    }
    if (previewPaused) {
      reasons.push('preview_paused');
    }
    if (!overlayEl) return;
    if (reasons.length === 0) {
      overlayEl.classList.add('hidden');
      overlayEl.textContent = '';
      return;
    }
    overlayEl.textContent = `ПРЕВʼЮ ПРИЗУПИНЕНО: ${reasons.join(', ')}`;
    overlayEl.classList.remove('hidden');
  }

  statusBlock.block.addEventListener('click', () => {
    if (drawerEl.classList.contains('hidden')) {
      _openDrawer(lastHealth?.status || {});
    } else {
      _closeDrawer();
    }
  });
  if (diagnosticsBtn) {
    diagnosticsBtn.addEventListener('click', _cycleDiagnosticsMode);
  }
  drawerBackdropEl.addEventListener('click', _closeDrawer);
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
      _closeDrawer();
    }
  });

  const chart = LightweightCharts.createChart(chartEl, {
    layout: {
      background: { type: 'solid', color: '#0f1116' },
      textColor: '#cfd3da',
      fontSize: 12,
      fontFamily: 'system-ui, -apple-system, Segoe UI, Roboto, Arial',
    },
    grid: {
      vertLines: { color: '#1f2430' },
      horzLines: { color: '#1f2430' },
    },
    rightPriceScale: {
      visible: true,
      borderVisible: true,
      borderColor: '#2a3140',
      scaleMargins: { top: 0.1, bottom: 0.2 },
    },
    leftPriceScale: { visible: false },
    timeScale: {
      visible: true,
      borderVisible: true,
      borderColor: '#2a3140',
      timeVisible: true,
      secondsVisible: false,
      rightOffset: 3,
      barSpacing: 4,
      fixLeftEdge: false,
      fixRightEdge: false,
    },
    crosshair: {
      mode: 1,
      vertLine: { color: '#5c6370', width: 1, style: 0, labelBackgroundColor: '#1f2430' },
      horzLine: { color: '#5c6370', width: 1, style: 0, labelBackgroundColor: '#1f2430' },
    },
    handleScroll: { mouseWheel: true, pressedMouseMove: true, horzTouchDrag: true, vertTouchDrag: true },
    handleScale: {
      axisPressedMouseMove: { time: true, price: true },
      axisDoubleClickReset: true,
      mouseWheel: true,
      pinch: true,
    },
  });

  try {
    const storedMode = localStorage.getItem(DIAG_KEY);
    if (storedMode === 'overlay' || storedMode === 'hidden' || storedMode === 'inline') {
      _setDiagnosticsMode(storedMode);
    } else {
      _setDiagnosticsMode('inline');
    }
  } catch {
    _setDiagnosticsMode('inline');
  }

  const timeScale = typeof chart.timeScale === 'function' ? chart.timeScale() : null;
  if (timeScale && typeof timeScale.subscribeVisibleTimeRangeChange === 'function') {
    timeScale.subscribeVisibleTimeRangeChange((range) => {
      const normalized = _normalizeTimeRange(range);
      if (!normalized) return;
      lastTimeRange = normalized;
      saveSettings();
    });
  }

  const candleSeries = typeof chart.addCandlestickSeries === 'function'
    ? chart.addCandlestickSeries({
      upColor: '#26a69a',
      borderUpColor: '#26a69a',
      wickUpColor: '#26a69a',
      downColor: '#ef5350',
      borderDownColor: '#ef5350',
      wickDownColor: '#ef5350',
      borderVisible: true,
      wickVisible: true,
      priceLineVisible: true,
      lastValueVisible: true,
      priceFormat: { type: 'price', precision: 2, minMove: 0.01 },
    })
    : (typeof chart.addSeries === 'function' && LightweightCharts && LightweightCharts.CandlestickSeries)
      ? chart.addSeries(LightweightCharts.CandlestickSeries, {
        upColor: '#26a69a',
        borderUpColor: '#26a69a',
        wickUpColor: '#26a69a',
        downColor: '#ef5350',
        borderDownColor: '#ef5350',
        wickDownColor: '#ef5350',
        borderVisible: true,
        wickVisible: true,
        priceLineVisible: true,
        lastValueVisible: true,
        priceFormat: { type: 'price', precision: 2, minMove: 0.01 },
      })
      : null;
  const barSeries = typeof chart.addBarSeries === 'function'
    ? chart.addBarSeries({
      upColor: '#26a69a',
      downColor: '#ef5350',
      thinBars: true,
      openVisible: true,
    })
    : (typeof chart.addSeries === 'function' && LightweightCharts && LightweightCharts.BarSeries)
      ? chart.addSeries(LightweightCharts.BarSeries, {
        upColor: '#26a69a',
        downColor: '#ef5350',
        thinBars: true,
        openVisible: true,
      })
      : null;
  if (barSeries && typeof barSeries.applyOptions === 'function') {
    barSeries.applyOptions({ visible: false });
  }
  const volumeSeries = typeof chart.addHistogramSeries === 'function'
    ? chart.addHistogramSeries({
      color: 'rgba(31,35,43,0.5)',
      priceFormat: { type: 'volume' },
      priceScaleId: 'volume',
    })
    : (typeof chart.addSeries === 'function' && LightweightCharts && LightweightCharts.HistogramSeries)
      ? chart.addSeries(LightweightCharts.HistogramSeries, {
        color: 'rgba(31,35,43,0.5)',
        priceFormat: { type: 'volume' },
        priceScaleId: 'volume',
      })
      : null;

  if (typeof chart.priceScale === 'function') {
    chart.priceScale('volume').applyOptions({
      scaleMargins: { top: 0.95, bottom: 0 },
      visible: false,
      borderVisible: false,
    });
  }

  const PRICE_AXIS_HIT_PX = 140;

  function _isPriceScaleEvent(e) {
    if (!e) return false;
    if (typeof e.composedPath === 'function') {
      const path = e.composedPath();
      for (const node of path) {
        if (!node || !node.classList) continue;
        if (node.classList.contains('price-scale') || node.classList.contains('right')) {
          return true;
        }
      }
    }
    const rect = chartEl.getBoundingClientRect();
    const x = e.clientX - rect.left;
    return x >= rect.width - PRICE_AXIS_HIT_PX;
  }

  function _activeSeries() {
    return seriesTypeSelect && seriesTypeSelect.value === 'bar' ? barSeries : candleSeries;
  }

  function _ensureYRangeReady() {
    const active = _activeSeries();
    if (!active || typeof active.priceScale !== 'function') return false;
    const ps = active.priceScale();
    if (!ps || typeof ps.getVisibleRange !== 'function') return false;
    if (!seriesDataReady) return false;
    const range = ps.getVisibleRange();
    if (range) return true;
    if (typeof ps.setAutoScale === 'function') {
      ps.setAutoScale(true);
    }
    if (typeof chart.timeScale === 'function') {
      chart.timeScale().fitContent();
    }
    if (!initYRangeAttempted) {
      initYRangeAttempted = true;
      requestAnimationFrame(() => {
        cachedYRange = ps.getVisibleRange();
        if (!cachedYRange) {
          initYRangeAttempted = false;
        }
      });
    }
    return false;
  }

  function _onWheel(e) {
    const timeScale = typeof chart.timeScale === 'function' ? chart.timeScale() : null;
    if (e.shiftKey && timeScale && typeof timeScale.scrollPosition === 'function' && typeof timeScale.scrollToPosition === 'function') {
      e.preventDefault();
      e.stopImmediatePropagation();
      const current = timeScale.scrollPosition();
      const step = Math.sign(e.deltaY || 0) * 3;
      timeScale.scrollToPosition(current + step, false);
      return;
    }
    const active = _activeSeries();
    if (!active) return;
    if (!_isPriceScaleEvent(e)) return;
    if (typeof active.priceScale !== 'function') return;
    const priceScale = active.priceScale();
    if (!priceScale || typeof priceScale.getVisibleRange !== 'function' || typeof priceScale.setVisibleRange !== 'function') return;
    e.preventDefault();
    if (typeof e.stopImmediatePropagation === 'function') {
      e.stopImmediatePropagation();
    }
    if (typeof e.stopPropagation === 'function') {
      e.stopPropagation();
    }
    if (!_ensureYRangeReady()) return;
    const range = priceScale.getVisibleRange();
    if (!range) return;
    if (typeof priceScale.setAutoScale === 'function') {
      priceScale.setAutoScale(false);
    }
    const rect = chartEl.getBoundingClientRect();
    const mouseY = e.clientY - rect.top;
    const anchor = typeof active.coordinateToPrice === 'function' ? active.coordinateToPrice(mouseY) : null;
    if (anchor === null || anchor === undefined) return;
    const span = range.to - range.from;
    if (!Number.isFinite(span) || span <= 0) return;
    const zoomIn = e.deltaY < 0;
    const k = zoomIn ? 0.9 : 1.1;
    const newSpan = span * k;
    const t = (anchor - range.from) / span;
    const newFrom = anchor - newSpan * t;
    const newTo = newFrom + newSpan;
    priceScale.setVisibleRange({ from: newFrom, to: newTo });
  }

  chartEl.addEventListener('wheel', _onWheel, { passive: false, capture: true });

  function _ensurePriceScaleRange() {
    const active = _activeSeries();
    if (!active || typeof active.priceScale !== 'function') return null;
    const ps = active.priceScale();
    if (!ps || typeof ps.getVisibleRange !== 'function') return null;
    let range = ps.getVisibleRange();
    if (!range && typeof ps.setAutoScale === 'function') {
      ps.setAutoScale(true);
      if (typeof chart.timeScale === 'function') {
        chart.timeScale().fitContent();
      }
      range = ps.getVisibleRange();
    }
    return range;
  }

  function _attachPriceScaleCapture() {
    if (!chartEl || !candleSeries) return;
    const capture = document.createElement('div');
    capture.setAttribute('data-price-scale-capture', 'true');
    capture.style.position = 'absolute';
    capture.style.top = '0';
    capture.style.right = '0';
    capture.style.bottom = '0';
    capture.style.width = `${PRICE_AXIS_HIT_PX}px`;
    capture.style.cursor = 'ns-resize';
    capture.style.background = 'transparent';
    capture.style.zIndex = '20';
    capture.style.pointerEvents = 'auto';
    chartEl.appendChild(capture);

    let dragActive = false;
    let dragStartY = 0;
    let dragStartRange = null;
    let pendingDrag = false;
    let pendingDragY = 0;

    capture.addEventListener('wheel', (e) => {
      _onWheel(e);
    }, { passive: false });

    capture.addEventListener('mousedown', (e) => {
      const active = _activeSeries();
      if (!active) return;
      if (typeof active.priceScale !== 'function') return;
      const ps = active.priceScale();
      if (!ps || typeof ps.setAutoScale !== 'function' || typeof ps.setVisibleRange !== 'function') return;
      const range = _ensurePriceScaleRange();
      if (!range) {
        pendingDrag = true;
        pendingDragY = e.clientY;
        e.preventDefault();
        e.stopImmediatePropagation();
        requestAnimationFrame(() => {
          const retry = _ensurePriceScaleRange();
          if (!retry) return;
          const retrySeries = _activeSeries();
          if (!retrySeries || typeof retrySeries.priceScale !== 'function') return;
          const retryPs = retrySeries.priceScale();
          if (!retryPs || typeof retryPs.setAutoScale !== 'function' || typeof retryPs.setVisibleRange !== 'function') return;
          retryPs.setAutoScale(false);
          dragActive = true;
          dragStartY = pendingDragY;
          dragStartRange = retry;
          pendingDrag = false;
        });
        return;
      }
      ps.setAutoScale(false);
      dragActive = true;
      dragStartY = e.clientY;
      dragStartRange = range;
      e.preventDefault();
      e.stopImmediatePropagation();
    });

    window.addEventListener('mousemove', (e) => {
      if (!dragActive) return;
      const active = _activeSeries();
      if (!active) return;
      if (typeof active.priceScale !== 'function') return;
      const ps = active.priceScale();
      if (!ps || typeof ps.setVisibleRange !== 'function') return;
      if (!dragStartRange) return;
      const dy = e.clientY - dragStartY;
      const span = dragStartRange.to - dragStartRange.from;
      if (!Number.isFinite(span) || span <= 0) return;
      const k = 1 + (dy / 200);
      const newSpan = span * Math.max(0.2, Math.min(5, k));
      const mid = (dragStartRange.to + dragStartRange.from) / 2;
      const newFrom = mid - newSpan / 2;
      const newTo = mid + newSpan / 2;
      ps.setVisibleRange({ from: newFrom, to: newTo });
    });

    window.addEventListener('mouseup', () => {
      dragActive = false;
      dragStartRange = null;
      pendingDrag = false;
    });
  }

  _attachPriceScaleCapture();

  const cache = new Map();
  const lastUiBarTimeByKey = new Map();
  let barsRxTotal = 0;
  let lastWsMsgTs = 0;
  let lastBarUpdateMs = 0;
  let didFitOnce = false;
  let seriesDataReady = false;
  let initYRangeAttempted = false;
  let cachedYRange = null;
  let lastHealth = null;
  let lastAgeTickMs = Date.now();
  let wsAgeDisplayMs = null;
  let statusAgeDisplayMs = null;
  let lastWsMsgTsSeen = 0;
  let lastStatusTsSeen = 0;

  function uiKey(symbol, tf, mode) {
    return `${symbol}|${tf}|${mode}`;
  }

  function currentSymbol() {
    return String(symbolSelect.value || '').trim();
  }

  function currentTf() {
    return String(tfSelect.value || '').trim();
  }

  function currentMode() {
    return String(modeSelect.value || 'preview').trim();
  }

  function updateCurrent() {
    currentEl.textContent = `${currentSymbol() || '-'} / ${currentTf() || '-'} / ${currentMode()}`;
  }

  function applySnapshot(symbol, tf, mode, bars) {
    const tfSec = window.ChartAdapter.tfToSeconds(tf);
    const filled = window.ChartAdapter.insertWhitespace(bars, tfSec);
    if (candleSeries) {
      candleSeries.setData(filled);
      seriesDataReady = filled.length > 0;
      _ensureYRangeReady();
      if (typeof candleSeries.priceScale === 'function') {
        const ps = candleSeries.priceScale();
        if (ps && typeof ps.setAutoScale === 'function') {
          ps.setAutoScale(true);
          if (typeof ps.getVisibleRange === 'function') {
            const range = ps.getVisibleRange();
            if (!range && typeof ps.setVisibleRange === 'function') {
              ps.setVisibleRange({ from: 0, to: 1 });
              ps.setAutoScale(true);
            }
          }
        }
      }
    }
    const volumeData = bars
      .filter((bar) => bar && bar.time && Number.isFinite(bar.volume))
      .map((bar) => ({
        time: bar.time,
        value: Number(bar.volume),
        color: bar.close >= bar.open ? 'rgba(47,92,87,0.5)' : 'rgba(90,43,43,0.5)',
      }));
    if (volumeSeries) {
      volumeSeries.setData(volumeData);
    }
    if (barSeries) {
      barSeries.setData(filled);
    }
    if (filled.length > 0) {
      const last = filled[filled.length - 1];
      if (last && last.time) {
        lastUiBarTimeByKey.set(uiKey(symbol, tf, mode), last.time);
        lastBarUpdateMs = Number(last.time) * 1000;
      }
    }
    if (!didFitOnce && filled.length > 5) {
      if (!appliedTimeRange && pendingTimeRange && timeScale && typeof timeScale.setVisibleRange === 'function') {
        timeScale.setVisibleRange(pendingTimeRange);
        appliedTimeRange = true;
        pendingTimeRange = null;
        didFitOnce = true;
      } else if (timeScale && typeof timeScale.fitContent === 'function') {
        timeScale.fitContent();
        didFitOnce = true;
      }
    }
  }

  function applyUpdate(symbol, tf, mode, bar) {
    const keyId = uiKey(symbol, tf, mode);
    const lastTime = lastUiBarTimeByKey.get(keyId) || null;
    const tfSec = window.ChartAdapter.tfToSeconds(tf);
    const placeholders = window.ChartAdapter.gapPlaceholders(lastTime, bar.time, tfSec);
    if (candleSeries) {
      for (const blank of placeholders) {
        candleSeries.update(blank);
      }
      candleSeries.update(bar);
    }
    if (barSeries) {
      for (const blank of placeholders) {
        barSeries.update(blank);
      }
      barSeries.update(bar);
    }
    if (volumeSeries && Number.isFinite(bar.volume)) {
      volumeSeries.update({
        time: bar.time,
        value: Number(bar.volume),
        color: bar.close >= bar.open ? 'rgba(47,92,87,0.5)' : 'rgba(90,43,43,0.5)',
      });
    }
    seriesDataReady = true;
    const lastTimeSafe = lastTime ? Number(lastTime) : 0;
    lastUiBarTimeByKey.set(keyId, Math.max(lastTimeSafe, bar.time));
    lastBarUpdateMs = Number(bar.time) * 1000;
  }

  function sendSubscribe() {
    if (ws.readyState !== WebSocket.OPEN) return;
    const symbol = currentSymbol();
    const tf = currentTf();
    const mode = currentMode();
    if (!symbol || !tf) {
      statusEl.textContent = 'WS: потрібні symbol і tf';
      return;
    }
    const payload = {
      type: 'subscribe',
      symbol,
      tf,
      mode,
    };
    ws.send(JSON.stringify(payload));
    updateCurrent();
  }

  function onMessage(payload) {
    if (payload.type === 'command_ack') {
      const ok = payload.ok === true;
      const req = payload.req_id ? ` (${payload.req_id})` : '';
      if (ok) {
        _updateCommandStatus(`OK: команда прийнята${req}`);
      } else {
        _updateCommandStatus(`FAIL: ${payload.error || 'command_failed'}`);
      }
      return;
    }
    if (payload.type === 'health') {
      lastHealth = payload;
      const statusTs = Number(payload.status?.ts_ms || payload.status?.ts || 0);
      if (payload.status_ok === true && statusTs > 0) {
        if (statusTs !== lastStatusTsSeen) {
          statusAgeDisplayMs = Date.now() - statusTs;
          lastStatusTsSeen = statusTs;
        }
      } else {
        statusAgeDisplayMs = null;
        lastStatusTsSeen = 0;
      }
      _renderStatusBlock(payload.status || {}, payload);
      _renderTickBlock(payload.status || {});
      _renderUiBlock(payload.ui || {});
      _renderFinalBlock(payload.status || {});
      _renderCommandBlock(payload.status || {});
      _renderWsBlock();
      _updateOverlay(payload.status || {});
      return;
    }
    if (payload.type === 'snapshot') {
      const symbol = payload.symbol || currentSymbol();
      const tf = payload.tf || currentTf();
      const mode = payload.mode || currentMode();
      const bars = window.ChartAdapter.normalizeBars(payload.bars || []);
      cache.set(uiKey(symbol, tf, mode), bars.slice(-800));
      applySnapshot(symbol, tf, mode, bars);
      barsRxTotal += bars.length;
      if (bars.length > 0) {
        const last = bars[bars.length - 1];
        if (last && last.time) {
          lastBarUpdateMs = Number(last.time) * 1000;
        }
      }
      return;
    }
    if (payload.type === 'bar') {
      const symbol = payload.symbol || currentSymbol();
      const tf = payload.tf || currentTf();
      const mode = payload.mode || currentMode();
      const bar = window.ChartAdapter.normalizeBar(payload.bar);
      if (!bar) return;
      applyUpdate(symbol, tf, mode, bar);
      barsRxTotal += 1;
      return;
    }
  }

  ws = new WebSocket(`ws://${location.host}`);
  ws.onopen = () => { statusEl.textContent = 'WS: connected'; sendSubscribe(); };
  ws.onclose = () => { statusEl.textContent = 'WS: disconnected'; };
  ws.onerror = () => { statusEl.textContent = 'WS: error'; };
  ws.onmessage = (event) => {
    try {
      const payload = JSON.parse(event.data);
      lastWsMsgTs = Date.now();
      onMessage(payload);
    } catch {
      // ignore
    }
  };

  applySettings();
  if (seriesTypeSelect) {
    const useBar = seriesTypeSelect.value === 'bar';
    if (candleSeries && typeof candleSeries.applyOptions === 'function') {
      candleSeries.applyOptions({ visible: !useBar });
    }
    if (barSeries && typeof barSeries.applyOptions === 'function') {
      barSeries.applyOptions({ visible: useBar });
    }
  }

  symbolSelect.addEventListener('change', () => {
    lastTimeRange = null;
    pendingTimeRange = null;
    appliedTimeRange = false;
    saveSettings();
    cache.clear();
    lastUiBarTimeByKey.clear();
    if (candleSeries) {
      candleSeries.setData([]);
    }
    if (barSeries) {
      barSeries.setData([]);
    }
    sendSubscribe();
  });
  tfSelect.addEventListener('change', () => {
    lastTimeRange = null;
    pendingTimeRange = null;
    appliedTimeRange = false;
    saveSettings();
    cache.clear();
    lastUiBarTimeByKey.clear();
    if (candleSeries) {
      candleSeries.setData([]);
    }
    if (barSeries) {
      barSeries.setData([]);
    }
    sendSubscribe();
  });
  modeSelect.addEventListener('change', () => {
    lastTimeRange = null;
    pendingTimeRange = null;
    appliedTimeRange = false;
    saveSettings();
    cache.clear();
    lastUiBarTimeByKey.clear();
    if (candleSeries) {
      candleSeries.setData([]);
    }
    if (barSeries) {
      barSeries.setData([]);
    }
    sendSubscribe();
  });
  seriesTypeSelect.addEventListener('change', () => {
    saveSettings();
    const useBar = seriesTypeSelect.value === 'bar';
    if (candleSeries && typeof candleSeries.applyOptions === 'function') {
      candleSeries.applyOptions({ visible: !useBar });
    }
    if (barSeries && typeof barSeries.applyOptions === 'function') {
      barSeries.applyOptions({ visible: useBar });
    }
  });
  clearBtn.addEventListener('click', () => {
    cache.clear();
    lastUiBarTimeByKey.clear();
    lastTimeRange = null;
    pendingTimeRange = null;
    appliedTimeRange = false;
    if (candleSeries) {
      candleSeries.setData([]);
    }
    if (barSeries) {
      barSeries.setData([]);
    }
    if (volumeSeries) {
      volumeSeries.setData([]);
    }
    didFitOnce = false;
  });
  subscribeBtn.addEventListener('click', () => {
    saveSettings();
    sendSubscribe();
  });
  fitBtn.addEventListener('click', () => {
    if (typeof chart.timeScale === 'function') {
      chart.timeScale().fitContent();
    }
  });

  window.addEventListener('resize', () => {
    const width = chartEl.clientWidth;
    const height = chartEl.clientHeight;
    if (typeof chart.resize === 'function') {
      chart.resize(width, height);
    } else if (typeof chart.applyOptions === 'function') {
      chart.applyOptions({ width, height });
    }
  });

  setInterval(() => {
    const now = Date.now();
    const delta = Math.max(0, now - lastAgeTickMs);
    lastAgeTickMs = now;

    if (lastWsMsgTs > 0) {
      if (lastWsMsgTs !== lastWsMsgTsSeen) {
        wsAgeDisplayMs = now - lastWsMsgTs;
        lastWsMsgTsSeen = lastWsMsgTs;
      } else if (wsAgeDisplayMs !== null) {
        wsAgeDisplayMs += delta;
      } else {
        wsAgeDisplayMs = now - lastWsMsgTs;
      }
    } else {
      wsAgeDisplayMs = null;
      lastWsMsgTsSeen = 0;
    }

    if (lastHealth?.status_ok === true && lastStatusTsSeen > 0) {
      if (statusAgeDisplayMs !== null) {
        statusAgeDisplayMs += delta;
      }
    }
    if (lastWsMsgTs > 0) {
      wsAgeEl.textContent = String(_fmt(wsAgeDisplayMs));
    } else {
      wsAgeEl.textContent = '-';
    }
    barsRxEl.textContent = String(barsRxTotal);
    updateCurrent();
    if (lastHealth) {
      _renderWsBlock();
      _renderStatusBlock(lastHealth.status || {}, lastHealth);
      _renderFinalBlock(lastHealth.status || {});
      _renderCommandBlock(lastHealth.status || {});
      let statusBadge = 'OK';
      if (lastHealth.status_ok !== true) {
        statusBadge = 'N/A';
      } else if (lastHealth.status_stale === true) {
        statusBadge = 'STALE';
      }
      statusEl.textContent = `WS: ${wsAgeEl.textContent} ms | STATUS: ${statusBadge} | AGE: ${_fmt(statusAgeDisplayMs)} | DATA: ${lastBarUpdateMs > 0 && Date.now() - lastBarUpdateMs > 5000 ? 'STALE' : 'OK'}`;
    }
  }, 1000);
})();
