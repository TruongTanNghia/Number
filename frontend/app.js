/**
 * Lottery Limit Manager - Frontend Application
 * Supports 3 regions: XSMN (Miền Nam), XSMB (Miền Bắc), XSMT (Miền Trung)
 */

// ═══════════════════════════════════════════════════════════
// CONFIGURATION
// ═══════════════════════════════════════════════════════════

const API_BASE = '';
const REFRESH_INTERVAL = 5 * 60 * 1000; // 5 minutes
const POINT_VALUE = 23000;
const WIN_MULTIPLIER = 80;

const REGION_LABELS = {
    xsmn: 'Miền Nam',
    xsmb: 'Miền Bắc',
    xsmt: 'Miền Trung',
};

const REGION_ICONS = {
    xsmn: '🌴',
    xsmb: '🏯',
    xsmt: '⛩️',
};

// ═══════════════════════════════════════════════════════════
// STATE
// ═══════════════════════════════════════════════════════════

let appState = {
    currentRegion: 'xsmn',
    currentView: 'dashboard',
    limits: [],
    consecutive: [],
    profitStats: null,
    chartData: null,
    chartInstance: null,
    chartDays: 7,
    isLoading: false,
    connected: false,
    pricingConfig: { price_per_point: 75, cost_multiplier: 18 },
    predictions: null,
};

// ═══════════════════════════════════════════════════════════
// INITIALIZATION
// ═══════════════════════════════════════════════════════════

document.addEventListener('DOMContentLoaded', () => {
    console.log('🚀 Lottery Limit Manager starting (3 Miền)...');
    initializeApp();
});

async function initializeApp() {
    generateLoGrid();
    await loadAllData();
    setInterval(loadAllData, REFRESH_INTERVAL);

    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') closeModal();
    });
}

async function loadAllData() {
    const region = appState.currentRegion;
    try {
        appState.isLoading = true;
        updateStatus('loading', `Đang tải ${REGION_LABELS[region]}...`);

        const [limitsRes, consecutiveRes, profitRes, scrapeStatusRes] = await Promise.allSettled([
            fetchAPI(`/api/limits?region=${region}`),
            fetchAPI(`/api/consecutive?region=${region}`),
            fetchAPI(`/api/stats/profit?days=30&region=${region}`),
            fetchAPI('/api/scrape/status'),
        ]);

        // Process limits
        if (limitsRes.status === 'fulfilled' && limitsRes.value?.data) {
            appState.limits = limitsRes.value.data;
            if (limitsRes.value.config) {
                appState.pricingConfig = {
                    price_per_point: limitsRes.value.config.price_per_point || 75,
                    cost_multiplier: limitsRes.value.config.cost_multiplier || 18,
                };
                renderPricingInfo();
            }
            renderLoGrid(appState.limits);
        }

        // Process consecutive
        if (consecutiveRes.status === 'fulfilled' && consecutiveRes.value?.data) {
            appState.consecutive = consecutiveRes.value.data;
            renderConsecutiveList(appState.consecutive);
        }

        // Process profit stats
        if (profitRes.status === 'fulfilled' && profitRes.value?.data) {
            appState.profitStats = profitRes.value.data;
            renderProfitStats(appState.profitStats);
        }

        // Process scrape status
        if (scrapeStatusRes.status === 'fulfilled') {
            const scrapeData = scrapeStatusRes.value;
            const byRegion = scrapeData.by_region || {};
            
            // Update scraped count for current region
            const currentRegionData = byRegion[region];
            document.getElementById('scraped-days').textContent =
                currentRegionData ? currentRegionData.count + ' ngày' : '0';
            
            // Update tab badges
            for (const [rgn, info] of Object.entries(byRegion)) {
                const badge = document.getElementById(`tab-badge-${rgn}`);
                if (badge) {
                    badge.textContent = info.count > 0 ? info.count : '';
                }
            }
        }

        // Load chart
        await loadChartData(appState.chartDays);

        // Load recent results
        await loadRecentResults();

        appState.connected = true;
        appState.isLoading = false;

        updateStatus('connected', `${REGION_LABELS[region]} — Đã kết nối`);
        document.getElementById('last-update').textContent =
            new Date().toLocaleTimeString('vi-VN', { hour: '2-digit', minute: '2-digit' });

    } catch (err) {
        console.error('Failed to load data:', err);
        appState.connected = false;
        appState.isLoading = false;
        updateStatus('error', 'Lỗi kết nối');
    }
}

