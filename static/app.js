const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
const state = { captchaId: '', eventPage: 1, eventTotal: 0, projects: [], domains: [], catalog: [], settings: {} };
const COUNTRY_CODES = 'AD AE AF AG AI AL AM AO AQ AR AS AT AU AW AX AZ BA BB BD BE BF BG BH BI BJ BL BM BN BO BQ BR BS BT BV BW BY BZ CA CC CD CF CG CH CI CK CL CM CN CO CR CU CV CW CX CY CZ DE DJ DK DM DO DZ EC EE EG EH ER ES ET FI FJ FK FM FO FR GA GB GD GE GF GG GH GI GL GM GN GP GQ GR GS GT GU GW GY HK HM HN HR HT HU ID IE IL IM IN IO IQ IR IS IT JE JM JO JP KE KG KH KI KM KN KP KR KW KY KZ LA LB LC LI LK LR LS LT LU LV LY MA MC MD ME MF MG MH MK ML MM MN MO MP MQ MR MS MT MU MV MW MX MY MZ NA NC NE NF NG NI NL NO NP NR NU NZ OM PA PE PF PG PH PK PL PM PN PR PS PT PW PY QA RE RO RS RU RW SA SB SC SD SE SG SH SI SJ SK SL SM SN SO SR SS ST SV SX SY SZ TC TD TF TG TH TJ TK TL TM TN TO TR TT TV TW TZ UA UG UM US UY UZ VA VC VE VG VI VN VU WF WS YE YT ZA ZM ZW'.split(' ');
const countryNames = typeof Intl.DisplayNames === 'function' ? new Intl.DisplayNames(['zh-CN'], { type: 'region' }) : null;

async function api(path, options = {}) {
  const response = await fetch(path, { credentials: 'same-origin', headers: { 'Content-Type': 'application/json', ...(options.headers || {}) }, ...options });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) { if (response.status === 401 && !path.includes('/auth/login')) showLogin(); throw new Error(data.error || `请求失败 (${response.status})`); }
  return data;
}
let toastTimer;
function toast(message, error = false) { const el = $('#toast'); el.textContent = message; el.className = `toast show${error ? ' error' : ''}`; clearTimeout(toastTimer); toastTimer = setTimeout(() => el.className = 'toast', 2800); }
function escapeHtml(value) { return String(value ?? '').replace(/[&<>'"]/g, ch => ({ '&':'&amp;', '<':'&lt;', '>':'&gt;', "'":'&#39;', '"':'&quot;' }[ch])); }

function parseCountryCodes(value) {
  return [...new Set(String(value || '').toUpperCase().split(/[\s,]+/).filter(code => COUNTRY_CODES.includes(code)))];
}
function countryName(code) {
  try { return countryNames?.of(code) || code; } catch (_) { return code; }
}
function closeCountrySelect(root) {
  root.classList.remove('open'); $('.country-menu', root).classList.add('hidden'); $('.country-control', root).setAttribute('aria-expanded', 'false');
}
function openCountrySelect(root) {
  $$('[data-country-select].open').forEach(item => { if (item !== root) closeCountrySelect(item); });
  root.classList.add('open'); $('.country-menu', root).classList.remove('hidden'); $('.country-control', root).setAttribute('aria-expanded', 'true'); $('.country-search', root).focus();
}
function renderCountrySelect(root) {
  const input = $('input[type="hidden"]', root); const selected = parseCountryCodes(input.value); input.value = selected.join(',');
  const chips = $('.country-chips', root);
  chips.innerHTML = selected.length ? selected.map(code => `<button type="button" class="country-chip" data-country-code="${code}" title="移除 ${escapeHtml(countryName(code))}">${code}<span>×</span></button>`).join('') : `<span class="country-placeholder">${input.name === 'country_whitelist' ? '选择允许访问的国家' : '选择需要拦截的国家'}</span>`;
  const query = $('.country-search', root).value.trim().toLocaleLowerCase('zh-CN');
  const filtered = COUNTRY_CODES.filter(code => `${code} ${countryName(code)}`.toLocaleLowerCase('zh-CN').includes(query));
  $('.country-options', root).innerHTML = filtered.length ? filtered.map(code => `<button type="button" class="country-option${selected.includes(code) ? ' selected' : ''}" data-country-option="${code}" role="option" aria-selected="${selected.includes(code)}"><span><b>${code}</b><small>${escapeHtml(countryName(code))}</small></span><i>${selected.includes(code) ? '✓' : ''}</i></button>`).join('') : '<p class="country-empty">没有匹配的国家</p>';
}
function setCountrySelectValue(form, name, value) {
  const input = form.elements[name]; input.value = parseCountryCodes(value).join(','); renderCountrySelect(input.closest('[data-country-select]'));
}
function initCountrySelect(root) {
  renderCountrySelect(root);
  $('.country-control', root).addEventListener('click', event => {
    const chip = event.target.closest('[data-country-code]');
    if (chip) {
      const input = $('input[type="hidden"]', root); input.value = parseCountryCodes(input.value).filter(code => code !== chip.dataset.countryCode).join(','); renderCountrySelect(root); return;
    }
    root.classList.contains('open') ? closeCountrySelect(root) : openCountrySelect(root);
  });
  $('.country-control', root).addEventListener('keydown', event => {
    if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); openCountrySelect(root); }
    if (event.key === 'Escape') closeCountrySelect(root);
  });
  $('.country-search', root).addEventListener('input', () => renderCountrySelect(root));
  $('.country-options', root).addEventListener('click', event => {
    const option = event.target.closest('[data-country-option]'); if (!option) return;
    const input = $('input[type="hidden"]', root); const selected = parseCountryCodes(input.value); const code = option.dataset.countryOption;
    input.value = (selected.includes(code) ? selected.filter(item => item !== code) : [...selected, code]).join(','); renderCountrySelect(root); $('.country-search', root).focus();
  });
}

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
    const eventLabels = { visit: '访问', click: '点击', rejected: '拒绝' };
    $('#eventsBody').innerHTML = data.items.length ? data.items.map(item => `<tr><td>#${item.id}</td><td>${escapeHtml(new Date(item.created_at).toLocaleString())}</td><td>${escapeHtml(item.domain)}</td><td><span class="event-type ${item.event_type}">${eventLabels[item.event_type] || escapeHtml(item.event_type)}</span></td><td>${escapeHtml(item.ip)}</td><td class="ua" title="${escapeHtml(item.ua)}">${escapeHtml(item.ua || '-')}</td></tr>`).join('') : '<tr><td colspan="6" style="text-align:center;padding:35px;color:#92959e">暂无符合条件的访问记录</td></tr>';
  } catch (error) { toast(error.message, true); }
}

