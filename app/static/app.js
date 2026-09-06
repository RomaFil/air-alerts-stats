'use strict';

const $ = (id) => document.getElementById(id);
const LS_UID = 'alerts.uid';
const LS_MODE = 'alerts.mode';
let MODE = 'day';   // 'day' | 'cmp'
let TREE = [];

const pad = (n) => String(n).padStart(2, '0');
const todayISO = () => {
  const d = new Date();
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
};

// українська множина: 1 тривога, 2 тривоги, 5 тривог
function plural(n, one, few, many) {
  const m10 = n % 10, m100 = n % 100;
  if (m10 === 1 && m100 !== 11) return one;
  if (m10 >= 2 && m10 <= 4 && (m100 < 12 || m100 > 14)) return few;
  return many;
}

function fmtDur(sec) {
  if (!sec) return '0 хв';
  const h = Math.floor(sec / 3600);
  const m = Math.round((sec % 3600) / 60);
  if (!h) return `${m} хв`;
  return m ? `${h} год ${m} хв` : `${h} год`;
}

const hhmm = (iso) => (iso ? iso.slice(11, 16) : '—');

// ---- селектор регіонів -------------------------------------------------
function buildOptions(query) {
  const sel = $('region');
  const keep = sel.value;
  const q = (query || '').trim().toLowerCase();
  sel.innerHTML = '';
  for (const obl of TREE) {
    const hitObl = !q || obl.title.toLowerCase().includes(q);
    const kids = obl.children.filter((c) => !q || hitObl || c.title.toLowerCase().includes(q));
    if (!hitObl && !kids.length) continue;
    const group = document.createElement('optgroup');
    group.label = obl.title;
    const head = new Option(obl.title, obl.uid);
    group.appendChild(head);
    for (const c of kids) group.appendChild(new Option('   ' + c.title, c.uid));
    sel.appendChild(group);
  }
  if ([...sel.options].some((o) => o.value === keep)) sel.value = keep;
}

// ---- рендер ------------------------------------------------------------
function renderChart(data) {
  const chart = $('chart');
  chart.innerHTML = '';
  for (let h = 6; h < 24; h += 6) {
    const g = document.createElement('div');
    g.className = 'grid';
    g.style.left = (h / 24) * 100 + '%';
    chart.appendChild(g);
  }
  const dayStart = new Date(data.date + 'T00:00:00');
  const span = 24 * 3600 * 1000;
  for (const a of data.alerts) {
    const s = new Date(a.clip_start).getTime() - dayStart.getTime();
    const e = new Date(a.clip_end).getTime() - dayStart.getTime();
    const bar = document.createElement('div');
    bar.className = 'bar' + (a.ongoing ? ' ongoing' : '');
    bar.style.left = Math.max(0, (s / span) * 100) + '%';
    bar.style.width = Math.max(0.4, ((e - s) / span) * 100) + '%';
    bar.title = `${a.location_title}: ${hhmm(a.clip_start)}–${hhmm(a.clip_end)}`;
    chart.appendChild(bar);
  }
}

function renderList(data) {
  const list = $('list');
  if (!data.alerts.length) {
    list.innerHTML = '<div class="empty">Тривог за цю добу не зафіксовано.</div>';
    return;
  }
  list.innerHTML = data.alerts
    .map((a) => {
      const flags = [];
      if (a.ongoing) flags.push('триває');
      if (a.clipped) flags.push('переходить через добу');
      if (a.estimated_end) flags.push('кінець оцінено збирачем');
      return `<div class="item">
        <div>
          <div class="when">${hhmm(a.clip_start)} – ${a.ongoing ? 'зараз' : hhmm(a.clip_end)}</div>
          <span class="place">${a.location_title}</span>
        </div>
        <div>
          <div class="dur">${fmtDur(a.duration_seconds)}</div>
          ${flags.length ? `<span class="flag">${flags.join(' · ')}</span>` : ''}
        </div>
      </div>`;
    })
    .join('');
}

function renderCards(data) {
  $('c-count').textContent = data.count;
  $('c-count').nextElementSibling.textContent = plural(data.count, 'тривога', 'тривоги', 'тривог');
  $('c-total').textContent = fmtDur(data.total_seconds);
  $('c-long').textContent = fmtDur(data.longest_seconds);
  $('c-share').textContent = (data.total_seconds / 864).toFixed(1) + '%';
}

