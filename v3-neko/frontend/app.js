/* ============================================================
   Wave Surf — Frontend Shell Logic
   Manages: address bar, navigation, AI panel, bookmarks, history
   Connects to Neko WebRTC viewer + CDP API backend
   ============================================================ */

const API_BASE = window.location.origin + '/api';
const WAVE_SEARCH_URL = 'https://wave-search-production.up.railway.app';
const NEKO_VIEWER_URL = window.location.origin + '/neko/?usr=wave&pwd=neko&u=wave&p=neko&embed=1&show_side=0&volume=0';

// DOM elements
const urlInput = document.getElementById('url-input');
const goBtn = document.getElementById('go-btn');
const backBtn = document.getElementById('back-btn');
const forwardBtn = document.getElementById('forward-btn');
const reloadBtn = document.getElementById('reload-btn');
const homeBtn = document.getElementById('home-btn');
const askAiBtn = document.getElementById('ask-ai-btn');
const aiPanel = document.getElementById('ai-panel');
const aiCloseBtn = document.getElementById('ai-close-btn');
const aiInput = document.getElementById('ai-input');
const aiSendBtn = document.getElementById('ai-send-btn');
const aiMessages = document.getElementById('ai-messages');
const bookmarksBtn = document.getElementById('bookmarks-btn');
const bookmarksPanel = document.getElementById('bookmarks-panel');
const bookmarksCloseBtn = document.getElementById('bookmarks-close-btn');
const bookmarksList = document.getElementById('bookmarks-list');
const historyBtn = document.getElementById('history-btn');
const historyPanel = document.getElementById('history-panel');
const historyCloseBtn = document.getElementById('history-close-btn');
const historyList = document.getElementById('history-list');
const screenshotBtn = document.getElementById('screenshot-btn');
const fullscreenBtn = document.getElementById('fullscreen-btn');
const nekoViewer = document.getElementById('neko-viewer');
const statusText = document.getElementById('status-text');
const statusUrl = document.getElementById('status-url');
const connectionStatus = document.getElementById('connection-status');
const fpsCounter = document.getElementById('fps-counter');

// ===== Initialize =====

function init() {
    // Load Neko viewer
    nekoViewer.src = NEKO_VIEWER_URL;
    
    // Set home page to Wave Search
    urlInput.value = WAVE_SEARCH_URL;
    
    // Load bookmarks and history from localStorage
    loadBookmarks();
    loadHistory();
    
    // Bind events
    bindEvents();
    
    // Check connection status
    checkConnection();
    setInterval(checkConnection, 5000);
    
    statusText.textContent = 'Ready';
}

// ===== Navigation =====

async function navigateTo(query) {
    if (!query) return;
    
    let url = query.trim();
    
    // If it looks like a URL, navigate directly
    if (url.match(/^https?:\/\//) || url.match(/^www\./)) {
        if (!url.match(/^https?:\/\//)) {
            url = 'https://' + url;
        }
    } else if (url.includes('.') && !url.includes(' ')) {
        // Likely a domain (e.g. "example.com")
        url = 'https://' + url;
    } else {
        // Search query — use Wave Search
        url = WAVE_SEARCH_URL + '/search?q=' + encodeURIComponent(url) + '&format=html';
    }
    
    statusText.textContent = 'Navigating...';
    statusUrl.textContent = url;
    urlInput.value = url;
    
    try {
        const res = await fetch(API_BASE + '/navigate', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ url: url, user_id: getUser() })
        });
        const data = await res.json();
        if (data.status === 'ok') {
            statusText.textContent = 'Loaded';
            addHistory(url);
        } else {
            statusText.textContent = 'Error: ' + (data.message || 'Navigation failed');
        }
    } catch (e) {
        statusText.textContent = 'Error: ' + e.message;
    }
}

function goBack() {
    fetch(API_BASE + '/back', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ user_id: getUser() }) });
}

function goForward() {
    fetch(API_BASE + '/forward', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ user_id: getUser() }) });
}

function reload() {
    fetch(API_BASE + '/reload', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ user_id: getUser() }) });
}

function goHome() {
    navigateTo(WAVE_SEARCH_URL);
}

// ===== AI Panel =====