function renderProjectCard(item, settings) {
  const domains = state.domains.filter(domain => domain.project_id === item.id);
  const primaryDomain = domains[0];
  const entry = primaryDomain?.frontend_entry || settings.frontend_entry || 'logo.gif';
  const address = primaryDomain ? `https://${primaryDomain.domain}/${entry}` : '';
  const activeCertificates = domains.filter(domain => domain.certificate_status === 'active').length;
  const addressMarkup = address ? `<a class="project-address-link" href="${escapeHtml(address)}" target="_blank" rel="noreferrer" title="${escapeHtml(address)}">${escapeHtml(address)}</a><button type="button" class="icon-button copy-address" data-address="${escapeHtml(address)}" title="复制前台地址">▣</button>` : '<span class="project-address-empty">配置域名后显示前台地址</span>';
  return `<article class="project-card rich-project-card"><header class="project-card-head"><div class="project-logo">LP</div><div class="project-title"><h4>${escapeHtml(item.name)}</h4><p>静态前台源码</p></div><span class="project-status">已下载</span></header><section class="project-address-block"><span class="project-address-label">前台地址</span><div class="project-address-value">${addressMarkup}</div></section><div class="project-meta"><span><small>域名</small><b>${domains.length}</b></span><span><small>HTTPS</small><b>${activeCertificates}/${domains.length || 0}</b></span><span><small>入口</small><b>/${escapeHtml(entry)}</b></span></div><footer class="project-actions"><button class="primary small project-config" data-project-id="${item.id}">配置</button><button class="secondary small project-update" data-project-id="${item.id}">更新</button><button class="secondary small project-cert" data-project-id="${item.id}">申请证书</button><button class="danger-link" data-project-id="${item.id}">删除</button></footer></article>`;
}

