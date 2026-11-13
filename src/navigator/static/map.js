/* Local D3 force layout. Edges use backend cosine neighbours, never screen proximity. */
(() => {
'use strict';
const $=id=>document.getElementById(id), canvas=$('graph'), context=canvas.getContext('2d');
const status=$('map-status'), detail=$('detail'), title=$('detail-title'), picker=$('node-picker');
const labels={answered:'Ответ найден',partial:'Ответ найден частично',not_found:'В найденных фрагментах ответ не найден',needs_clarification:'Нужно уточнение',conflict:'Неразрешённое противоречие'};
const colors={topic:'#70bea3',answered:'#68c986',partial:'#e4b460',not_found:'#f07e86',needs_clarification:'#9bada4',conflict:'#e4b460',stale:'#9bada4'};
let graph=null,nodes=[],edges=[],simulation=null,transform=d3.zoomIdentity,width=0,height=0,selected=null,view='overview',lastTopic=null,viewToken=0,loadToken=0,animation=null;
const documents=new Map();
function element(tag,text,className){const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(className)n.className=className;return n;}
function message(text,error=false){status.textContent=text;status.classList.toggle('error',error);}
function resetDetail(heading){title.textContent=heading;detail.replaceChildren();}
function paragraph(text,className){detail.append(element('p',text,className));}
async function request(url,options){
 const response=await fetch(url,options);let data;
 try{data=await response.json();}catch(error){throw new Error('Сервер вернул некорректный ответ. Повторите позже.');}
 if(!response.ok)throw new Error(typeof data.detail==='string'?data.detail:'Не удалось выполнить запрос. Проверьте параметры.');
 return data;
}
function docColor(id){let hash=0;for(const c of id)hash=(hash*31+c.charCodeAt(0))>>>0;return `hsl(${hash%360} 55% 65%)`;}
function nodeColor(n){return n.kind==='fragment'?'#6796ad':n.kind==='topic'?'#729d7c':colors[n.stale?'stale':n.result.result_type];}
function visibleNodes(){if(!selected)return nodes;const ids=new Set([selected]);for(const e of edges){if(e.source.id===selected)ids.add(e.target.id);if(e.target.id===selected)ids.add(e.source.id);}return nodes.filter(n=>ids.has(n.id));}
function redraw(){
 if(animation!==null)return;animation=requestAnimationFrame(()=>{animation=null;draw();});
}
function draw(){
 const ratio=Math.min(devicePixelRatio||1,1.5);context.setTransform(ratio,0,0,ratio,0,0);context.clearRect(0,0,width,height);
 const shown=visibleNodes(),ids=new Set(shown.map(n=>n.id));
 context.save();context.translate(transform.x,transform.y);context.scale(transform.k,transform.k);
 // An overview shows regions. Only a selected node reveals its real incident edges.
 for(const e of edges){
  if(!selected||!ids.has(e.source.id)||!ids.has(e.target.id)||(e.source.id!==selected&&e.target.id!==selected))continue;
  context.beginPath();context.moveTo(e.source.x,e.source.y);context.lineTo(e.target.x,e.target.y);
  context.strokeStyle='#8caa95';context.lineWidth=1.3/transform.k;
  context.setLineDash(e.kind==='question'?[5/transform.k,5/transform.k]:[]);context.stroke();
 }
 context.setLineDash([]);
 for(const n of shown){
  context.beginPath();context.arc(n.x,n.y,Math.max(n.radius,11/transform.k),0,Math.PI*2);context.fillStyle=nodeColor(n);context.strokeStyle=nodeColor(n);context.lineWidth=2/transform.k;
  if(n.kind==='question'&&(n.stale||n.result.result_type!=='answered')){context.setLineDash([4/transform.k,3/transform.k]);context.stroke();context.setLineDash([]);}else context.fill();
  if(n.id===selected){context.beginPath();context.arc(n.x,n.y,n.radius+5/transform.k,0,Math.PI*2);context.strokeStyle='#2f6542';context.stroke();}
  context.font=`600 ${11/transform.k}px Arial`;context.fillStyle=n.kind==='question'?'#5a3c42':'#fff';context.textAlign='center';context.fillText(n.number,n.x,n.y+4/transform.k);
 }
 context.restore();
 // Place labels in screen coordinates, reserving space for nodes and earlier labels.
 const boxes=[],points=shown.map(n=>({n,x:transform.applyX(n.x),y:transform.applyY(n.y),r:Math.max(n.radius*transform.k,11)+5}));
 const ordered=points.slice().sort((a,b)=>Number(b.n.id===selected)-Number(a.n.id===selected)||(b.n.count||0)-(a.n.count||0));
 context.font='12px Arial';context.textAlign='left';
 const overlaps=(a,b)=>a.x<b.x+b.w&&a.x+a.w>b.x&&a.y<b.y+b.h&&a.y+a.h>b.y;
 for(const p of ordered){
  const words=p.n.label.split(/\s+/),lines=[];let line='';
  for(const word of words){if(line&&context.measureText(line+' '+word).width>142){lines.push(line);line=word;}else line+=(line?' ':'')+word;}
  if(line)lines.push(line);if(lines.length>3){lines.length=3;lines[2]=lines[2].slice(0,19)+'…';}
  const w=Math.min(160,Math.max(...lines.map(t=>context.measureText(t).width))+12),h=lines.length*15+8;
  const candidates=[{x:p.x-w/2,y:p.y+p.r+3},{x:p.x-w/2,y:p.y-p.r-h-3},{x:p.x+p.r+4,y:p.y-h/2},{x:p.x-p.r-w-4,y:p.y-h/2}];
  const box=candidates.map(c=>({...c,w,h})).find(c=>c.x>=6&&c.y>=6&&c.x+c.w<=width-6&&c.y+c.h<=height-48&&!boxes.some(b=>overlaps(c,b))&&!points.some(q=>overlaps(c,{x:q.x-q.r,y:q.y-q.r,w:q.r*2,h:q.r*2})));
  if(!box)continue;boxes.push(box);context.fillStyle='#f5f8f2f5';context.fillRect(box.x,box.y,box.w,box.h);context.fillStyle=p.n.id===selected?'#194c2b':'#405d48';
  lines.forEach((text,i)=>context.fillText(text,box.x+6,box.y+15+i*15));
 }
 canvas.dataset.visibleNodes=String(shown.length);canvas.dataset.visibleLabels=String(boxes.length);
}
const zoom=d3.zoom().scaleExtent([.25,5]).on('zoom',event=>{transform=event.transform;redraw();});
d3.select(canvas).call(zoom).on('dblclick.zoom',null);
function fit(){
 if(!nodes.length)return;
 const shown=visibleNodes();const xs=shown.map(n=>n.x),ys=shown.map(n=>n.y);const loX=Math.min(...xs)-60,hiX=Math.max(...xs)+60,loY=Math.min(...ys)-60,hiY=Math.max(...ys)+80;
 const scale=Math.min(1.6,(width-35)/(hiX-loX),(height-70)/(hiY-loY));
 d3.select(canvas).call(zoom.transform,d3.zoomIdentity.translate(width/2-(loX+hiX)*scale/2,height/2-(loY+hiY)*scale/2).scale(scale));
}
function installGraph(nextNodes,nextEdges){
 if(simulation)simulation.stop();nodes=nextNodes.map((n,i)=>({...n,number:n.kind==='topic'?String(graph.topics.findIndex(t=>t.id===n.id)+1):n.kind==='question'?'?':String(i+1)}));edges=nextEdges.map(e=>({...e}));selected=null;
 const pickerNodes=nodes.slice().sort((a,b)=>a.label.localeCompare(b.label,'ru'));picker.replaceChildren(element('option','Выберите тему, вопрос или фрагмент'));
 picker.firstChild.value='';for(const n of pickerNodes){const option=element('option',n.label);option.value=n.id;picker.append(option);}
 simulation=d3.forceSimulation(nodes).randomSource(d3.randomLcg(.42)).force('links',d3.forceLink(edges).id(n=>n.id).distance(e=>e.kind==='question'?125:75+(1-(e.similarity||0))*220).strength(e=>e.kind==='question'?.15:.5))
  .force('charge',d3.forceManyBody().strength(n=>-160-n.radius*10)).force('collision',d3.forceCollide(n=>Math.max(70,n.radius+38))).force('center',d3.forceCenter(width/2,height/2)).alphaDecay(.035).on('tick',redraw);
 // Settle the initial view synchronously; no perpetual motion or hidden-tab simulation.
 simulation.stop();simulation.tick(220);fit();redraw();
 // Positions remain fixed until the user changes the view.
}
function resize(){const box=canvas.getBoundingClientRect();width=box.width;height=box.height;const ratio=Math.min(devicePixelRatio||1,1.5);canvas.width=Math.round(width*ratio);canvas.height=Math.round(height*ratio);if(nodes.length)fit();redraw();}
new ResizeObserver(resize).observe(canvas);
document.addEventListener('visibilitychange',()=>{if(simulation){if(document.hidden)simulation.stop();else if(simulation.alpha()>.02&&!matchMedia('(prefers-reduced-motion: reduce)').matches)simulation.restart();}});
function hit(event){const box=canvas.getBoundingClientRect(),p=transform.invert([event.clientX-box.left,event.clientY-box.top]);let found=null,distance=Infinity;
 for(const n of visibleNodes()){const d=Math.hypot(n.x-p[0],n.y-p[1]);if(d<Math.max(n.radius,11/transform.k)+12/transform.k&&d<distance){found=n;distance=d;}}return found;}
canvas.addEventListener('click',event=>{if(event.defaultPrevented)return;const n=hit(event);if(n)select(n);});
canvas.addEventListener('mousemove',event=>{const n=hit(event),hover=$('hover');canvas.style.cursor=n?'pointer':'grab';if(!n){hover.hidden=true;return;}hover.textContent=n.label;hover.hidden=false;const box=canvas.getBoundingClientRect();hover.style.left=Math.max(8,Math.min(event.clientX-box.left+12,width-hover.offsetWidth-10))+'px';hover.style.top=Math.max(8,event.clientY-box.top-44)+'px';});
canvas.addEventListener('mouseleave',()=>{$('hover').hidden=true;});
picker.addEventListener('change',()=>{const n=nodes.find(n=>n.id===picker.value);if(n)select(n);});
$('show-checks').addEventListener('change',overview);$('topic-filter').addEventListener('input',renderBrowser);
$('fit').addEventListener('click',fit);$('overview').addEventListener('click',()=>overview());$('refresh').addEventListener('click',load);
function overview(){
 if(!graph)return;viewToken++;view='overview';lastTopic=null;resetDetail('Выберите тему');paragraph('Темы собраны по смыслу из всего корпуса. Нажмите на тему, затем выберите фрагмент, чтобы увидеть соседей из разных файлов.');
 const ns=graph.topics.map(t=>({...t,kind:'topic',radius:Math.min(26,10+Math.sqrt(t.count))}));const es=graph.edges.map(e=>({...e}));
 for(const q of ($('show-checks').checked?graph.questions:[])){const id='question-'+q.id;ns.push({...q,id,kind:'question',label:q.question,radius:12});for(const t of q.related_topics)es.push({source:id,target:t.id,similarity:t.similarity,kind:'question'});}
 installGraph(ns,es);renderBrowser();$('graph-caption').textContent='Обзор областей · выберите точку, чтобы увидеть её связи';
 const stale=graph.questions.filter(q=>q.stale).length;
 message(`${graph.topics.length} тем · ${graph.chunk_count.toLocaleString('ru')} фрагментов · ${graph.documents.length} документов · ${graph.questions.length} проверенных вопросов${stale?' · требуют повторной проверки: '+stale:''}`);
}
async function load(){
 const token=++loadToken;message('Строим карту по текущему индексу…');$('refresh').disabled=true;
 try{for(let i=0;i<100;i++){
  const data=await request('/api/map');if(token!==loadToken)return;
  if(data.status==='building'){await new Promise(resolve=>setTimeout(resolve,1800));continue;}
  graph=data;documents.clear();for(const d of graph.documents)documents.set(d.id,d.name);graph.topics=graph.topics.map((t,i)=>({...t,label:window.SmenaMapLabels.topic(t,documents,i)}));overview();return;
 }throw new Error('Карта ещё строится. Подождите и нажмите «Обновить».');}
 catch(error){if(token===loadToken)message(error.message,true);}
 finally{if(token===loadToken)$('refresh').disabled=false;}
}
function renderBrowser(){
 if(!graph)return;
 const list=$('topic-list'),query=$('topic-filter').value.trim().toLocaleLowerCase();list.replaceChildren();
 const topicMatches=graph.topics.filter(t=>[t.label,...t.documents.map(d=>documents.get(d.id)||'')].join(' ').toLocaleLowerCase().includes(query));
 const questions=graph.questions.filter(q=>q.question.toLocaleLowerCase().includes(query));
 if(questions.length)list.append(element('h3','Проверенные вопросы'));
 for(const q of questions){const b=element('button',undefined,'question-link');b.type='button';b.append(element('strong',q.question),element('span',q.stale?'Нужна повторная проверка':labels[q.result.result_type],'node-badge'));b.addEventListener('click',()=>{$('show-checks').checked=true;overview();const n=nodes.find(n=>n.id==='question-'+q.id);if(n)select(n);});list.append(b);}
 list.append(element('p','Области: '+topicMatches.length+' из '+graph.topics.length,'browser-count'));
 for(const topic of topicMatches){
  const index=graph.topics.findIndex(t=>t.id===topic.id)+1;
  const b=element('button',undefined,'topic-link');b.type='button';
  b.append(element('span',String(index),'topic-number'),element('strong',topic.label),element('small',topic.count+' фрагментов · '+topic.documents.length+' документов'),element('span',topic.documents.slice(0,2).map(d=>documents.get(d.id)||d.id).join(' · '),'topic-docs'));
  b.addEventListener('click',()=>{if(view!=='overview')overview();const n=nodes.find(n=>n.id===topic.id);if(n)select(n);});list.append(b);
 }
 if(!topicMatches.length&&!questions.length)list.append(element('p','В названиях тем и документов совпадений нет. Для поиска по содержимому используйте страницу вопросов.'));
}
function fragmentButton(f,cosine){const button=element('button',undefined,'fragment');button.type='button';const strong=element('strong',f.document_name);const color=element('i',undefined,'document-color');color.style.background=docColor(f.document_id);strong.prepend(color);button.append(strong,element('span',f.preview));if(cosine!==undefined)button.append(element('small','Близость в 384D: '+cosine.toFixed(3)));button.addEventListener('click',()=>showFragment(f.id));return button;}
function sourceButton(sourceId,label='Открыть источник'){const b=element('button',label,'button secondary');b.type='button';b.addEventListener('click',()=>openSource(sourceId));return b;}
async function select(n){
 selected=n.id;picker.value=n.id;fit();redraw();$('graph-caption').textContent='Фокус: выбранный узел и его прямые связи · «Вся карта» возвращает обзор';if(n.kind==='question'){viewToken++;showQuestion(n);return;}
 if(n.kind==='fragment'){await showFragment(n.id);return;}
 const token=++viewToken;resetDetail(n.label);paragraph('Загружаем фрагменты темы…');
 try{const data=await request('/api/map/topics/'+encodeURIComponent(n.id)+'?corpus_revision='+encodeURIComponent(graph.corpus_revision));if(token!==viewToken)return;lastTopic=n.id;
  resetDetail(n.label);paragraph(`${data.count} фрагментов из ${data.documents.length} документов. Показаны ${data.shown} ближайших к центру темы.`);
  const list=element('ul');for(const d of data.documents){const li=element('li',(documents.get(d.id)||d.id)+' — '+d.count);list.append(li);}detail.append(list);
  detail.append(element('h3','Фрагменты темы'));for(const f of data.fragments)detail.append(fragmentButton(f));
 }catch(error){if(token===viewToken){resetDetail(n.label);paragraph(error.message);message(error.message,true);}}
}
async function showFragment(id){
 const token=++viewToken;resetDetail('Ближайшие фрагменты');paragraph('Ищем соседей в исходном векторном пространстве…');
 try{const data=await request('/api/map/fragments/'+encodeURIComponent(id)+'?corpus_revision='+encodeURIComponent(graph.corpus_revision));if(token!==viewToken)return;
  const f=data.fragment;view='fragment';lastTopic=f.topic_id;const fs=[f,...data.neighbours];installGraph(fs.map(a=>({...a,kind:'fragment',label:a.preview.replace(/\s+/g,' ').slice(0,52),radius:a.id===id?19:11})),data.neighbours.map(a=>({source:id,target:a.id,similarity:a.similarity,kind:'similarity'})));
  selected=id;picker.value=id;redraw();$('graph-caption').textContent='Фрагменты всего корпуса · выбранный фрагмент и его соседи';
  resetDetail(f.document_name);paragraph(f.preview);detail.append(sourceButton(f.source_id));
  const back=element('button','К теме','button secondary');back.type='button';back.addEventListener('click',()=>{overview();const n=nodes.find(n=>n.id===f.topic_id);if(n)select(n);});const actions=element('div',undefined,'action-row');actions.append(back);detail.append(actions);
  paragraph('Ниже — 8 ближайших фрагментов по cosine similarity в 384 измерениях. Тематическая близость не доказывает наличие ответа.');
  for(const a of data.neighbours)detail.append(fragmentButton(a,a.similarity));message('Выбран фрагмент и его ближайшие соседи по всем документам.');
 }catch(error){if(token===viewToken){resetDetail('Не удалось открыть фрагмент');paragraph(error.message);message(error.message,true);}}
}
function showQuestion(q){
 resetDetail(q.question);detail.append(element('span',q.stale?'Нужна повторная проверка':labels[q.result.result_type],'node-badge'));
 paragraph('Проверено: '+new Date(q.checked_at).toLocaleString('ru-RU'));
 if(q.stale)paragraph('База изменилась после этой проверки. Результат относится к прежней версии; проверьте вопрос снова.','text-warning');
 if(q.result.result_type==='not_found')paragraph('В найденных фрагментах не удалось подтвердить ответ. Это результат конкретной проверки, а не доказательство отсутствия сведений во всей базе.');
 for(const claim of q.result.summary)paragraph(claim.text);
 for(const key of (q.result.result_type==='not_found'?[]:['missing_information','clarifications','conflicts']))for(const item of q.result[key])paragraph(item,'text-warning');
 const seen=new Set();for(const c of q.result.citations){if(!seen.has(c.source_id)){detail.append(sourceButton(c.source_id,c.document_name));seen.add(c.source_id);}}
 const recheck=element('button','Проверить этот вопрос снова','button secondary');recheck.type='button';recheck.addEventListener('click',()=>{$('check-question').value=q.question;$('check-question').focus();$('check-form').scrollIntoView({block:'center',behavior:'auto'});});detail.append(element('div',undefined,'action-row'));detail.lastChild.append(recheck);
}
let sourceToken=0;
async function openSource(id){
 const token=++sourceToken,dialog=$('source-dialog'),body=$('source-body');$('source-title').textContent='Фрагмент документа';body.replaceChildren(element('p','Загружаем источник…'));if(!dialog.open)dialog.showModal();
 try{const data=await request('/api/sources/'+encodeURIComponent(id));if(token!==sourceToken||!dialog.open)return;$('source-title').textContent=data.document_name;body.replaceChildren(element('p','Строки извлечённого блока. Нумерация не совпадает с физическими строками оригинального PDF.','source-meta'));
  if(data.extraction_method==='ocr')body.append(element('p','Распознано со скана; возможны ошибки OCR.','text-warning'));
  for(const warning of (data.extraction_warnings||[]).slice(0,20))body.append(element('p',typeof warning==='string'?warning:JSON.stringify(warning),'text-warning'));
  data.block_text.split(/\r\n|\r|\n/).forEach((line,i)=>{const row=element('div',undefined,'source-line'+(i+1>=data.line_start&&i+1<=data.line_end?' highlight':''));row.append(element('span',String(i+1),'line-no'),element('span',line,'line-text'));body.append(row);});
  requestAnimationFrame(()=>body.querySelector('.highlight')?.scrollIntoView({block:'center'}));
 }catch(error){if(token===sourceToken)body.replaceChildren(element('p',error.message));}
}
$('source-close').addEventListener('click',()=>{$('source-dialog').close();sourceToken++;});$('source-dialog').addEventListener('close',()=>sourceToken++);
let checking=false;
$('check-form').addEventListener('submit',async event=>{
 event.preventDefault();if(checking)return;const question=$('check-question').value.trim();if(!question||!$('share-consent').checked)return;
 checking=true;$('check-button').disabled=true;$('check-status').textContent='Проверяем вопрос по документам. Это может занять до нескольких минут…';const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),265000);
 try{const result=await request('/api/map/questions',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({question,public_data:true}),signal:controller.signal});
  $('check-status').textContent='Проверка завершена: '+labels[result.answer.result_type]+'. Результат добавлен на общую карту.';await load();const q=nodes.find(n=>n.kind==='question'&&n.question.toLocaleLowerCase()===question.toLocaleLowerCase());if(q)select(q);
 }catch(error){$('check-status').textContent=error.name==='AbortError'?'Сервер не ответил вовремя. Обновите карту: проверка могла завершиться в фоне.':error.message;}
 finally{clearTimeout(timer);checking=false;$('check-button').disabled=false;}
});
load();
})();
