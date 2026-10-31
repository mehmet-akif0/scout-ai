const $ = id => document.getElementById(id);
let startups = [];
const escape = value => String(value).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
async function api(url, options) {
  const response = await fetch(url, options);
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || 'İşlem başarısız.');
  return result;
}
async function load() {
  try {
    startups = await api('/api/startups');
    const current = $('sector').value;
    $('sector').innerHTML = '<option value="">Tüm sektörler</option>' + [...new Set(startups.map(s => s.sector))].sort().map(s => `<option>${escape(s)}</option>`).join('');
    $('sector').value = current;
    $('message').textContent = '';
    render();
  } catch { $('message').textContent = 'Veriler yüklenemedi. Sunucu bağlantısını kontrol edip sayfayı yenileyin.'; $('empty').hidden = true; }
}
function render() {
  $('total').textContent = startups.length;
  $('potential').textContent = startups.filter(s => s.score >= 80).length;
  $('meetings').textContent = startups.filter(s => s.status === 'Görüşme').length;
  $('average').textContent = startups.length ? Math.round(startups.reduce((sum, s) => sum + s.score, 0) / startups.length) : '—';
  const query = $('search').value.toLocaleLowerCase('tr');
  const visible = startups.filter(s => `${s.name} ${s.description} ${s.location}`.toLocaleLowerCase('tr').includes(query) && (!$('sector').value || s.sector === $('sector').value) && (!$('status').value || s.status === $('status').value));
  $('count').textContent = visible.length;
  $('empty').hidden = visible.length > 0;
  $('empty').querySelector('h2').textContent = startups.length ? 'Eşleşen girişim bulunamadı.' : 'Yeni fırsatlara yer aç.';
  $('empty').querySelector('p').textContent = startups.length ? 'Aramayı veya filtreleri değiştirmeyi dene.' : 'İlk girişimini ekleyerek keşif listeni oluşturmaya başla.';
  $('cards').innerHTML = visible.map(s => `<article class="card"><div class="card-top"><span class="logo">${escape(s.name.slice(0, 2).toUpperCase())}</span><span class="score">${s.score}<small>/100</small></span></div><h3>${escape(s.name)}</h3><div class="tags"><span>${escape(s.sector)}</span><span>${escape(s.stage)}</span></div><p class="description">${escape(s.description || 'Henüz açıklama eklenmedi.')}</p><div class="location">⌖ ${escape(s.location || 'Konum belirtilmedi')}</div><div class="card-bottom"><span class="status">● ${escape(s.status)}</span><button data-edit="${s.id}">İncele ↗</button></div></article>`).join('');
}
function edit(item) {
  $('form').reset();
  $('form').elements.id.value = '';
  if (item) for (const [key, value] of Object.entries(item)) if ($('form').elements.namedItem(key)) $('form').elements.namedItem(key).value = value;
  $('dialog-title').textContent = item ? 'Girişimi değerlendir' : 'Yeni girişim';
  $('delete').hidden = !item;
  $('form-error').textContent = '';
  $('editor').showModal();
}
$('add').onclick = () => edit();
$('close').onclick = () => $('editor').close();
$('cards').onclick = e => { const button = e.target.closest('[data-edit]'); if (button) edit(startups.find(s => s.id === Number(button.dataset.edit))); };
for (const id of ['search', 'sector', 'status']) $(id).addEventListener('input', render);
$('form').onsubmit = async e => {
  e.preventDefault();
  const item = Object.fromEntries(new FormData(e.target));
  item.score = Number(item.score);
  $('save').disabled = true;
  try { await api('/api/startups' + (item.id ? '/' + item.id : ''), { method: item.id ? 'PUT' : 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(item) }); $('editor').close(); await load(); }
  catch (err) { $('form-error').textContent = err.message; }
  finally { $('save').disabled = false; }
};
$('delete').onclick = async () => {
  if (!confirm('Bu girişimi kalıcı olarak silmek istiyor musunuz?')) return;
  try { await api('/api/startups/' + $('form').elements.id.value, { method: 'DELETE' }); $('editor').close(); await load(); }
  catch (err) { $('form-error').textContent = err.message; }
};
$('export').onclick = () => {
  const url = URL.createObjectURL(new Blob([JSON.stringify(startups, null, 2)], { type: 'application/json' }));
  const link = document.createElement('a'); link.href = url; link.download = 'scout-ai.json'; link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
};
load();