async function loadFrontend() {
  try {
    const [projects, domains, settings] = await Promise.all([api('/api/projects'), api('/api/domains'), api('/api/settings')]); state.projects = projects.items; state.domains = domains.items; state.settings = settings;
    state.catalog = projects.catalog;
    $('#projectList').innerHTML = state.projects.map(item => renderProjectCard(item, settings)).join('');
    $('#domainList').innerHTML = state.domains.length ? state.domains.map(item => `<article class="domain-item"><span><b><a href="https://${escapeHtml(item.domain)}/${escapeHtml(item.frontend_entry || settings.frontend_entry || 'logo.gif')}" target="_blank" rel="noreferrer">https://${escapeHtml(item.domain)}/${escapeHtml(item.frontend_entry || settings.frontend_entry || 'logo.gif')}</a></b><small>${escapeHtml(item.project_name || '未关联项目')}</small></span><span class="cert-${item.certificate_status}">${item.certificate_status === 'active' ? 'HTTPS 已启用' : item.certificate_status === 'failed' ? '申请失败' : '待申请 HTTPS'}</span></article>`).join('') : '<div class="empty-state" style="padding:30px"><p>还没有配置域名</p></div>';
    renderCatalog(state.catalog);
  } catch (error) { toast(error.message, true); }
}

function renderCatalog(items) {
  $('#catalogList').innerHTML = items.length ? `<div class="source-table"><div class="source-table-head"><span>LOGO</span><span>国家</span><span>官网</span><span>描述</span><span>站点预览图</span><span>更新时间</span><span>操作</span></div>${items.map(item => `<div class="source-row"><div class="source-logo">VIEW<small>ビューカード</small></div><span>日本 JP</span><span class="source-url">未配置官网</span><span>${escapeHtml(item.description)}</span><div class="source-preview">HTML</div><span class="source-time">内置源码</span><button class="primary small catalog-download" data-source-id="${escapeHtml(item.id)}" ${item.downloaded ? 'disabled' : ''}>${item.downloaded ? '已安装' : '安装'}</button></div>`).join('')}</div>` : '';
  $('#catalogEmpty').classList.toggle('hidden', items.length > 0);
}

async function loadSettings() {
  try { state.settings = await api('/api/settings'); $('#ipregistry_api_key').value = state.settings.ipregistry_api_key || ''; $('#ipregistry_enabled').checked = Boolean(state.settings.ipregistry_enabled); await loadIpregistryCredits(); }
  catch (error) { toast(error.message, true); }
}
async function loadIpregistryCredits() {
  const label = $('#ipregistryKeyLabel'); const key = $('#ipregistry_api_key').value.trim();
  label.className = '';
  if (!key) { label.textContent = 'API Key（剩余积分：未配置）'; return; }
  label.textContent = 'API Key（剩余积分：查询中）'; label.classList.add('credit-loading');
  try {
    const status = await api('/api/ipregistry/status'); label.textContent = `API Key（剩余积分：${status.remaining}）`; label.className = 'credit-ready';
  } catch (_) { label.textContent = 'API Key（剩余积分：查询失败）'; label.className = 'credit-error'; }
}
async function saveSettings() {
  try { await api('/api/settings', { method: 'POST', body: JSON.stringify({ ipregistry_api_key: $('#ipregistry_api_key').value.trim(), ipregistry_enabled: $('#ipregistry_enabled').checked }) }); await loadIpregistryCredits(); toast('防红配置已保存'); }
  catch (error) { toast(error.message, true); }
}