function toggleAIPanel() {
    aiPanel.classList.toggle('hidden');
    if (!aiPanel.classList.contains('hidden')) {
        aiInput.focus();
        // Close other panels
        bookmarksPanel.classList.add('hidden');
        historyPanel.classList.add('hidden');
    }
}

async function sendAIMessage() {
    const message = aiInput.value.trim();
    if (!message) return;
    
    // Add user message
    addAIMessage(message, 'user');
    aiInput.value = '';
    
    // Show typing indicator
    const typingId = addAIMessage('Thinking...', 'assistant');
    
    try {
        // Call surfAutomate API (routes to Wave Assistant / GLM-5.2 on Theta EdgeCloud)
        const res = await fetch(API_BASE + '/automate', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                task: message,
                user_id: getUser()
            })
        });
        const data = await res.json();
        
        // Remove typing indicator
        document.getElementById(typingId)?.remove();
        
        if (data.status === 'ok') {
            addAIMessage(data.response || data.message || 'Done!', 'assistant');
            if (data.steps) {
                addAIMessage('Steps executed:\n' + data.steps.map((s, i) => `${i+1}. ${s.action}: ${s.result}`).join('\n'), 'assistant');
            }
        } else {
            addAIMessage('Error: ' + (data.message || 'Something went wrong'), 'assistant');
        }
    } catch (e) {
        document.getElementById(typingId)?.remove();
        addAIMessage('Error: ' + e.message, 'assistant');
    }
}

function addAIMessage(text, role) {
    const div = document.createElement('div');
    div.className = 'ai-message ' + role;
    
    if (role === 'assistant' && text.includes('\n')) {
        const pre = document.createElement('pre');
        pre.textContent = text;
        div.appendChild(pre);
    } else {
        div.textContent = text;
    }
    
    aiMessages.appendChild(div);
    aiMessages.scrollTop = aiMessages.scrollHeight;
    return div;
}

// ===== Bookmarks =====

function loadBookmarks() {
    const bookmarks = JSON.parse(localStorage.getItem('wave-surf-bookmarks') || '[]');
    bookmarksList.innerHTML = '';
    
    if (bookmarks.length === 0) {
        bookmarksList.innerHTML = '<p style="color: var(--wave-muted); padding: 16px; text-align: center; font-size: 13px;">No bookmarks yet</p>';
        return;
    }
    
    bookmarks.forEach((bm, i) => {
        const item = document.createElement('div');
        item.className = 'bookmark-item';
        item.innerHTML = `
            <img class="favicon" src="https://www.google.com/s2/favicons?domain=${encodeURIComponent(bm.url)}" alt="" onerror="this.style.display='none'">
            <div style="flex:1; overflow:hidden;">
                <div class="title">${escapeHtml(bm.title)}</div>
                <div class="url">${escapeHtml(bm.url)}</div>
            </div>
        `;
        item.onclick = () => navigateTo(bm.url);
        bookmarksList.appendChild(item);
    });
}

function addBookmark(url, title) {
    const bookmarks = JSON.parse(localStorage.getItem('wave-surf-bookmarks') || '[]');
    bookmarks.push({ url, title, added: Date.now() });
    localStorage.setItem('wave-surf-bookmarks', JSON.stringify(bookmarks));
    loadBookmarks();
    
    // Also sync to BrowserBookmark entity via API
    fetch(API_BASE + '/bookmark', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url, title, user_id: getUser() })
    }).catch(() => {});
}

// ===== History =====

function loadHistory() {
    const history = JSON.parse(localStorage.getItem('wave-surf-history') || '[]');
    historyList.innerHTML = '';
    
    if (history.length === 0) {
        historyList.innerHTML = '<p style="color: var(--wave-muted); padding: 16px; text-align: center; font-size: 13px;">No history yet</p>';
        return;
    }
    
    history.slice(-50).reverse().forEach(h => {
        const item = document.createElement('div');
        item.className = 'history-item';
        item.innerHTML = `
            <img class="favicon" src="https://www.google.com/s2/favicons?domain=${encodeURIComponent(h.url)}" alt="" onerror="this.style.display='none'">
            <div style="flex:1; overflow:hidden;">
                <div class="title">${escapeHtml(h.title || h.url)}</div>
                <div class="url">${escapeHtml(h.url)}</div>
            </div>
        `;
        item.onclick = () => navigateTo(h.url);
        historyList.appendChild(item);
    });
}

