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
function nodeColor(n){return n.kind==='fragment'?docColor(n.document_id):colors[n.kind==='question'?(n.stale?'stale':n.result.result_type):'topic'];}
function redraw(){
 if(animation!==null)return;animation=requestAnimationFrame(()=>{animation=null;draw();});
}
function draw(){
 const ratio=Math.min(devicePixelRatio||1,1.5);context.setTransform(ratio,0,0,ratio,0,0);context.clearRect(0,0,width,height);context.save();
 context.translate(transform.x,transform.y);context.scale(transform.k,transform.k);
 const adjacent=new Set(selected?[selected]:[]);
 if(selected)for(const e of edges){if(e.source.id===selected)adjacent.add(e.target.id);if(e.target.id===selected)adjacent.add(e.source.id);}
 const ranked=nodes.filter(n=>!selected||adjacent.has(n.id)).sort((a,b)=>(b.count||0)-(a.count||0));
 const labelIds=new Set(selected?[selected]:[]);
 for(const n of ranked.slice(0,width<600?(selected?0:1):(selected?2:6)))labelIds.add(n.id);
 for(const e of edges){
  const active=selected&&(e.source.id===selected||e.target.id===selected);
  context.beginPath();context.moveTo(e.source.x,e.source.y);context.lineTo(e.target.x,e.target.y);
  context.strokeStyle=active?'#a6d1bf':selected?'#41645444':'#49796566';context.lineWidth=(active?1.6:1)/transform.k;
  context.setLineDash(e.kind==='question'?[5/transform.k,5/transform.k]:[]);context.stroke();
 }
 context.setLineDash([]);
 for(const n of nodes){
  const highlighted=!selected||adjacent.has(n.id);context.globalAlpha=highlighted?1:.35;
  context.beginPath();context.arc(n.x,n.y,n.radius,0,Math.PI*2);context.fillStyle=nodeColor(n);context.strokeStyle=nodeColor(n);context.lineWidth=2/transform.k;
  if(n.kind==='question'&&(n.stale||n.result.result_type!=='answered')){context.setLineDash([4/transform.k,3/transform.k]);context.stroke();context.setLineDash([]);}else context.fill();
  if(n.id===selected){context.beginPath();context.arc(n.x,n.y,n.radius+5/transform.k,0,Math.PI*2);context.strokeStyle='#edf9f0';context.stroke();}
  if(labelIds.has(n.id)||(transform.k>1.9&&highlighted)){
   const font=13/transform.k;context.font=`${font}px Arial`;context.fillStyle='#d9e9de';context.textAlign='center';
   const label=n.label.length>34?n.label.slice(0,31)+'…':n.label;
   const half=context.measureText(label).width/2;
   const left=transform.invert([8,0])[0]+half,right=transform.invert([width-8,0])[0]-half;
   context.fillText(label,Math.max(left,Math.min(right,n.x)),n.y+n.radius+font+6/transform.k);
  }
 }
 context.globalAlpha=1;context.restore();
}
const zoom=d3.zoom().scaleExtent([.25,5]).on('zoom',event=>{transform=event.transform;redraw();});
d3.select(canvas).call(zoom).on('dblclick.zoom',null);
function fit(){
 if(!nodes.length)return;
 const xs=nodes.map(n=>n.x),ys=nodes.map(n=>n.y);const loX=Math.min(...xs)-60,hiX=Math.max(...xs)+60,loY=Math.min(...ys)-60,hiY=Math.max(...ys)+80;
 const scale=Math.min(1.6,(width-35)/(hiX-loX),(height-70)/(hiY-loY));
 d3.select(canvas).call(zoom.transform,d3.zoomIdentity.translate(width/2-(loX+hiX)*scale/2,height/2-(loY+hiY)*scale/2).scale(scale));
}
function installGraph(nextNodes,nextEdges){
 if(simulation)simulation.stop();nodes=nextNodes.map(n=>({...n}));edges=nextEdges.map(e=>({...e}));selected=null;
 const pickerNodes=nodes.slice().sort((a,b)=>a.label.localeCompare(b.label,'ru'));picker.replaceChildren(element('option','Выберите тему, вопрос или фрагмент'));
 picker.firstChild.value='';for(const n of pickerNodes){const option=element('option',n.label);option.value=n.id;picker.append(option);}
 simulation=d3.forceSimulation(nodes).randomSource(d3.randomLcg(.42)).force('links',d3.forceLink(edges).id(n=>n.id).distance(e=>e.kind==='question'?125:75+(1-(e.similarity||0))*220).strength(e=>e.kind==='question'?.15:.5))
  .force('charge',d3.forceManyBody().strength(n=>-160-n.radius*10)).force('collision',d3.forceCollide(n=>n.radius+24)).force('center',d3.forceCenter(width/2,height/2)).alphaDecay(.035).on('tick',redraw);
 // Settle the initial view synchronously; no perpetual motion or hidden-tab simulation.
 simulation.stop();simulation.tick(220);fit();redraw();
 if(!matchMedia('(prefers-reduced-motion: reduce)').matches&&!document.hidden)simulation.alpha(.08).restart();
}
function resize(){const box=canvas.getBoundingClientRect();width=box.width;height=box.height;const ratio=Math.min(devicePixelRatio||1,1.5);canvas.width=Math.round(width*ratio);canvas.height=Math.round(height*ratio);if(nodes.length)fit();redraw();}
new ResizeObserver(resize).observe(canvas);
document.addEventListener('visibilitychange',()=>{if(simulation){if(document.hidden)simulation.stop();else if(simulation.alpha()>.02&&!matchMedia('(prefers-reduced-motion: reduce)').matches)simulation.restart();}});
function hit(event){const box=canvas.getBoundingClientRect(),p=transform.invert([event.clientX-box.left,event.clientY-box.top]);let found=null,distance=Infinity;
 for(const n of nodes){const d=Math.hypot(n.x-p[0],n.y-p[1]);if(d<n.radius+12/transform.k&&d<distance){found=n;distance=d;}}return found;}