function ensureRedirectLinksField(form) {
  if ($('.frontend-step-panel', form)) return;
  const grid = $('.config-grid', form);
  const panel = document.createElement('section');
  panel.className = 'config-panel frontend-step-panel hidden';
  panel.innerHTML = '<div class="frontend-step-heading"><div><h4>前台配置</h4><p>配置模板按钮最终跳转到的链接和每条链接的点击上限。</p></div></div><div class="field redirect-links-field"><span>模板跳转链接</span><small>达到点击上限后自动切换到下一条，最后一条完成后从第一条继续循环；0 表示不限</small><div class="redirect-batch-toolbar"><button type="button" class="secondary small open-redirect-import">批量导入</button><label><span>批量点击上限</span><input class="redirect-batch-limit" type="number" value="0" min="0" max="999999999" step="1"></label><button type="button" class="secondary small apply-batch-limit">应用到全部</button></div><div class="redirect-import-panel hidden"><textarea class="redirect-import-input" placeholder="每行一条链接，也支持 链接|点击上限"></textarea><div><button type="button" class="secondary small cancel-redirect-import">取消</button><button type="button" class="primary small confirm-redirect-import">导入链接</button></div></div><div class="redirect-links-editor"></div><button type="button" class="secondary small add-redirect-link">+ 添加链接</button></div>';
  const summary = document.createElement('section');
  summary.className = 'config-panel config-summary-panel hidden';
  grid.append(panel, summary);
  panel.addEventListener('click', event => {
    if (event.target.closest('.open-redirect-import')) { $('.redirect-import-panel', panel).classList.remove('hidden'); $('.redirect-import-input', panel).focus(); return; }
    if (event.target.closest('.cancel-redirect-import')) { $('.redirect-import-panel', panel).classList.add('hidden'); return; }
    if (event.target.closest('.confirm-redirect-import')) {
      const batchLimit = Math.min(999999999, Math.max(0, Math.trunc(Number($('.redirect-batch-limit', panel).value) || 0)));
      const imported = parseRedirectImport($('.redirect-import-input', panel).value, batchLimit); const current = readRedirectLinks(form); const combined = [...current, ...imported.links];
      renderRedirectLinks(form, combined.slice(0, 50)); $('.redirect-import-input', panel).value = ''; $('.redirect-import-panel', panel).classList.add('hidden');
      const ignored = imported.invalid + Math.max(0, combined.length - 50); toast(`已导入 ${Math.min(imported.links.length, Math.max(0, 50 - current.length))} 条${ignored ? `，忽略 ${ignored} 条无效或超出限制的内容` : ''}`); return;
    }
    if (event.target.closest('.apply-batch-limit')) {
      const input = $('.redirect-batch-limit', panel); const raw = input.value.trim(); if (!/^\d{1,9}$/.test(raw)) return toast('请输入 0 到 999999999 的整数', true);
      const links = readRedirectLinks(form); if (!links.length) return toast('请先添加跳转链接', true); links.forEach(item => { item.limit = Number(raw); }); renderRedirectLinks(form, links); toast('已批量修改点击上限'); return;
    }
    if (event.target.closest('.add-redirect-link')) return renderRedirectLinks(form, [...readRedirectLinks(form), { url: '', limit: 0 }]);
    const remove = event.target.closest('.remove-redirect-link'); if (!remove) return;
    const links = readRedirectLinks(form); links.splice(Number(remove.dataset.index), 1); renderRedirectLinks(form, links.length ? links : [{ url: '', limit: 0 }]);
  });
  const previous = $('.wizard-actions .secondary', form); const primary = $('.wizard-actions .primary', form);
  previous.addEventListener('click', () => setConfigStep(form, Number(form.dataset.configStep || 1) - 1));
  primary.addEventListener('click', event => { const step = Number(form.dataset.configStep || 1); if (step < 3) { event.preventDefault(); setConfigStep(form, step + 1); } });
}

function parseRedirectImport(text, fallbackLimit) {
  const links = []; let invalid = 0;
  text.split(/\r?\n/).map(line => line.trim()).filter(Boolean).forEach(line => {
    let url = line; let limit = fallbackLimit; const separator = line.lastIndexOf('|'); const inlineLimit = separator >= 0 ? line.slice(separator + 1).trim() : '';
    if (/^\d{1,9}$/.test(inlineLimit)) { url = line.slice(0, separator).trim(); limit = Number(inlineLimit); }
    try { const parsed = new URL(url); if (!['http:', 'https:'].includes(parsed.protocol) || !parsed.host) throw new Error('invalid'); links.push({ url, limit }); } catch (_) { invalid++; }
  });
  return { links, invalid };
}

function readRedirectLinks(form) {
  return $$('.redirect-link-row', form).map(row => ({ url: $('[data-link-url]', row).value.trim(), limit: Math.min(999999999, Math.max(0, Math.trunc(Number($('[data-link-limit]', row).value) || 0))) })).filter(item => item.url);
}

function renderRedirectLinks(form, links) {
  $('.redirect-links-editor', form).innerHTML = (links.length ? links : [{ url: '', limit: 0 }]).map((item, index) => `<div class="redirect-link-row"><input data-link-url type="url" value="${escapeHtml(item.url || '')}" placeholder="https://example.com/"><input data-link-limit type="number" value="${Number(item.limit) || 0}" min="0" max="999999999" step="1" title="点击上限"><button type="button" class="icon-button remove-redirect-link" data-index="${index}" title="删除链接">×</button></div>`).join('');
}

