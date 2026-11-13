/* A request-local evidence graph. Membership comes only from the pinned retrieval trace. */
(() => {
'use strict';
const root = document.getElementById('search-map');
if (!root) return;
const $ = id => document.getElementById(id);
const graph = $('sm-canvas');
let base = null, trace = null, answer = null, question = '', mode = 'fragments';
let state = 'idle', selected = null, openSource = null;
const element = (tag, text, className) => {
 const node = document.createElement(tag);
 if (text !== undefined) node.textContent = text;
 if (className) node.className = className;
 return node;
};
const compact = text => text.replace(/\s+/g, ' ').trim();
function button(text, action, className = '') {
 const node = element('button', text, className); node.type = 'button';
 node.addEventListener('click', action); return node;
}
function setStatus(text, error = false) {
 $('sm-status').textContent = text; $('sm-status').classList.toggle('sm-error', error);
}
function stages(index) {
 [...$('sm-steps').children].forEach((node, i) => {
  node.classList.toggle('active', i === index);
  node.classList.toggle('done', i < index);
 });
}
function topics() {
 if (!trace || trace.map_status !== 'ready') return [];
 const same = base?.corpus_revision === trace.corpus_revision;
 const documents = new Map((same ? base.documents : []).map(d => [d.id, d.name]));
 return (same ? base.topics : trace.topics).map((t, i) => ({...t, label: window.SmenaMapLabels.topic(t, documents, i)}));
}
function sources() {
 const used = new Set((answer?.citations || []).map(c => c.source_id));
 return (trace?.sources || []).map((s, i) => ({...s, used: used.has(s.citation.source_id), number: s.rank || 'К' + (i + 1)}));
}
function sourceDetail(source) {
 selected = 'source:' + source.citation.source_id;
 $('sm-picker').value = selected;
 const c = source.citation, detail = $('sm-detail');
 detail.replaceChildren(element('h3', c.document_name),
  element('p', source.used ? 'Источник использован в ответе.' : source.included && state !== 'searched' ? 'Фрагмент включён в контекст модели.' : 'Кандидат поиска; наличие ответа не подтверждено.'),
  element('p', c.quote, 'sm-detail-quote'), button('Открыть источник со строками', () => openSource?.(c.source_id, c.document_name), 'btn btn-secondary'));
 markSelection();
}
function markSelection() {
 root.querySelectorAll('[data-sm-source]').forEach(node => node.classList.toggle('selected', 'source:' + node.dataset.smSource === selected));
}
function sourceNode(source) {
 const c = source.citation;
 const node = element('div', undefined, 'sm-source-node' + (source.used ? ' used' : ''));
 node.dataset.smSource = c.source_id;
 const choose = button('', () => sourceDetail(source), 'sm-source-select');
 const claim = [...(answer?.summary || []), ...(answer?.steps || [])].find(item => item.citation_ids.includes(c.source_id));
 choose.append(element('span', '[' + source.number + '] ' + (source.used ? 'Источник ответа' : source.included && state !== 'searched' ? 'В контексте модели' : 'Кандидат поиска'), 'sm-source-state'),
  element('strong', c.document_name), element('span', claim ? claim.text : compact(c.quote).slice(0, 140) + (compact(c.quote).length > 140 ? '…' : ''), 'sm-source-preview'));
 const open = button('Открыть строки ↗', () => { sourceDetail(source); openSource?.(c.source_id, c.document_name); }, 'sm-source-open');
 open.setAttribute('aria-label', 'Открыть строки: ' + c.document_name);
 node.append(choose, open); return node;
}
function topicDetail(topic) {
 selected = 'topic:' + topic.id;
 mode = 'fragments'; build();
 $('sm-picker').value = selected;
 const related = sources().filter(s => s.topic_ids.includes(topic.id));
 $('sm-detail').replaceChildren(element('h3', topic.label),
  element('p', 'Автоматическая группировка. В текущей выдаче: ' + related.length + ' источников. Один фрагмент может относиться к нескольким областям.'));
 const matching = [...graph.querySelectorAll('[data-sm-topic]')].find(n => n.dataset.smTopic === topic.id);
 matching?.scrollIntoView({block: 'nearest', behavior: 'auto'});
}
function build() {
 graph.replaceChildren();
 const all = sources(), used = all.filter(s => s.used), availableTopics = topics();
 const byId = new Map(availableTopics.map(t => [t.id, t]));
 // The normal view follows cited evidence when there is a final answer. All candidates remain accessible.
 const candidates = all.filter(s => s.role === 'found');
 const shown = mode === 'topics' ? [] : mode === 'context' ? all : used.length ? used : candidates.slice(0, 5);
 const groups = new Map();
 const relevant = mode === 'topics' ? all : shown;
 for (const source of relevant) {
  // Draw one parent per fragment to avoid duplicating a source or suggesting an order of retrieval.
  const preferred = selected?.startsWith('topic:') ? selected.slice(6) : null;
  const id = preferred && source.topic_ids.includes(preferred) && byId.has(preferred) ? preferred : source.topic_ids.find(t => byId.has(t)) || 'ungrouped';
  if (!groups.has(id)) groups.set(id, {topic: byId.get(id), sources: []});
  groups.get(id).sources.push(source);
 }
 const picker = $('sm-picker');
 picker.replaceChildren(element('option', 'Выберите область или источник')); picker.firstChild.value = '';
 for (const topic of availableTopics.filter(t => all.some(s => s.topic_ids.includes(t.id)))) {
  const option = element('option', topic.label); option.value = 'topic:' + topic.id; picker.append(option);
 }
 for (const source of all) {
  const option = element('option', '[' + source.number + '] ' + source.citation.document_name);
  option.value = 'source:' + source.citation.source_id; picker.append(option);
 }
 if (selected) picker.value = selected;
 if (!trace) {
  const empty = element('div', undefined, 'sm-empty');
  empty.append(element('strong', question ? 'Готовим поиск' : 'Путь от вопроса к источнику'),
   element('p', question || 'Задайте вопрос. Здесь появятся только относящиеся к нему области и фрагменты.'),
   element('div', 'Ваш вопрос → Найденные области → Источники', 'sm-empty-route'));
  graph.append(empty);
 } else {
  const heading = element('div', undefined, 'sm-view-heading');
  heading.append(element('strong', mode === 'topics' ? 'Области текущего поиска' : used.length && mode !== 'context' ? 'На этих фрагментах основан ответ' : mode === 'context' ? 'Все фрагменты контекста' : 'Фрагменты, найденные поиском'),
   element('span', mode === 'topics' ? groups.size + ' областей' : shown.length + ' из ' + all.length + ' источников'));
  graph.append(heading);
  const flow = element('div', undefined, 'sm-flow-body');
  const query = element('div', undefined, 'sm-query-node');
  query.append(element('span', 'ВАШ ВОПРОС', 'sm-node-eyebrow'), element('strong', question));
  if (state === 'error' || state === 'cancelled') query.append(element('span', 'Проверка не завершена', 'sm-source-state'));
  else if (answer?.result_type === 'not_found') query.append(element('span', 'Ответ не подтверждён', 'sm-source-state'));
  const branches = element('div', undefined, 'sm-branches');
  let index = 0;
  for (const [id, group] of groups) {
   const row = element('section', undefined, 'sm-branch' + (mode === 'topics' ? ' topics-only' : ''));
   row.dataset.smTopic = id;
   const label = group.topic?.label || 'Без группировки по темам';
   const topic = group.topic ? button('', () => topicDetail(group.topic), 'sm-topic-node') : element('div', undefined, 'sm-topic-node');
   topic.append(element('span', 'ОБЛАСТЬ ' + (++index), 'sm-node-eyebrow'), element('strong', label),
    element('span', 'Источников: ' + group.sources.length, 'sm-source-state'));
   if (group.topic) topic.title = 'Автоматическая группировка: ' + label;
   row.append(topic);
   if (mode !== 'topics') {
    const list = element('div', undefined, 'sm-source-list');
    for (const source of group.sources) list.append(sourceNode(source));
    row.append(list);
   }
   branches.append(row);
  }
  if (!groups.size) branches.append(element('p', 'Поиск не вернул фрагменты. Это не доказывает отсутствие сведений во всей базе.', 'sm-no-results'));
  flow.append(query, branches); graph.append(flow);
  if (mode !== 'topics' && mode !== 'context' && shown.length < all.length) {
   graph.append(button('Показать все источники (' + all.length + ')', () => setMode('context'), 'sm-show-more'));
  }
 }
 $('sm-counts').textContent = trace ? `Найдено: ${trace.retrieved_count} · контекст модели: ${state === 'searched' ? 0 : trace.evidence_source_ids.length} · цитат ответа: ${used.length}` : base ? `${base.topics.length} областей · ${base.chunk_count.toLocaleString('ru')} фрагментов · ${base.documents.length} документов` : 'Подготавливаем сведения о базе…';
 $('sm-answer-link').hidden = !answer;
 for (const node of root.querySelectorAll('[data-sm-mode]')) node.setAttribute('aria-pressed', String(node.dataset.smMode === mode));
 markSelection();
}
function setMode(value) { mode = value; build(); graph.scrollTop = 0; }
for (const node of root.querySelectorAll('[data-sm-mode]')) node.addEventListener('click', () => setMode(node.dataset.smMode));
$('sm-fit').addEventListener('click', () => { setMode('fragments'); $('sm-detail').replaceChildren(element('p', 'Выберите источник, чтобы прочитать фрагмент, или откройте строки документа.')); });
$('sm-picker').addEventListener('change', () => {
 const value = $('sm-picker').value;
 if (value.startsWith('source:')) { const source = sources().find(s => 'source:' + s.citation.source_id === value); if (source) sourceDetail(source); }
 else { const topic = topics().find(t => 'topic:' + t.id === value); if (topic) topicDetail(topic); }
});
async function loadBase() {
 try {
  for (let i = 0; i < 60; i++) {
   const response = await fetch('/api/map?include_questions=false'), data = await response.json();
   if (!response.ok) throw new Error('map');
   if (data.status === 'building') { await new Promise(resolve => setTimeout(resolve, 1800)); continue; }
   base = data; build();
   if (state === 'idle') setStatus('Задайте вопрос: увидите путь к найденным источникам.');
   return;
  }
 } catch (error) { if (state === 'idle') setStatus('Обзор тем недоступен. Поиск по документам остаётся доступен.'); }
}
window.SmenaSearchMap = {
 setOpenSource(callback) { openSource = callback; },
 start(text, operation) {
  trace = null; answer = null; question = text; mode = 'fragments'; selected = null; state = operation === 'search' ? 'searching' : 'asking';
  $('sm-detail').replaceChildren(element('p', 'Ожидаем результаты поиска.')); stages(0); setStatus('Вопрос принят. Готовим смысловой поиск…'); build();
  root.scrollIntoView({block: 'start', behavior: 'auto'});
 },
 event(event) {
  if (event.type === 'stage') {
   if (event.stage === 'embedding') { stages(0); setStatus(event.status === 'complete' ? 'Смысловое представление вопроса готово.' : 'Готовим смысловое представление вопроса…'); }
   if (event.stage === 'retrieval') { stages(1); setStatus(`Ищем по документам${event.parts > 1 ? ' · часть ' + event.part + ' из ' + event.parts : ''}…`); }
   if (event.stage === 'context') { stages(1); setStatus('Отбираем фрагменты и соседний контекст…'); }
   if (event.stage === 'generation') { stages(2); setStatus(event.attempt > 1 ? 'Повторяем запрос после проверки предыдущего ответа…' : 'Фрагменты найдены. Модель формирует ответ по источникам…'); }
  } else if (event.type === 'retrieval') {
   trace = event.trace; state = 'retrieved'; stages(2); setStatus(trace.retrieved_count ? 'Найдены фрагменты. Показываем области и источники.' : 'Поиск не вернул кандидатов.'); build();
   $('sm-detail').replaceChildren(element('p', 'Выберите источник, чтобы прочитать фрагмент, или откройте строки документа.'));
  } else if (event.type === 'map_update' && trace && event.trace.corpus_revision === trace.corpus_revision) { trace = event.trace; build();
  } else if (event.type === 'answer') {
   answer = event.answer; state = 'answered'; stages(4); setStatus(({answered: 'Ответ готов. Показаны фрагменты, на которые он ссылается.', partial: 'Ответ частичный. Показаны источники подтверждённой части; пробелы перечислены ниже.', not_found: 'В найденных фрагментах ответ не подтверждён.', needs_clarification: 'Нужно уточнение. Найденные фрагменты показаны ниже.', conflict: 'В ответе обнаружено противоречие. Проверьте положения источников.'})[answer.result_type]); build();
  } else if (event.type === 'search_complete') { state = 'searched'; stages(4); setStatus('Поиск завершён. Это кандидаты; ответ моделью не проверялся.'); build(); }
 },
 fail(message, cancelled = false) { answer = null; state = cancelled ? 'cancelled' : 'error'; stages(-1); setStatus(message, true); build(); },
};
build(); loadBase();
})();