function addHistory(url) {
    const history = JSON.parse(localStorage.getItem('wave-surf-history') || '[]');
    history.push({ url, title: url, visited: Date.now() });
    // Keep last 500 entries
    if (history.length > 500) history.shift();
    localStorage.setItem('wave-surf-history', JSON.stringify(history));
    
    // Also sync to BrowserHistory entity via API
    fetch(API_BASE + '/history', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url, title: url, user_id: getUser() })
    }).catch(() => {});
}

// ===== Screenshot =====

async function takeScreenshot() {
    try {
        const res = await fetch(API_BASE + '/screenshot?user_id=' + getUser());
        const blob = await res.blob();
        const url = URL.createObjectURL(blob);
        
        // Open in new tab
        window.open(url, '_blank');
        statusText.textContent = 'Screenshot captured';
    } catch (e) {
        statusText.textContent = 'Screenshot failed: ' + e.message;
    }
}

// ===== Fullscreen =====

function toggleFullscreen() {
    if (!document.fullscreenElement) {
        document.documentElement.requestFullscreen();
    } else {
        document.exitFullscreen();
    }
}

// ===== Connection Status =====

async function checkConnection() {
    try {
        const res = await fetch(API_BASE + '/health');
        const data = await res.json();
        if (data.status === 'ok' || data.status === 'healthy') {
            connectionStatus.className = 'status-dot connected';
            if (data.fps) fpsCounter.textContent = data.fps + 'fps';
        } else {
            connectionStatus.className = 'status-dot disconnected';
        }
    } catch {
        connectionStatus.className = 'status-dot disconnected';
    }
}

// ===== Helpers =====

function getUser() {
    return localStorage.getItem('wave-user-id') || 'demo';
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// ===== Event Bindings =====

function bindEvents() {
    // Address bar
    goBtn.addEventListener('click', () => navigateTo(urlInput.value));
    urlInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') navigateTo(urlInput.value);
    });
    
    // Navigation
    backBtn.addEventListener('click', goBack);
    forwardBtn.addEventListener('click', goForward);
    reloadBtn.addEventListener('click', reload);
    homeBtn.addEventListener('click', goHome);
    
    // AI panel
    askAiBtn.addEventListener('click', toggleAIPanel);
    aiCloseBtn.addEventListener('click', () => aiPanel.classList.add('hidden'));
    aiSendBtn.addEventListener('click', sendAIMessage);
    aiInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            sendAIMessage();
        }
    });
    
    // Sidebars
    bookmarksBtn.addEventListener('click', () => {
        bookmarksPanel.classList.toggle('hidden');
        historyPanel.classList.add('hidden');
        aiPanel.classList.add('hidden');
    });
    bookmarksCloseBtn.addEventListener('click', () => bookmarksPanel.classList.add('hidden'));
    
    historyBtn.addEventListener('click', () => {
        historyPanel.classList.toggle('hidden');
        bookmarksPanel.classList.add('hidden');
        aiPanel.classList.add('hidden');
    });
    historyCloseBtn.addEventListener('click', () => historyPanel.classList.add('hidden'));
    
    // Screenshot
    screenshotBtn.addEventListener('click', takeScreenshot);
    
    // Fullscreen
    fullscreenBtn.addEventListener('click', toggleFullscreen);
    
    // Keyboard shortcuts
    document.addEventListener('keydown', (e) => {
        if (e.ctrlKey || e.metaKey) {
            if (e.key === 'l') { e.preventDefault(); urlInput.focus(); urlInput.select(); }
            if (e.key === 't') { e.preventDefault(); navigateTo(WAVE_SEARCH_URL); }
            if (e.key === 'h') { e.preventDefault(); historyPanel.classList.toggle('hidden'); }
            if (e.key === 'b') { e.preventDefault(); bookmarksPanel.classList.toggle('hidden'); }
            if (e.key === 'k') { e.preventDefault(); toggleAIPanel(); }
        }
    });
}

// Start
init();
