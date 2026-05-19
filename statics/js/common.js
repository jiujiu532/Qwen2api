// 共用工具函数
function getKey() { return localStorage.getItem('qwen2api_key') || '' }
function authHeaders() { return { Authorization: 'Bearer ' + getKey() } }
function jsonHeaders() { return { ...authHeaders(), 'Content-Type': 'application/json' } }

function logout() { localStorage.removeItem('qwen2api_key'); location.href = '/admin/login' }

function showToast(msg, duration) {
  if (!duration) duration = 2500;
  let wrap = document.querySelector('.toast-wrap');
  if (!wrap) { wrap = document.createElement('div'); wrap.className = 'toast-wrap'; document.body.appendChild(wrap) }
  const t = document.createElement('div');
  t.className = 'toast';
  t.textContent = msg;
  wrap.appendChild(t);
  setTimeout(() => t.remove(), duration);
}

// 渲染 header
function renderHeader(active) {
  const header = document.getElementById('admin-header');
  if (!header) return;
  header.innerHTML = `
    <div class="admin-header-inner">
      <div><span class="admin-brand">qwen2api</span></div>
      <nav class="admin-nav">
        <a href="/admin/accounts" class="${active === 'accounts' ? 'active' : ''}">账户管理</a>
        <a href="/admin/config" class="${active === 'config' ? 'active' : ''}">配置管理</a>
        <a href="/admin/register" class="${active === 'register' ? 'active' : ''}">扩容中心</a>
      </nav>
      <div class="admin-header-right">
        <span class="admin-version">v3.0</span>
        <button class="admin-logout" onclick="logout()">登出</button>
      </div>
    </div>
  `;
}

// 鉴权检查
async function checkAuth() {
  const key = getKey();
  if (!key) { location.href = '/admin/login'; return false }
  try {
    const r = await fetch('/api/admin/settings', { headers: authHeaders() });
    if (!r.ok) { location.href = '/admin/login'; return false }
    return true;
  } catch { location.href = '/admin/login'; return false }
}