canvas.addEventListener('click',event=>{if(event.defaultPrevented)return;const n=hit(event);if(n)select(n);});
canvas.addEventListener('mousemove',event=>{const n=hit(event),hover=$('hover');canvas.style.cursor=n?'pointer':'grab';if(!n){hover.hidden=true;return;}hover.textContent=n.label;hover.hidden=false;const box=canvas.getBoundingClientRect();hover.style.left=Math.max(8,Math.min(event.clientX-box.left+12,width-hover.offsetWidth-10))+'px';hover.style.top=Math.max(8,event.clientY-box.top-44)+'px';});
canvas.addEventListener('mouseleave',()=>{$('hover').hidden=true;});
picker.addEventListener('change',()=>{const n=nodes.find(n=>n.id===picker.value);if(n)select(n);});
$('fit').addEventListener('click',fit);$('overview').addEventListener('click',()=>overview());$('refresh').addEventListener('click',load);
function overview(){
 if(!graph)return;viewToken++;view='overview';lastTopic=null;resetDetail('Выберите тему');paragraph('Темы собраны по смыслу из всего корпуса. Нажмите на тему, затем выберите фрагмент, чтобы увидеть соседей из разных файлов.');
 const ns=graph.topics.map(t=>({...t,kind:'topic',radius:Math.min(38,12+Math.sqrt(t.count)*1.3)}));const es=graph.edges.map(e=>({...e}));
 for(const q of graph.questions){const id='question-'+q.id;ns.push({...q,id,kind:'question',label:q.question,radius:12});for(const t of q.related_topics)es.push({source:id,target:t.id,similarity:t.similarity,kind:'question'});}
 installGraph(ns,es);$('graph-caption').textContent='Темы: зелёные узлы · вопросы: цвет результата проверки';
 const stale=graph.questions.filter(q=>q.stale).length;
 message(`${graph.topics.length} тем · ${graph.chunk_count.toLocaleString('ru')} фрагментов · ${graph.documents.length} документов · ${graph.questions.length} проверенных вопросов${stale?' · требуют повторной проверки: '+stale:''}`);
}
async function load(){
 const token=++loadToken;message('Строим карту по текущему индексу…');$('refresh').disabled=true;
 try{for(let i=0;i<100;i++){
  const data=await request('/api/map');if(token!==loadToken)return;
  if(data.status==='building'){await new Promise(resolve=>setTimeout(resolve,1800));continue;}
  graph=data;documents.clear();for(const d of graph.documents)documents.set(d.id,d.name);overview();return;
 }throw new Error('Карта ещё строится. Подождите и нажмите «Обновить».');}
 catch(error){if(token===loadToken)message(error.message,true);}
 finally{if(token===loadToken)$('refresh').disabled=false;}
}
function fragmentButton(f,cosine){const button=element('button',undefined,'fragment');button.type='button';const strong=element('strong',f.document_name);const color=element('i',undefined,'document-color');color.style.background=docColor(f.document_id);strong.prepend(color);button.append(strong,element('span',f.preview));if(cosine!==undefined)button.append(element('small','Близость в 384D: '+cosine.toFixed(3)));button.addEventListener('click',()=>showFragment(f.id));return button;}
function sourceButton(sourceId,label='Открыть источник'){const b=element('button',label,'button secondary');b.type='button';b.addEventListener('click',()=>openSource(sourceId));return b;}
async function select(n){
 selected=n.id;picker.value=n.id;redraw();if(n.kind==='question'){viewToken++;showQuestion(n);return;}
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
  selected=id;picker.value=id;redraw();$('graph-caption').textContent='Фрагменты всего корпуса · цвет обозначает исходный документ';
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
 for(const key of ['missing_information','clarifications','conflicts'])for(const item of q.result[key])paragraph(item,'text-warning');
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