function setConfigStep(form, requestedStep) {
  const step = Math.min(3, Math.max(1, requestedStep)); form.dataset.configStep = step;
  $$('.domain-panel, .access-panel', form).forEach(panel => panel.classList.toggle('hidden', step !== 1));
  $('.frontend-step-panel', form).classList.toggle('hidden', step !== 2);
  $('.config-summary-panel', form).classList.toggle('hidden', step !== 3);
  $('.config-grid', form).classList.toggle('single-panel', step > 1);
  $$('.wizard-step', form).forEach((item, index) => { item.classList.toggle('active', index === step - 1); item.classList.toggle('complete', index < step - 1); });
  const headings = [['配置前台源码','域名、访问策略和前台入口统一在这里设置。'],['前台配置','设置模板的多个跳转链接和点击切换次数。'],['确认配置','确认域名、访问入口和跳转链接后保存。']];
  $('.config-heading h3', form).textContent = headings[step - 1][0]; $('.config-heading>p:last-child', form).textContent = headings[step - 1][1];
  const previous = $('.wizard-actions .secondary', form); const primary = $('.wizard-actions .primary', form); previous.disabled = step === 1; primary.textContent = step === 3 ? '保存并完成 →' : '下一步 →';
  if (step === 3) renderConfigSummary(form);
  $('.config-grid', form).scrollTop = 0;
}

function renderConfigSummary(form) {
  const domains = JSON.parse(form.dataset.pendingDomains || '[]'); const links = readRedirectLinks(form); const entry = form.elements.frontend_entry.value.trim().replace(/^\/+/, '') || 'logo.gif';
  $('.config-summary-panel', form).innerHTML = `<h4>配置确认</h4><div class="config-summary-grid"><div><span>域名</span><strong>${domains.length}</strong><small>${escapeHtml(domains.join('、') || '未添加')}</small></div><div><span>前台入口</span><strong>/${escapeHtml(entry)}</strong><small>访问时自动记录 IP、UA 和时间</small></div><div><span>跳转链接</span><strong>${links.length}</strong><small>${links.length ? '按设置的点击上限依次切换' : '保留模板原始链接'}</small></div></div>`;
}

