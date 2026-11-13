/* Display labels only: never alter clustering, membership, or retrieval. */
(() => {
'use strict';
const generic = new Set('none null поле поля проверено сохраненное сохранённое заголовок контекст непустой непустое актуальность годы года структура прочие этап'.split(' '));
window.SmenaMapLabels = {
 topic(topic, documents, index) {
  const words = (topic.keywords || topic.label.split(' · ')).filter(word => !generic.has(word.toLocaleLowerCase()));
  if (words.length) return words.join(' · ');
  const doc = topic.documents?.find(d => documents.has(d.id));
  // An exact filename is a fallback identifier, not a claim about the document's contents.
  return doc ? documents.get(doc.id).replace(/\.(pdf|docx|xlsx)$/i, '').replaceAll('_', ' ') : 'Область ' + (index + 1);
 },
};
})();