// ═══════════════════════════════════════════════════════════
// REGION SWITCHING
// ═══════════════════════════════════════════════════════════

function switchRegion(region) {
    if (region === appState.currentRegion && appState.connected) return;

    appState.currentRegion = region;

    document.querySelectorAll('.region-tab').forEach(tab => {
        tab.classList.toggle('active', tab.dataset.region === region);
    });

    document.getElementById('grid-region-label').textContent = REGION_LABELS[region];
    const predLabel = document.getElementById('pred-region-label');
    if (predLabel) predLabel.textContent = REGION_LABELS[region];

    const mainContent = document.querySelector('.main-content');
    mainContent.classList.add('region-switching');
    setTimeout(() => mainContent.classList.remove('region-switching'), 400);

    if (appState.currentView === 'dashboard') {
        loadAllData();
    } else {
        loadPredictions();
    }
}

function switchView(view) {
    if (view === appState.currentView) return;
    appState.currentView = view;

    document.querySelectorAll('.view-btn').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.view === view);
    });

    document.getElementById('view-dashboard').style.display = (view === 'dashboard') ? '' : 'none';
    document.getElementById('view-prediction').style.display = (view === 'prediction') ? '' : 'none';

    if (view === 'prediction' && !appState.predictions) {
        loadPredictions();
    }
}

// ═══════════════════════════════════════════════════════════
// API HELPERS
// ═══════════════════════════════════════════════════════════

async function fetchAPI(endpoint, options = {}) {
    const url = API_BASE + endpoint;
    const response = await fetch(url, {
        ...options,
        headers: {
            'Content-Type': 'application/json',
            ...options.headers,
        }
    });
    if (!response.ok) {
        throw new Error(`API Error: ${response.status} ${response.statusText}`);
    }
    return response.json();
}

// ═══════════════════════════════════════════════════════════
// LÔ GRID
// ═══════════════════════════════════════════════════════════

function generateLoGrid() {
    const grid = document.getElementById('lo-grid');
    grid.innerHTML = '';

    for (let i = 0; i < 100; i++) {
        const lo = String(i).padStart(2, '0');
        const cell = document.createElement('div');
        cell.className = 'lo-cell';
        cell.id = `lo-${lo}`;
        cell.dataset.lo = lo;
        cell.dataset.limit = '200';
        cell.onclick = () => openLoDetail(lo);

        cell.innerHTML = `
            <span class="lo-number">${lo}</span>
            <span class="lo-limit">200đ</span>
            <span class="lo-days"></span>
        `;

        grid.appendChild(cell);
    }
}

function renderLoGrid(limitsData) {
    if (!limitsData || limitsData.length === 0) return;

    limitsData.forEach(item => {
        const cell = document.getElementById(`lo-${item.lo_number}`);
        if (!cell) return;

        const limit = item.current_limit;
        const days = item.days_since_last;

        cell.dataset.limit = String(limit);
        cell.querySelector('.lo-number').textContent = item.lo_number;
        cell.querySelector('.lo-limit').textContent = `${limit}đ`;
        cell.title = `Lô ${item.lo_number} • ${limit} điểm\nXác cược: ${formatVND(item.bet_cost_vnd)}\nTrúng 1 lần: ${formatVND(item.win_per_hit_vnd)}`;

        const daysEl = cell.querySelector('.lo-days');
        if (days === 0) {
            daysEl.textContent = 'mới về';
        } else {
            daysEl.textContent = `${days}d`;
        }

        cell.classList.remove('consecutive', 'hot-streak', 'just-hit');
        if (item.category === 'hot_streak') {
            cell.classList.add('hot-streak');
        } else if (item.category === 'consecutive') {
            cell.classList.add('consecutive');
        }
    });
}

