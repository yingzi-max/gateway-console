const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
const state = { captchaId: '', eventPage: 1, eventTotal: 0, projects: [], domains: [], catalog: [], settings: {} };

async function api(path, options = {}) {
  const response = await fetch(path, { credentials: 'same-origin', headers: { 'Content-Type': 'application/json', ...(options.headers || {}) }, ...options });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) { if (response.status === 401 && !path.includes('/auth/login')) showLogin(); throw new Error(data.error || `请求失败 (${response.status})`); }
  return data;
}
let toastTimer;
function toast(message, error = false) { const el = $('#toast'); el.textContent = message; el.className = `toast show${error ? ' error' : ''}`; clearTimeout(toastTimer); toastTimer = setTimeout(() => el.className = 'toast', 2800); }
function escapeHtml(value) { return String(value ?? '').replace(/[&<>'"]/g, ch => ({ '&':'&amp;', '<':'&lt;', '>':'&gt;', "'":'&#39;', '"':'&quot;' }[ch])); }

async function loadCaptcha() { try { const data = await api('/api/auth/captcha'); state.captchaId = data.id; $('#captchaQuestion').textContent = data.question; } catch (_) { $('#captchaQuestion').textContent = '重新加载'; } }
function showLogin() { $('#appView').classList.add('hidden'); $('#loginView').classList.remove('hidden'); loadCaptcha(); }
function showApp(user) { $('#loginView').classList.add('hidden'); $('#appView').classList.remove('hidden'); $('#currentUser').textContent = user || 'admin'; navigate('dashboard'); }

const pageLabels = { dashboard: ['概览 / 仪表板', '仪表板'], data: ['数据 / 数据中心', '数据中心'], frontend: ['管理 / 前台配置', '前台配置'], settings: ['管理 / 系统设置', '系统设置'] };
function navigate(page) {
  $$('[data-page-view]').forEach(el => el.classList.toggle('active', el.dataset.pageView === page));
  $$('[data-page]').forEach(el => el.classList.toggle('active', el.dataset.page === page));
  [$('#breadcrumb').textContent, $('#pageTitle').textContent] = pageLabels[page];
  $('.sidebar').classList.remove('open'); $('#mobileBackdrop').classList.remove('show');
  if (page === 'dashboard') loadDashboard(); if (page === 'data') loadEvents(); if (page === 'frontend') loadFrontend(); if (page === 'settings') loadSettings();
}
async function loadDashboard() { try { const data = await api('/api/dashboard'); $('#statToday').textContent = data.today.toLocaleString(); $('#statTotal').textContent = data.total.toLocaleString(); $('#statVisits').textContent = data.visits.toLocaleString(); $('#statClicks').textContent = data.clicks.toLocaleString(); $('#statDomains').textContent = data.domains.toLocaleString(); } catch (error) { toast(error.message, true); } }

async function loadEvents() {
  const form = new FormData($('#eventFilters')); const query = new URLSearchParams({ page: state.eventPage, page_size: 25 });
  if (form.get('domain')) query.set('domain', form.get('domain').trim()); if (form.get('type')) query.set('type', form.get('type'));
  try {
    const data = await api(`/api/events?${query}`); state.eventTotal = data.total; $('#eventCount').textContent = `共 ${data.total} 条`; $('#eventPage').textContent = data.page; $('#eventsPrev').disabled = data.page <= 1; $('#eventsNext').disabled = data.page * 25 >= data.total;
    $('#eventsBody').innerHTML = data.items.length ? data.items.map(item => `<tr><td>#${item.id}</td><td>${escapeHtml(new Date(item.created_at).toLocaleString())}</td><td>${escapeHtml(item.domain)}</td><td><span class="event-type ${item.event_type}">${item.event_type === 'visit' ? '访问' : '点击'}</span></td><td>${escapeHtml(item.ip)}</td><td class="ua" title="${escapeHtml(item.ua)}">${escapeHtml(item.ua || '-')}</td></tr>`).join('') : '<tr><td colspan="6" style="text-align:center;padding:35px;color:#92959e">暂无符合条件的访问记录</td></tr>';
  } catch (error) { toast(error.message, true); }
}

async function loadFrontend() {
  try {
    const [projects, domains] = await Promise.all([api('/api/projects'), api('/api/domains')]); state.projects = projects.items; state.domains = domains.items;
    state.catalog = projects.catalog;
    $('#projectList').innerHTML = state.projects.map(item => `<article class="project-card rich-project-card"><div class="project-brand"><div class="project-logo">e<sup>+</sup></div><div><h4>${escapeHtml(item.name)}</h4><p>官网：<span>待配置官网地址</span></p></div></div><label class="frontend-address">前台地址 <button type="button" class="copy-address" data-address="${escapeHtml(item.local_path)}" title="复制地址">▣</button><textarea readonly placeholder="配置域名后显示前台地址"></textarea></label><div class="project-actions"><button class="link-button project-config" data-project-id="${item.id}">配置</button><button class="link-button project-update" data-project-id="${item.id}">更新前台</button><button class="link-button project-cert" data-project-id="${item.id}">申请证书</button><button class="danger-link" data-project-id="${item.id}">删除</button></div></article>`).join('');
    $('#domainList').innerHTML = state.domains.length ? state.domains.map(item => `<article class="domain-item"><span><b>${escapeHtml(item.domain)}</b><small>${escapeHtml(item.project_name || '未关联项目')}</small></span><span>端口 ${item.upstream_port}</span><span class="cert-${item.certificate_status}">${item.certificate_status === 'active' ? 'HTTPS 已启用' : item.certificate_status === 'failed' ? '申请失败' : '未申请证书'}</span></article>`).join('') : '<div class="empty-state" style="padding:30px"><p>还没有配置域名</p></div>';
    renderCatalog(state.catalog);
  } catch (error) { toast(error.message, true); }
}

function renderCatalog(items) {
  $('#catalogList').innerHTML = items.length ? `<div class="source-table"><div class="source-table-head"><span>LOGO</span><span>国家</span><span>官网</span><span>描述</span><span>站点预览图</span><span>更新时间</span><span>操作</span></div>${items.map(item => `<div class="source-row"><div class="source-logo">VIEW<small>ビューカード</small></div><span>日本 JP</span><span class="source-url">未配置官网</span><span>${escapeHtml(item.description)}</span><div class="source-preview">HTML</div><span class="source-time">内置源码</span><button class="primary small catalog-download" data-source-id="${escapeHtml(item.id)}" ${item.downloaded ? 'disabled' : ''}>${item.downloaded ? '已安装' : '安装'}</button></div>`).join('')}</div>` : '';
  $('#catalogEmpty').classList.toggle('hidden', items.length > 0);
}

async function loadSettings() {
  try { state.settings = await api('/api/settings'); $('#ipregistry_api_key').value = state.settings.ipregistry_api_key || ''; $('#ipregistry_enabled').checked = Boolean(state.settings.ipregistry_enabled); }
  catch (error) { toast(error.message, true); }
}
async function saveSettings() {
  try { await api('/api/settings', { method: 'POST', body: JSON.stringify({ ipregistry_api_key: $('#ipregistry_api_key').value.trim(), ipregistry_enabled: $('#ipregistry_enabled').checked }) }); toast('防红配置已保存'); }
  catch (error) { toast(error.message, true); }
}

function fillProjectConfig(projectId) {
  const form = $('#projectConfigForm'); const domains = state.domains.filter(item => item.project_id === Number(projectId)); const settings = state.settings;
  form.elements.project_id.value = projectId; form.elements.domains.value = domains.map(item => item.domain).join('\n'); form.elements.upstream_port.value = domains[0]?.upstream_port || 8080;
  form.dataset.pendingDomains = JSON.stringify(domains.map(item => item.domain)); renderConfigDomains(form);
  form.elements.frontend_entry.value = settings.frontend_entry || 'index.html'; form.elements.ipregistry_enabled.checked = Boolean(settings.ipregistry_enabled);
  form.elements.country_whitelist.value = settings.country_whitelist || ''; form.elements.country_blacklist.value = settings.country_blacklist || ''; form.elements.redirect_url.value = settings.redirect_url || '';
  ['human_verification','block_desktop','block_ios','block_android'].forEach(name => { form.elements[name].checked = Boolean(settings[name]); });
  $$('[name="blocked_ip_types"], [name="blocked_threats"]', form).forEach(el => { el.checked = (settings[el.name] || []).includes(el.value); });
  $('#projectConfigDialog').showModal();
}
function renderConfigDomains(form) {
  const domains = JSON.parse(form.dataset.pendingDomains || '[]'); const list = $('.config-domain-list', form);
  list.innerHTML = domains.length ? domains.map(domain => `<div class="config-domain-row"><span>${escapeHtml(domain)}</span><button type="button" data-domain="${escapeHtml(domain)}">删除</button></div>`).join('') : '<p>保存后配置的域名会显示在这里</p>';
}
async function saveProjectConfig(event) {
  event.preventDefault(); const form = event.currentTarget; const domains = form.elements.domains.value.split(/\s+/).map(item => item.trim().toLowerCase()).filter(Boolean); const values = {};
  ['country_whitelist','country_blacklist','redirect_url','frontend_entry'].forEach(name => values[name] = form.elements[name].value.trim()); ['human_verification','block_desktop','block_ios','block_android','ipregistry_enabled'].forEach(name => values[name] = form.elements[name].checked);
  values.blocked_ip_types = $$('[name="blocked_ip_types"]:checked', form).map(el => el.value); values.blocked_threats = $$('[name="blocked_threats"]:checked', form).map(el => el.value);
  try {
    await api('/api/settings', { method: 'POST', body: JSON.stringify(values) }); const existing = new Set(state.domains.map(item => item.domain));
    for (const domain of domains) if (!existing.has(domain)) await api('/api/domains', { method: 'POST', body: JSON.stringify({ domain, upstream_port: form.elements.upstream_port.value, project_id: Number(form.elements.project_id.value) }) });
    $('#projectConfigDialog').close(); toast('前台配置已保存'); loadFrontend();
  } catch (error) { toast(error.message, true); }
}

$('#loginForm').addEventListener('submit', async event => { event.preventDefault(); $('#loginError').textContent = ''; const formElement = event.currentTarget; const form = new FormData(formElement); try { const result = await api('/api/auth/login', { method: 'POST', body: JSON.stringify({ username: form.get('username'), password: form.get('password'), captcha: form.get('captcha'), captcha_id: state.captchaId }) }); formElement.reset(); showApp(result.username); } catch (error) { $('#loginError').textContent = error.message; loadCaptcha(); } });
$('#captchaQuestion').addEventListener('click', loadCaptcha);
$('#logoutBtn').addEventListener('click', async () => { await api('/api/auth/logout', { method: 'POST', body: '{}' }); showLogin(); });
$('#mainNav').addEventListener('click', event => { const button = event.target.closest('[data-page]'); if (button) navigate(button.dataset.page); });
$('#refreshDashboard').addEventListener('click', loadDashboard); $('#eventFilters').addEventListener('submit', event => { event.preventDefault(); state.eventPage = 1; loadEvents(); });
$('#eventsPrev').addEventListener('click', () => { if (state.eventPage > 1) { state.eventPage--; loadEvents(); } }); $('#eventsNext').addEventListener('click', () => { if (state.eventPage * 25 < state.eventTotal) { state.eventPage++; loadEvents(); } });
$$('.tabs button').forEach(button => button.addEventListener('click', () => { $$('.tabs button').forEach(el => el.classList.toggle('active', el === button)); $$('.tab-panel').forEach(el => el.classList.toggle('active', el.id === `${button.dataset.tab}Tab`)); }));
$('#openImport').addEventListener('click', () => $('#importDialog').showModal()); $('#manualInstall').addEventListener('click', () => $('#importDialog').showModal()); $('#saveSettings').addEventListener('click', saveSettings); $('#projectConfigForm').addEventListener('submit', saveProjectConfig);
$('#sourceQuery').addEventListener('click', () => { const keyword = $('#sourceSearch').value.trim().toLowerCase(); renderCatalog(state.catalog.filter(item => `${item.name} ${item.description} ${item.filename}`.toLowerCase().includes(keyword))); });
$('#sourceReset').addEventListener('click', () => { $('#sourceSearch').value = ''; renderCatalog(state.catalog); });
$('#searchCode').addEventListener('keydown', event => { if (event.key === 'Enter') { $('#sourceSearch').value = event.currentTarget.value; $('#sourceQuery').click(); } });
$$('.close-dialog').forEach(button => button.addEventListener('click', () => button.closest('dialog').close()));
$('#importForm').addEventListener('submit', async event => { event.preventDefault(); const form = event.currentTarget; try { await api('/api/projects/import', { method: 'POST', body: JSON.stringify(Object.fromEntries(new FormData(form).entries())) }); $('#importDialog').close(); form.reset(); toast('源码已登记'); loadFrontend(); } catch (error) { toast(error.message, true); } });
$('#projectList').addEventListener('click', async event => {
  const button = event.target.closest('button'); if (!button) return; const id = Number(button.dataset.projectId); const project = state.projects.find(item => item.id === id);
  if (button.classList.contains('project-config')) { if (!state.settings.ipregistry_api_key) state.settings = await api('/api/settings'); fillProjectConfig(id); }
  if (button.classList.contains('project-update')) { button.disabled = true; try { await api(`/api/projects/${id}/update`, { method: 'POST', body: '{}' }); toast('前台源码已更新'); } catch (error) { toast(error.message, true); } finally { button.disabled = false; } }
  if (button.classList.contains('project-cert')) { const domain = state.domains.find(item => item.project_id === id); if (!domain) return toast('请先在配置中添加域名', true); button.disabled = true; try { await api('/api/certificates', { method: 'POST', body: JSON.stringify({ domain: domain.domain }) }); toast('HTTPS 证书申请成功'); loadFrontend(); } catch (error) { toast(error.message, true); button.disabled = false; } }
  if (button.classList.contains('danger-link')) { if (!confirm(`确定删除“${project?.name || ''}”吗？服务器源码文件不会被删除。`)) return; try { await api(`/api/projects/${id}`, { method: 'DELETE' }); toast('源码记录已删除'); loadFrontend(); } catch (error) { toast(error.message, true); } }
});
$('#addConfigDomain').addEventListener('click', () => { const form = $('#projectConfigForm'); const domains = form.elements.domains.value.split(/\s+/).map(item => item.trim().toLowerCase()).filter(Boolean); const current = JSON.parse(form.dataset.pendingDomains || '[]'); form.dataset.pendingDomains = JSON.stringify([...new Set([...current, ...domains])]); form.elements.domains.value = JSON.parse(form.dataset.pendingDomains).join('\n'); renderConfigDomains(form); });
$('.config-domain-list').addEventListener('click', event => { const button = event.target.closest('button[data-domain]'); if (!button) return; const form = $('#projectConfigForm'); const domains = JSON.parse(form.dataset.pendingDomains || '[]').filter(domain => domain !== button.dataset.domain); form.dataset.pendingDomains = JSON.stringify(domains); form.elements.domains.value = domains.join('\n'); renderConfigDomains(form); });
$('#projectList').addEventListener('click', async event => {
  const button = event.target.closest('.copy-address'); if (!button) return;
  try { await navigator.clipboard.writeText(button.dataset.address); toast('地址已复制'); } catch (_) { toast('当前浏览器不允许复制地址', true); }
});
$('#catalogList').addEventListener('click', async event => {
  const button = event.target.closest('.catalog-download'); if (!button || button.disabled) return; button.disabled = true; button.textContent = '下载中…';
  try { await api('/api/catalog/download', { method: 'POST', body: JSON.stringify({ source_id: button.dataset.sourceId }) }); toast('源码下载完成，已加入已下载'); loadFrontend(); document.querySelector('[data-tab="downloaded"]').click(); }
  catch (error) { toast(error.message, true); button.disabled = false; button.textContent = '下载源码'; }
});
$('#menuBtn').addEventListener('click', () => { $('.sidebar').classList.add('open'); $('#mobileBackdrop').classList.add('show'); }); $('#mobileBackdrop').addEventListener('click', () => { $('.sidebar').classList.remove('open'); $('#mobileBackdrop').classList.remove('show'); });
api('/api/auth/me').then(data => data.authenticated ? showApp(data.user) : showLogin()).catch(showLogin);