function fillProjectConfig(projectId) {
  const form = $('#projectConfigForm'); const domains = state.domains.filter(item => item.project_id === Number(projectId)); const settings = state.settings;
  ensureRedirectLinksField(form);
  form.elements.project_id.value = projectId; form.elements.domains.value = domains.map(item => item.domain).join('\n');
  form.dataset.pendingDomains = JSON.stringify(domains.map(item => item.domain));
  form.dataset.originalDomains = JSON.stringify(Object.fromEntries(domains.map(item => [item.domain, item.frontend_entry || 'logo.gif'])));
  form.elements.frontend_entry.value = domains[0]?.frontend_entry || settings.frontend_entry || 'logo.gif';
  renderConfigDomains(form); form.elements.ipregistry_enabled.checked = Boolean(settings.ipregistry_enabled);
  setCountrySelectValue(form, 'country_whitelist', settings.country_whitelist || ''); setCountrySelectValue(form, 'country_blacklist', settings.country_blacklist || ''); form.elements.redirect_url.value = settings.redirect_url || '';
  renderRedirectLinks(form, settings.redirect_links || []);
  ['human_verification','block_desktop','block_ios','block_android'].forEach(name => { form.elements[name].checked = Boolean(settings[name]); });
  $$('[name="blocked_ip_types"], [name="blocked_threats"]', form).forEach(el => { el.checked = (settings[el.name] || []).includes(el.value); });
  setConfigStep(form, 1);
  $('#projectConfigDialog').showModal();
}
function renderConfigDomains(form) {
  const domains = JSON.parse(form.dataset.pendingDomains || '[]'); const list = $('.config-domain-list', form);
  const entry = (form.elements.frontend_entry?.value || '').trim().replace(/^\/+/, '');
  list.innerHTML = domains.length ? domains.map(domain => `<div class="config-domain-row"><span>${escapeHtml(domain + (entry ? '/' + entry : ''))}</span><button type="button" data-domain="${escapeHtml(domain)}">删除</button></div>`).join('') : '<p>保存后配置的域名会显示在这里</p>';
}
async function saveProjectConfig(event) {
  event.preventDefault(); const form = event.currentTarget; const domains = [...new Set(form.elements.domains.value.split(/\s+/).map(item => item.trim().toLowerCase()).filter(Boolean))]; const values = {};
  ['country_whitelist','country_blacklist','redirect_url','frontend_entry'].forEach(name => values[name] = form.elements[name].value.trim()); values.redirect_links = readRedirectLinks(form); ['human_verification','block_desktop','block_ios','block_android','ipregistry_enabled'].forEach(name => values[name] = form.elements[name].checked);
  values.blocked_ip_types = $$('[name="blocked_ip_types"]:checked', form).map(el => el.value); values.blocked_threats = $$('[name="blocked_threats"]:checked', form).map(el => el.value);
  try {
    await api('/api/settings', { method: 'POST', body: JSON.stringify(values) });
    const original = JSON.parse(form.dataset.originalDomains || '{}'); const entry = values.frontend_entry.replace(/^\/+/, '') || 'logo.gif';
    const domainsToConfigure = domains.filter(domain => !Object.prototype.hasOwnProperty.call(original, domain) || original[domain] !== entry);
    for (const domain of domainsToConfigure) await api('/api/domains', { method: 'POST', body: JSON.stringify({ domain, frontend_entry: entry, project_id: Number(form.elements.project_id.value) }) });
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
$$('[data-country-select]').forEach(initCountrySelect);
document.addEventListener('click', event => { if (!event.target.closest('[data-country-select]')) $$('[data-country-select].open').forEach(closeCountrySelect); });
$('#ipregistry_api_key').addEventListener('input', () => { $('#ipregistryKeyLabel').textContent = `API Key（剩余积分：${$('#ipregistry_api_key').value.trim() ? '保存后查询' : '未配置'}）`; $('#ipregistryKeyLabel').className = ''; });
$('#sourceQuery').addEventListener('click', () => { const keyword = $('#sourceSearch').value.trim().toLowerCase(); renderCatalog(state.catalog.filter(item => `${item.name} ${item.description} ${item.filename}`.toLowerCase().includes(keyword))); });
$('#sourceReset').addEventListener('click', () => { $('#sourceSearch').value = ''; renderCatalog(state.catalog); });
$('#searchCode').addEventListener('keydown', event => { if (event.key === 'Enter') { $('#sourceSearch').value = event.currentTarget.value; $('#sourceQuery').click(); } });
$$('.close-dialog').forEach(button => button.addEventListener('click', () => button.closest('dialog').close()));
$('#importForm').addEventListener('submit', async event => { event.preventDefault(); const form = event.currentTarget; try { await api('/api/projects/import', { method: 'POST', body: JSON.stringify(Object.fromEntries(new FormData(form).entries())) }); $('#importDialog').close(); form.reset(); toast('源码已登记'); loadFrontend(); } catch (error) { toast(error.message, true); } });
$('#projectList').addEventListener('click', async event => {
  const button = event.target.closest('button'); if (!button) return; const id = Number(button.dataset.projectId); const project = state.projects.find(item => item.id === id);
  if (button.classList.contains('project-config')) { if (!state.settings.ipregistry_api_key) state.settings = await api('/api/settings'); fillProjectConfig(id); }
  if (button.classList.contains('project-update')) { button.disabled = true; try { await api(`/api/projects/${id}/update`, { method: 'POST', body: '{}' }); toast('前台源码已更新'); } catch (error) { toast(error.message, true); } finally { button.disabled = false; } }
  if (button.classList.contains('project-cert')) { const domains = state.domains.filter(item => item.project_id === id); if (!domains.length) return toast('请先在配置中添加域名', true); const pending = domains.filter(item => item.certificate_status !== 'active'); if (!pending.length) return toast('全部域名均已启用 HTTPS'); button.disabled = true; try { for (const domain of pending) await api('/api/certificates', { method: 'POST', body: JSON.stringify({ domain: domain.domain }) }); toast(`已为 ${pending.length} 个域名申请 HTTPS 证书`); loadFrontend(); } catch (error) { toast(error.message, true); button.disabled = false; } }
  if (button.classList.contains('danger-link')) { if (!confirm(`确定删除“${project?.name || ''}”吗？服务器源码文件不会被删除。`)) return; try { await api(`/api/projects/${id}`, { method: 'DELETE' }); toast('源码记录已删除'); loadFrontend(); } catch (error) { toast(error.message, true); } }
});
$('#addConfigDomain').addEventListener('click', () => { const form = $('#projectConfigForm'); const domains = form.elements.domains.value.split(/\s+/).map(item => item.trim().toLowerCase()).filter(Boolean); const current = JSON.parse(form.dataset.pendingDomains || '[]'); form.dataset.pendingDomains = JSON.stringify([...new Set([...current, ...domains])]); form.elements.domains.value = JSON.parse(form.dataset.pendingDomains).join('\n'); renderConfigDomains(form); });
$('#projectConfigForm').elements?.frontend_entry?.addEventListener('input', () => renderConfigDomains($('#projectConfigForm')));
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