// ---- порівняння днів ---------------------------------------------------
function shiftISO(iso, days) {
  const d = new Date(iso + 'T12:00:00');
  d.setDate(d.getDate() + days);
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

function renderCompare(data, metric) {
  const chart = $('cmp-chart');
  const days = data.days;
  const max = metric === 'count' ? data.max_count : data.max_seconds;
  chart.innerHTML = '';

  const axis = $('cmp-axis');
  axis.innerHTML = '';
  // На довгих періодах числа не влазять горизонтально — вісь стає вертикальною.
  axis.classList.toggle('dense', days.length > 20);

  days.forEach((d, i) => {
    const val = metric === 'count' ? d.count : d.total_seconds;
    const col = document.createElement('div');
    col.className = 'col' + (d.covered ? '' : ' uncovered');
    const h = max > 0 ? Math.round((val / max) * 100) : 0;
    col.innerHTML = `<div class="fill" style="height:${Math.max(h, val > 0 ? 2 : 0)}%"></div>`;
    chart.appendChild(col);

    // Підпис під кожним днем, усі на одній лінії.
    const dd = d.date.slice(8, 10);
    const mm = d.date.slice(5, 7);
    const firstOfMonth = dd === '01';
    const tick = document.createElement('span');
    // Місяць пишемо лише там, де він змінюється, — решта днів це просто число.
    tick.textContent = (firstOfMonth || i === 0) ? `${dd}.${mm}` : dd;
    if (firstOfMonth) tick.className = 'first';
    axis.appendChild(tick);

    const select = () => {
      [...chart.children].forEach((c) => c.classList.remove('sel'));
      [...axis.children].forEach((t) => t.classList.remove('sel'));
      col.classList.add('sel');
      tick.classList.add('sel');
      showCmpDetail(d);
    };
    col.addEventListener('click', select);
    tick.addEventListener('click', select);
  });

  $('cmp-title').textContent =
    `${data.region_title}: ${data.from} — ${data.to}`;

  $('k-avgc').textContent = data.avg_count;
  $('k-avgt').textContent = fmtDur(data.avg_seconds);

  const covered = days.filter((d) => d.covered);
  const worst = covered.reduce((a, b) => (b.total_seconds > a.total_seconds ? b : a), covered[0]);
  const calm = covered.reduce((a, b) => (b.total_seconds < a.total_seconds ? b : a), covered[0]);
  $('k-maxd').textContent = worst ? fmtDur(worst.total_seconds) : '—';
  $('k-maxd').nextElementSibling.textContent =
    worst ? `найгірший день — ${worst.date.slice(8, 10)}.${worst.date.slice(5, 7)}` : 'найгірший день';
  $('k-mint').textContent = calm ? fmtDur(calm.total_seconds) : '—';
  $('k-mint').nextElementSibling.textContent =
    calm ? `найспокійніший — ${calm.date.slice(8, 10)}.${calm.date.slice(5, 7)}` : 'найспокійніший';

  const uncovered = days.length - covered.length;
  $('cmp-legend').innerHTML = uncovered
    ? `<span class="hint">Сірим — ${uncovered} ${plural(uncovered, 'доба', 'доби', 'діб')} до початку збору даних, за них статистики немає.</span>`
    : '<span class="hint">Торкніться стовпця, щоб побачити цифри за той день.</span>';
}

function showCmpDetail(d) {
  const [y, m, dd] = d.date.split('-');
  $('cmp-legend').innerHTML = d.covered
    ? `<b>${dd}.${m}.${y}</b> — ${d.count} ${plural(d.count, 'тривога', 'тривоги', 'тривог')}, ` +
      `${fmtDur(d.total_seconds)} під тривогою (${(d.total_seconds / 864).toFixed(1)}% доби).<br>` +
      `<span class="hint">Подвійний тап — відкрити цю добу детально.</span>`
    : `<b>${dd}.${m}.${y}</b> — до початку збору даних, статистики немає.`;
  $('cmp-legend').ondblclick = () => {
    if (!d.covered) return;
    $('date').value = d.date;
    setMode('day');
  };
}

async function loadCompare() {
  const uid = $('region').value;
  const to = $('date').value;
  if (!uid || !to) return;
  const span = parseInt($('span').value, 10);
  const from = shiftISO(to, -(span - 1));
  const scope = $('children').checked ? 'with_children' : 'exact';
  $('cmp-legend').textContent = 'Завантаження…';
  try {
    const r = await fetch(`/api/range?uid=${uid}&from=${from}&to=${to}&scope=${scope}`);
    if (!r.ok) throw new Error(await r.text());
    renderCompare(await r.json(), $('metric').value);
    $('warn').hidden = true;
  } catch (e) {
    $('cmp-legend').textContent = `Помилка: ${e.message}`;
  }
}

function setMode(mode) {
  MODE = mode;
  localStorage.setItem(LS_MODE, mode);
  const day = mode === 'day';
  $('mode-day').classList.toggle('on', day);
  $('mode-cmp').classList.toggle('on', !day);
  $('mode-day').setAttribute('aria-selected', String(day));
  $('mode-cmp').setAttribute('aria-selected', String(!day));
  $('view-day').hidden = !day;
  $('view-cmp').hidden = day;
  $('cards-day').hidden = !day;
  $('cards-cmp').hidden = day;
  $('span-row').hidden = day;
  refresh();
}

function refresh() {
  return MODE === 'day' ? load() : loadCompare();
}

// ---- завантаження ------------------------------------------------------
async function load() {
  const uid = $('region').value;
  const date = $('date').value;
  if (!uid || !date) return;
  localStorage.setItem(LS_UID, uid);
  const scope = $('children').checked ? 'with_children' : 'exact';
  $('list').innerHTML = '<div class="empty">Завантаження…</div>';
  try {
    const r = await fetch(`/api/stats?uid=${uid}&date=${date}&scope=${scope}`);
    if (!r.ok) throw new Error(await r.text());
    const data = await r.json();
    renderCards(data);
    renderChart(data);
    renderList(data);
    const warn = $('warn');
    const since = data.coverage_start;
    if (data.coverage === 'none') {
      warn.hidden = false;
      warn.textContent =
        `За цю дату даних немає: збір почався ${since ? since.slice(0, 10) : '—'}. ` +
        'Показане нижче — лише тривоги, що тривають з тих часів.';
    } else if (data.coverage === 'partial') {
      warn.hidden = false;
      warn.textContent =
        `Збір даних почався всередині цієї доби (${since ? since.slice(0, 10) : ''}). ` +
        'Тривоги, що на той момент уже тривали, пораховані правильно; ' +
        'ті, що встигли початись і скінчитись раніше, у базу не потрапили.';
    } else {
      warn.hidden = true;
    }
  } catch (e) {
    $('list').innerHTML = `<div class="empty">Помилка: ${e.message}</div>`;
  }
}

function shiftDate(days) {
  const d = new Date($('date').value + 'T12:00:00');
  d.setDate(d.getDate() + days);
  $('date').value = `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
  refresh();
}

async function init() {
  $('date').value = todayISO();
  $('date').max = todayISO();

  const [regionsRes, statusRes] = await Promise.all([
    fetch('/api/regions').then((r) => r.json()),
    fetch('/api/status').then((r) => r.json()).catch(() => null),
  ]);
  TREE = regionsRes.regions;
  buildOptions('');
  $('region').value = localStorage.getItem(LS_UID) || '31';

  if (statusRes) {
    // Саме coverage_start, а не найстаріша тривога: у фіді є тривоги, що тривають
    // з 2022 року, і вони б удавали історію, якої в нас немає.
    const since = statusRes.coverage_start ? statusRes.coverage_start.slice(0, 10) : '—';
    const poll = statusRes.last_poll_at ? statusRes.last_poll_at.slice(11, 16) + ' UTC' : 'ще не було';
    $('status').textContent =
      `Джерело: ${statusRes.provider || '—'} · збір з ${since} · ${statusRes.alerts_stored} записів · опитано ${poll}`;
    const SOURCE_NAMES = {
      siren: 'siren.pp.ua (дзеркало ukrainealarm / ДСНС)',
      ubilling: 'ubilling.net.ua/aerialalerts',
      alerts_in_ua: 'alerts.in.ua',
    };
    $('footer').textContent =
      `Дані: ${SOURCE_NAMES[statusRes.provider] || statusRes.provider || '—'} · власний збирач · час київський`;
  }

  $('filter').addEventListener('input', (e) => buildOptions(e.target.value));
  $('region').addEventListener('change', refresh);
  $('date').addEventListener('change', refresh);
  $('children').addEventListener('change', refresh);
  $('span').addEventListener('change', loadCompare);
  $('metric').addEventListener('change', loadCompare);
  $('prev').addEventListener('click', () => shiftDate(-1));
  $('next').addEventListener('click', () => shiftDate(1));
  $('today').addEventListener('click', () => { $('date').value = todayISO(); refresh(); });
  $('mode-day').addEventListener('click', () => setMode('day'));
  $('mode-cmp').addEventListener('click', () => setMode('cmp'));
  document.getElementById('controls').addEventListener('submit', (e) => e.preventDefault());

  setMode(localStorage.getItem(LS_MODE) === 'cmp' ? 'cmp' : 'day');
}

init();
