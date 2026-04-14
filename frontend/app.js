/**
 * XSMN Limit Manager - Frontend Application
 * 
 * Handles all dashboard interactions, API calls, chart rendering,
 * and real-time data display for the lottery limit management system.
 */

// ═══════════════════════════════════════════════════════════
// CONFIGURATION
// ═══════════════════════════════════════════════════════════

const API_BASE = '';  // Same origin
const REFRESH_INTERVAL = 5 * 60 * 1000; // 5 minutes
const POINT_VALUE = 23000;
const WIN_MULTIPLIER = 80;

// ═══════════════════════════════════════════════════════════
// STATE
// ═══════════════════════════════════════════════════════════

let appState = {
    limits: [],
    consecutive: [],
    profitStats: null,
    chartData: null,
    chartInstance: null,
    chartDays: 7,
    isLoading: false,
    connected: false,
};

// ═══════════════════════════════════════════════════════════
// INITIALIZATION
// ═══════════════════════════════════════════════════════════

document.addEventListener('DOMContentLoaded', () => {
    console.log('🚀 XSMN Limit Manager starting...');
    initializeApp();
});

async function initializeApp() {
    // Generate the grid first (static structure)
    generateLoGrid();
    
    // Load data
    await loadAllData();
    
    // Set up auto-refresh
    setInterval(loadAllData, REFRESH_INTERVAL);
    
    // Keyboard shortcuts
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') closeModal();
    });
}

async function loadAllData() {
    try {
        appState.isLoading = true;
        updateStatus('loading', 'Đang tải dữ liệu...');
        
        // Parallel API calls
        const [limitsRes, consecutiveRes, profitRes, scrapeStatusRes] = await Promise.allSettled([
            fetchAPI('/api/limits'),
            fetchAPI('/api/consecutive'),
            fetchAPI('/api/stats/profit?days=30'),
            fetchAPI('/api/scrape/status'),
        ]);
        
        // Process limits
        if (limitsRes.status === 'fulfilled' && limitsRes.value?.data) {
            appState.limits = limitsRes.value.data;
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
            document.getElementById('scraped-days').textContent = 
                scrapeData.total_days + ' ngày';
        }
        
        // Load chart
        await loadChartData(appState.chartDays);
        
        // Load recent results
        await loadRecentResults();
        
        appState.connected = true;
        appState.isLoading = false;
        
        updateStatus('connected', 'Đã kết nối');
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
        const consec = item.consecutive_days;
        
        // Update data
        cell.dataset.limit = String(limit);
        
        // Update display
        cell.querySelector('.lo-number').textContent = item.lo_number;
        cell.querySelector('.lo-limit').textContent = `${limit}đ`;
        
        // Day info
        const daysEl = cell.querySelector('.lo-days');
        if (days === 0) {
            daysEl.textContent = 'mới về';
        } else {
            daysEl.textContent = `${days}d`;
        }
        
        // Remove all category classes 
        cell.classList.remove('consecutive', 'hot-streak', 'just-hit');
        
        // Add category class
        if (item.category === 'hot_streak') {
            cell.classList.add('hot-streak');
        } else if (item.category === 'consecutive') {
            cell.classList.add('consecutive');
        }
    });
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
    
    // Profit card color
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
    try {
        const data = await fetchAPI(`/api/stats/profit/chart?days=${days}`);
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
    
    // Destroy existing chart
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
            interaction: {
                mode: 'index',
                intersect: false,
            },
            plugins: {
                legend: {
                    display: true,
                    position: 'top',
                    labels: {
                        color: '#94a3b8',
                        font: { family: 'Inter', size: 11 },
                        boxWidth: 12,
                        boxHeight: 12,
                        padding: 12,
                        usePointStyle: true,
                    }
                },
                tooltip: {
                    backgroundColor: 'rgba(17, 24, 39, 0.95)',
                    borderColor: 'rgba(255, 255, 255, 0.1)',
                    borderWidth: 1,
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
                    ticks: {
                        color: '#64748b',
                        font: { family: 'JetBrains Mono', size: 10 },
                        maxRotation: 45,
                    }
                },
                y: {
                    grid: { color: 'rgba(255,255,255,0.03)' },
                    ticks: {
                        color: '#64748b',
                        font: { family: 'JetBrains Mono', size: 10 },
                        callback: (v) => v + 'M',
                    }
                }
            }
        }
    });
}

function changeChartDays(days) {
    appState.chartDays = days;
    
    // Update button states
    document.querySelectorAll('.panel--chart .btn-sm').forEach(btn => {
        btn.classList.toggle('active', parseInt(btn.dataset.days) === days);
    });
    
    loadChartData(days);
}

// ═══════════════════════════════════════════════════════════
// RECENT RESULTS
// ═══════════════════════════════════════════════════════════

async function loadRecentResults() {
    try {
        const data = await fetchAPI('/api/results/lo-daily?days=7');
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
    
    // Group by date
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
    const overlay = document.getElementById('modal-overlay');
    const title = document.getElementById('modal-title');
    const body = document.getElementById('modal-body');
    
    title.textContent = `Lô ${loNumber}`;
    body.innerHTML = '<div class="empty-state">Đang tải...</div>';
    overlay.classList.add('open');
    
    try {
        const data = await fetchAPI(`/api/limits/${loNumber}`);
        const info = data.data;
        
        const limitColor = getLimitColor(info.current_limit);
        const categoryEmoji = getCategoryEmoji(info.consecutive_days, info.days_since_last);
        
        body.innerHTML = `
            <div class="modal-stat-grid">
                <div class="modal-stat">
                    <div class="modal-stat-label">Hạn mức hiện tại</div>
                    <div class="modal-stat-value" style="color: ${limitColor}">${info.current_limit}đ</div>
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
                        <span class="count hit">✅ ${h.count} lần</span>
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
        // Start scraping
        statusText.textContent = 'Đang crawl dữ liệu 30 ngày...';
        progressBar.style.width = '10%';
        
        await fetchAPI('/api/scrape/range?days=30', { method: 'POST' });
        
        // Simulate progress
        let progress = 10;
        const progressInterval = setInterval(() => {
            progress = Math.min(progress + 3, 90);
            progressBar.style.width = progress + '%';
        }, 1000);
        
        // Poll for completion
        statusText.textContent = 'Đang xử lý... vui lòng đợi';
        
        // Wait and then refresh
        await new Promise(resolve => setTimeout(resolve, 45000));
        
        clearInterval(progressInterval);
        progressBar.style.width = '100%';
        statusText.textContent = 'Hoàn tất! Đang tải lại dữ liệu...';
        
        await new Promise(resolve => setTimeout(resolve, 1500));
        
        // Reload data
        await loadAllData();
        
        showToast('success', '✅ Dữ liệu đã được cập nhật!');
        
    } catch (err) {
        showToast('error', '❌ Lỗi: ' + err.message);
    } finally {
        btn.classList.remove('loading');
        btn.disabled = false;
        scrapeOverlay.style.display = 'none';
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
    
    // Auto-remove after 5s
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