function renderPricingInfo() {
    const el = document.getElementById('pricing-info');
    if (!el) return;
    const { price_per_point, cost_multiplier } = appState.pricingConfig;
    const region = appState.currentRegion;
    const regionLabel = REGION_LABELS[region];
    const costPerPoint = cost_multiplier * price_per_point;

    el.innerHTML = `
        <div class="pricing-row">
            <span class="pricing-label">Khu vực</span>
            <span class="pricing-value">${regionLabel}</span>
        </div>
        <div class="pricing-row">
            <span class="pricing-label">Xác cược / điểm</span>
            <span class="pricing-value">
                ${cost_multiplier} × ${price_per_point}đ
                = <strong>${costPerPoint.toLocaleString('vi-VN')}đ</strong>
            </span>
        </div>
        <div class="pricing-row">
            <span class="pricing-label">Trúng cược / điểm / lần</span>
            <span class="pricing-value pricing-win"><strong>${price_per_point}đ</strong></span>
        </div>
        <div class="pricing-row pricing-formula">
            <span>VD: 100 điểm</span>
            <span>
                Cược <strong>${(100 * costPerPoint).toLocaleString('vi-VN')}đ</strong>
                — Trúng/lần <strong class="pricing-win">${(100 * price_per_point).toLocaleString('vi-VN')}đ</strong>
            </span>
        </div>
    `;
}

// ═══════════════════════════════════════════════════════════
// CONSECUTIVE LIST
// ═══════════════════════════════════════════════════════════

function renderConsecutiveList(data) {
    const list = document.getElementById('consecutive-list');
    const countBadge = document.getElementById('consecutive-count');

    countBadge.textContent = data.length;

    if (data.length === 0) {
        list.innerHTML = '<div class="empty-state">Không có lô nào về liên tiếp</div>';
        return;
    }

    list.innerHTML = data.map(item => `
        <div class="consecutive-item" onclick="openLoDetail('${item.lo_number}')">
            <span class="ci-lo">${item.lo_number}</span>
            <span class="ci-streak">
                <span class="fire">${'🔥'.repeat(Math.min(item.consecutive_days, 4))}</span>
                ${item.consecutive_days} ngày
            </span>
            <span class="ci-limit">${item.current_limit}đ</span>
        </div>
    `).join('');
}

// ═══════════════════════════════════════════════════════════
// PROFIT STATS
// ═══════════════════════════════════════════════════════════

function renderProfitStats(stats) {
    if (!stats) return;

    const profitEl = document.getElementById('total-profit-value');
    const winEl = document.getElementById('total-win-value');
    const lossEl = document.getElementById('total-loss-value');
    const rateEl = document.getElementById('win-rate-value');
    const profitCard = document.getElementById('stat-total-profit');

    profitEl.textContent = formatVND(stats.net_profit_vnd);
    winEl.textContent = formatVND(stats.total_win_vnd);
    lossEl.textContent = formatVND(-stats.total_loss_vnd);
    rateEl.textContent = stats.win_rate.toFixed(1) + '%';

    if (stats.net_profit_vnd < 0) {
        profitCard.classList.add('negative');
    } else {
        profitCard.classList.remove('negative');
    }
}

// ═══════════════════════════════════════════════════════════
// CHART
// ═══════════════════════════════════════════════════════════

async function loadChartData(days) {
    const region = appState.currentRegion;
    try {
        const data = await fetchAPI(`/api/stats/profit/chart?days=${days}&region=${region}`);
        if (data?.data) {
            appState.chartData = data.data;
            renderChart(data.data);
        }
    } catch (err) {
        console.error('Chart data error:', err);
    }
}

function renderChart(chartData) {
    const ctx = document.getElementById('profit-chart');
    if (!ctx) return;

    if (appState.chartInstance) {
        appState.chartInstance.destroy();
    }

    appState.chartInstance = new Chart(ctx, {
        type: 'bar',
        data: {
            labels: chartData.labels,
            datasets: [
                {
                    label: 'Thu',
                    data: chartData.datasets.wins.map(v => v / 1000000),
                    backgroundColor: 'rgba(16, 185, 129, 0.5)',
                    borderColor: 'rgba(16, 185, 129, 0.8)',
                    borderWidth: 1,
                    borderRadius: 3,
                    order: 2,
                },
                {
                    label: 'Bù',
                    data: chartData.datasets.losses.map(v => v / 1000000),
                    backgroundColor: 'rgba(239, 68, 68, 0.5)',
                    borderColor: 'rgba(239, 68, 68, 0.8)',
                    borderWidth: 1,
                    borderRadius: 3,
                    order: 3,
                },
                {
                    label: 'Lũy kế',
                    data: chartData.datasets.cumulative.map(v => v / 1000000),
                    type: 'line',
                    borderColor: '#60a5fa',
                    backgroundColor: 'rgba(96, 165, 250, 0.1)',
                    borderWidth: 2,
                    pointRadius: 2,
                    pointHoverRadius: 5,
                    fill: true,
                    tension: 0.3,
                    order: 1,
                },
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: { mode: 'index', intersect: false },
            plugins: {
                legend: {
                    display: true, position: 'top',
                    labels: {
                        color: '#94a3b8', font: { family: 'Inter', size: 11 },
                        boxWidth: 12, boxHeight: 12, padding: 12, usePointStyle: true,
                    }
                },
                tooltip: {
                    backgroundColor: 'rgba(17, 24, 39, 0.95)',
                    borderColor: 'rgba(255, 255, 255, 0.1)', borderWidth: 1,
                    titleFont: { family: 'Inter', size: 12 },
                    bodyFont: { family: 'JetBrains Mono', size: 11 },
                    padding: 12,
                    callbacks: {
                        label: function(context) {
                            const value = context.parsed.y;
                            return `${context.dataset.label}: ${value >= 0 ? '+' : ''}${value.toFixed(1)}M`;
                        }
                    }
                }
            },
            scales: {
                x: {
                    grid: { color: 'rgba(255,255,255,0.03)' },
                    ticks: { color: '#64748b', font: { family: 'JetBrains Mono', size: 10 }, maxRotation: 45 }
                },
                y: {
                    grid: { color: 'rgba(255,255,255,0.03)' },
                    ticks: { color: '#64748b', font: { family: 'JetBrains Mono', size: 10 }, callback: (v) => v + 'M' }
                }
            }
        }
    });
}

function changeChartDays(days) {
    appState.chartDays = days;
    document.querySelectorAll('.panel--chart .btn-sm').forEach(btn => {
        btn.classList.toggle('active', parseInt(btn.dataset.days) === days);
    });
    loadChartData(days);
}

// ═══════════════════════════════════════════════════════════
// RECENT RESULTS
// ═══════════════════════════════════════════════════════════

async function loadRecentResults() {
    const region = appState.currentRegion;
    try {
        const data = await fetchAPI(`/api/results/lo-daily?days=7&region=${region}`);
        if (data?.data) {
            renderRecentResults(data.data);
        }
    } catch (err) {
        console.error('Recent results error:', err);
    }
}

function renderRecentResults(data) {
    const list = document.getElementById('recent-list');

    if (!data || data.length === 0) {
        list.innerHTML = '<div class="empty-state">Chưa có dữ liệu. Nhấn "Cập nhật" để crawl.</div>';
        return;
    }

    const byDate = {};
    data.forEach(item => {
        if (!byDate[item.date]) byDate[item.date] = [];
        byDate[item.date].push(item);
    });

    const dates = Object.keys(byDate).sort().reverse().slice(0, 5);

    list.innerHTML = dates.map(date => {
        const los = byDate[date].sort((a, b) => a.lo_number.localeCompare(b.lo_number));
        const displayDate = formatDateDisplay(date);
        return `
            <div class="recent-date-group">
                <div class="recent-date-label">${displayDate}</div>
                <div class="recent-lo-list">
                    ${los.map(lo => `
                        <span class="recent-lo-tag ${lo.count > 1 ? 'highlight' : ''}" 
                              title="${lo.lo_number}: ${lo.count} lần"
                              onclick="openLoDetail('${lo.lo_number}')">
                            ${lo.lo_number}${lo.count > 1 ? `×${lo.count}` : ''}
                        </span>
                    `).join('')}
                </div>
            </div>
        `;
    }).join('');
}

// ═══════════════════════════════════════════════════════════
// LÔ DETAIL MODAL
// ═══════════════════════════════════════════════════════════

async function openLoDetail(loNumber) {
    const region = appState.currentRegion;
    const overlay = document.getElementById('modal-overlay');
    const title = document.getElementById('modal-title');
    const body = document.getElementById('modal-body');

    title.textContent = `Lô ${loNumber} — ${REGION_LABELS[region]}`;
    body.innerHTML = '<div class="empty-state">Đang tải...</div>';
    overlay.classList.add('open');

    try {
        const data = await fetchAPI(`/api/limits/${loNumber}?region=${region}`);
        const info = data.data;

        const limitColor = getLimitColor(info.current_limit);
        const categoryEmoji = getCategoryEmoji(info.consecutive_days, info.days_since_last);

        const { price_per_point, cost_multiplier } = appState.pricingConfig;
        const limit = info.current_limit;
        const betCost = limit * cost_multiplier * price_per_point;
        const winPerHit = limit * price_per_point;

        body.innerHTML = `
            <div class="modal-stat-grid">
                <div class="modal-stat">
                    <div class="modal-stat-label">Hạn mức hiện tại</div>
                    <div class="modal-stat-value" style="color: ${limitColor}">${limit} điểm</div>
                </div>
                <div class="modal-stat">
                    <div class="modal-stat-label">Ngày chưa về</div>
                    <div class="modal-stat-value">${info.days_since_last}</div>
                </div>
                <div class="modal-stat">
                    <div class="modal-stat-label">Liên tiếp</div>
                    <div class="modal-stat-value">${info.consecutive_days > 0 ? info.consecutive_days + ' ngày' : '—'}</div>
                </div>
                <div class="modal-stat">
                    <div class="modal-stat-label">Trạng thái</div>
                    <div class="modal-stat-value">${categoryEmoji}</div>
                </div>
            </div>

            <div class="modal-section-title">💵 Tính tiền nếu đánh ${limit} điểm</div>
            <div class="modal-stat-grid">
                <div class="modal-stat" style="border-color: rgba(239, 68, 68, 0.25);">
                    <div class="modal-stat-label">Xác cược (chi phí)</div>
                    <div class="modal-stat-value" style="color: #ef4444; font-size: 1rem;">
                        ${betCost.toLocaleString('vi-VN')}đ
                    </div>
                    <div class="modal-stat-label" style="margin-top: 4px;">
                        ${limit} × ${cost_multiplier} × ${price_per_point}
                    </div>
                </div>
                <div class="modal-stat" style="border-color: rgba(16, 185, 129, 0.25);">
                    <div class="modal-stat-label">Trúng / mỗi lần lô về</div>
                    <div class="modal-stat-value" style="color: #10b981; font-size: 1rem;">
                        +${winPerHit.toLocaleString('vi-VN')}đ
                    </div>
                    <div class="modal-stat-label" style="margin-top: 4px;">
                        ${limit} × ${price_per_point}
                    </div>
                </div>
            </div>

            <div class="modal-stat" style="margin-bottom: 16px;">
                <div class="modal-stat-label">Lần cuối về</div>
                <div class="modal-stat-value" style="font-size: 0.95rem;">
                    ${info.last_appeared_date ? formatDateDisplay(info.last_appeared_date) : 'Chưa có dữ liệu'}
                </div>
            </div>

            ${info.history && info.history.length > 0 ? `
                <div class="modal-section-title">📅 Lịch sử xuất hiện (30 ngày)</div>
                ${info.history.slice(0, 15).map(h => `
                    <div class="modal-history-row">
                        <span class="date">${formatDateDisplay(h.date)}</span>
                        <span class="count hit">✅ ${h.count} lần — +${(limit * price_per_point * h.count).toLocaleString('vi-VN')}đ</span>
                    </div>
                `).join('')}
            ` : '<div class="empty-state">Chưa có lịch sử</div>'}
        `;
    } catch (err) {
        body.innerHTML = `<div class="empty-state">Lỗi tải dữ liệu: ${err.message}</div>`;
    }
}

function closeModal() {
    document.getElementById('modal-overlay').classList.remove('open');
}

// ═══════════════════════════════════════════════════════════
// SCRAPING
// ═══════════════════════════════════════════════════════════

async function triggerScrape() {
    const btn = document.getElementById('btn-scrape');
    btn.classList.add('loading');
    btn.disabled = true;

    const scrapeOverlay = document.getElementById('scrape-overlay');
    scrapeOverlay.style.display = 'flex';

    const progressBar = document.getElementById('scrape-progress');
    const statusText = document.getElementById('scrape-status-text');

    try {
        statusText.textContent = 'Đang crawl dữ liệu 3 miền (30 ngày)...';
        progressBar.style.width = '5%';

        // Scrape all 3 regions
        await fetchAPI('/api/scrape/all?days=30', { method: 'POST' });

        // Simulate progress
        let progress = 5;
        const progressInterval = setInterval(() => {
            progress = Math.min(progress + 2, 90);
            progressBar.style.width = progress + '%';
            
            // Update region status indicators
            if (progress > 20) document.getElementById('scrape-dot-xsmn').textContent = '✅';
            if (progress > 50) document.getElementById('scrape-dot-xsmb').textContent = '✅';
            if (progress > 75) document.getElementById('scrape-dot-xsmt').textContent = '✅';
        }, 1000);

        statusText.textContent = 'Đang xử lý 3 miền... vui lòng đợi';

        // Wait for completion (3 regions × ~30 days × 1.5s delay ≈ 135s, but cached dates skip)
        await new Promise(resolve => setTimeout(resolve, 60000));

        clearInterval(progressInterval);
        progressBar.style.width = '100%';
        
        // Mark all regions done
        document.getElementById('scrape-dot-xsmn').textContent = '✅';
        document.getElementById('scrape-dot-xsmb').textContent = '✅';
        document.getElementById('scrape-dot-xsmt').textContent = '✅';
        
        statusText.textContent = 'Hoàn tất! Đang tải lại dữ liệu...';
        await new Promise(resolve => setTimeout(resolve, 1500));

        await loadAllData();
        showToast('success', '✅ Dữ liệu 3 miền đã được cập nhật!');

    } catch (err) {
        showToast('error', '❌ Lỗi: ' + err.message);
    } finally {
        btn.classList.remove('loading');
        btn.disabled = false;
        scrapeOverlay.style.display = 'none';
        
        // Reset dots
        document.getElementById('scrape-dot-xsmn').textContent = '⏳';
        document.getElementById('scrape-dot-xsmb').textContent = '⏳';
        document.getElementById('scrape-dot-xsmt').textContent = '⏳';
    }
}

// ═══════════════════════════════════════════════════════════
// STATUS & NOTIFICATIONS
// ═══════════════════════════════════════════════════════════

function updateStatus(state, text) {
    const statusDot = document.querySelector('.status-dot');
    const statusText = document.getElementById('status-text');

    statusText.textContent = text;
    statusDot.classList.remove('connected');

    if (state === 'connected') {
        statusDot.classList.add('connected');
    }
}

function showToast(type, message) {
    const container = document.getElementById('toast-container');
    const icons = { success: '✅', error: '❌', info: 'ℹ️' };

    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    toast.innerHTML = `
        <span class="toast-icon">${icons[type] || 'ℹ️'}</span>
        <span>${message}</span>
    `;

    container.appendChild(toast);
    setTimeout(() => {
        toast.style.animation = 'toastSlideIn 300ms ease reverse';
        setTimeout(() => toast.remove(), 300);
    }, 5000);
}

// ═══════════════════════════════════════════════════════════
// UTILITIES
// ═══════════════════════════════════════════════════════════

function formatVND(amount) {
    if (amount === 0 || amount === undefined || amount === null) return '0đ';
    const absAmount = Math.abs(amount);
    const sign = amount >= 0 ? '+' : '-';
    if (absAmount >= 1000000) {
        return `${sign}${(absAmount / 1000000).toFixed(1)}M`;
    } else if (absAmount >= 1000) {
        return `${sign}${(absAmount / 1000).toFixed(0)}K`;
    }
    return `${sign}${absAmount.toLocaleString('vi-VN')}đ`;
}

function formatDateDisplay(dateStr) {
    if (!dateStr) return '—';
    const date = new Date(dateStr + 'T00:00:00');
    const days = ['CN', 'T2', 'T3', 'T4', 'T5', 'T6', 'T7'];
    const dayName = days[date.getDay()];
    return `${dayName} ${date.getDate()}/${date.getMonth() + 1}`;
}

function getLimitColor(limit) {
    if (limit >= 200) return '#10b981';
    if (limit >= 150) return '#34d399';
    if (limit >= 100) return '#facc15';
    if (limit >= 50) return '#fb923c';
    if (limit >= 20) return '#ef4444';
    return '#fca5a5';
}

function getCategoryEmoji(consecutive, daysSince) {
    if (consecutive >= 4) return '🔥🔥🔥🔥 Hot!';
    if (consecutive >= 3) return '🔥🔥🔥 Nóng';
    if (consecutive >= 2) return '🔥🔥 Liên tiếp';
    if (daysSince === 0) return '✅ Mới về';
    if (daysSince <= 3) return '🟢 Gần đây';
    if (daysSince <= 7) return '🟡 Đang nguội';
    return '🔴 Lâu rồi';
}

// ═══════════════════════════════════════════════════════════
// PREDICTION PAGE
// ═══════════════════════════════════════════════════════════

async function loadPredictions() {
    const region = appState.currentRegion;
    const windowSel = document.getElementById('pred-window');
    const windowDays = windowSel ? parseInt(windowSel.value) : 60;

    const topList = document.getElementById('pred-top-list');
    if (topList) topList.innerHTML = '<div class="empty-state">Đang tính toán...</div>';

    try {
        const data = await fetchAPI(`/api/predict?region=${region}&window=${windowDays}`);
        appState.predictions = data;
        renderPredictions(data);
    } catch (err) {
        if (topList) topList.innerHTML = `<div class="empty-state">Lỗi: ${err.message}</div>`;
    }
}

function renderPredictions(data) {
    if (!data || !data.predictions) return;

    const preds = data.predictions;

    document.getElementById('pred-days').textContent = `${data.days_available} ngày`;
    document.getElementById('pred-top-lo').textContent = preds[0] ? preds[0].lo_number : '--';
    document.getElementById('pred-top-lift').textContent = data.top_lift ? `${data.top_lift}×` : '--';

    const avgConf = preds.reduce((s, p) => s + p.confidence, 0) / preds.length;
    document.getElementById('pred-avg-conf').textContent = `${avgConf.toFixed(1)}%`;

    document.getElementById('pred-region-label').textContent = REGION_LABELS[appState.currentRegion];

    renderPredTopList(preds.slice(0, 20));
    renderPredModels(data.model_weights);
    renderPredHeatmap(preds);
    renderPredTable(preds);
}

function renderPredTopList(top20) {
    const el = document.getElementById('pred-top-list');
    if (!el) return;

    const maxProb = Math.max(...top20.map(p => p.probability));

    el.innerHTML = top20.map(p => {
        const barW = (p.probability / maxProb) * 100;
        let rankClass = '';
        if (p.rank === 1) rankClass = 'gold';
        else if (p.rank === 2) rankClass = 'silver';
        else if (p.rank === 3) rankClass = 'bronze';

        return `
            <div class="pred-card">
                <div class="pred-rank ${rankClass}">#${p.rank}</div>
                <div class="pred-info">
                    <div class="pred-lo-num">${p.lo_number}</div>
                    <div class="pred-bar-wrap">
                        <div class="pred-bar" style="width: ${barW}%"></div>
                    </div>
                </div>
                <div class="pred-stats-line">
                    <div class="pred-prob">${p.probability.toFixed(2)}%</div>
                    <div class="pred-conf">conf ${p.confidence}%</div>
                </div>
            </div>
        `;
    }).join('');
}

function renderPredModels(weights) {
    const el = document.getElementById('pred-models');
    if (!el || !weights) return;

    const labels = {
        frequency:   'Frequency',
        recency:     'Recency',
        poisson:     'Poisson Gap',
        markov:      'Markov',
        temperature: 'Temperature',
        pair:        'Pair',
        streak:      'Streak',
    };

    const max = Math.max(...Object.values(weights));

    el.innerHTML = Object.entries(weights).map(([k, w]) => {
        const pct = (w / max) * 100;
        return `
            <div class="pred-model-row">
                <span class="model-name">${labels[k] || k}</span>
                <div class="model-bar-wrap">
                    <div class="model-bar" style="width: ${pct}%"></div>
                </div>
                <span class="model-weight">${(w * 100).toFixed(0)}%</span>
            </div>
        `;
    }).join('');
}

function renderPredHeatmap(preds) {
    const el = document.getElementById('pred-heatmap');
    if (!el) return;

    const byLo = {};
    preds.forEach(p => byLo[p.lo_number] = p);

    const probs = preds.map(p => p.probability);
    const maxProb = Math.max(...probs);

    let html = '';
    for (let i = 0; i < 100; i++) {
        const lo = String(i).padStart(2, '0');
        const p = byLo[lo];
        if (!p) continue;
        const intensity = Math.min(1, p.probability / maxProb);
        html += `
            <div class="pred-heat-cell" title="Lô ${lo} • ${p.probability.toFixed(2)}% • Rank #${p.rank}">
                <div class="ph-fill" style="opacity: ${intensity.toFixed(3)};"></div>
                <span class="ph-num">${lo}</span>
                <span class="ph-prob">${p.probability.toFixed(1)}%</span>
            </div>
        `;
    }
    el.innerHTML = html;
}

function renderPredTable(preds) {
    const el = document.getElementById('pred-table-body');
    if (!el) return;

    el.innerHTML = preds.map(p => {
        const b = p.breakdown;
        const fmt = (v) => (v * 100).toFixed(1);
        return `
            <tr>
                <td class="rank-col">#${p.rank}</td>
                <td class="lo-col">${p.lo_number}</td>
                <td class="prob-col">${p.probability.toFixed(3)}%</td>
                <td>${p.composite_score.toFixed(3)}</td>
                <td>${p.confidence}%</td>
                <td>${fmt(b.frequency)}</td>
                <td>${fmt(b.recency)}</td>
                <td>${fmt(b.poisson)}</td>
                <td>${fmt(b.markov)}</td>
                <td>${fmt(b.temperature)}</td>
                <td>${fmt(b.pair)}</td>
                <td>${fmt(b.streak)}</td>
            </tr>
        `;
    }).join('');
}
