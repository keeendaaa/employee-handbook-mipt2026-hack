/* Displays only actual retrieval records and validated final citation IDs. */
(() => {
'use strict';
const root=document.getElementById('search-map');if(!root)return;
const $=id=>document.getElementById(id),canvas=$('sm-canvas'),ctx=canvas.getContext('2d');
const reduced=matchMedia('(prefers-reduced-motion: reduce)').matches;
let base=null,trace=null,answer=null,question='',mode='fragments',state='idle',selected=null,nodes=[],links=[],simulation=null,width=0,height=0,transform=d3.zoomIdentity,frame=null,openSource=null,token=0;
const sourceNode=id=>'source:'+id,topicNode=id=>'topic:'+id;
const element=(tag,text)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;return n;};
function setStatus(text,error=false){$('sm-status').textContent=text;$('sm-status').classList.toggle('sm-error',error);}
function stages(index){[...$('sm-steps').children].forEach((node,i)=>{node.classList.toggle('active',i===index);node.classList.toggle('done',i<index);});}
const zoom=d3.zoom().scaleExtent([.25,5]).on('zoom',event=>{
 transform=event.transform;drawSoon();
 if(event.sourceEvent&&trace&&mode==='topics'&&transform.k>1.65)setMode('fragments');
});
d3.select(canvas).call(zoom).on('dblclick.zoom',null);
function color(n){if(n.kind==='question')return state==='error'||state==='cancelled'?'#9bac9f':answer?.result_type==='not_found'?'#f08489':'#edf8ee';if(n.kind==='topic')return '#6ab39b';return n.used?'#69c792':n.included?'#82add6':'#e2ad53';}
function drawSoon(){if(frame!==null)return;frame=requestAnimationFrame(()=>{frame=null;draw();});}
function draw(){
 const ratio=Math.min(devicePixelRatio||1,1.5);ctx.setTransform(ratio,0,0,ratio,0,0);ctx.clearRect(0,0,width,height);ctx.save();ctx.translate(transform.x,transform.y);ctx.scale(transform.k,transform.k);
 for(const e of links){ctx.beginPath();ctx.moveTo(e.source.x,e.source.y);ctx.lineTo(e.target.x,e.target.y);ctx.strokeStyle=e.kind==='background'?'#36594a45':e.target.used?'#72c298cc':e.kind==='context'?'#83aed477':'#99baaa88';ctx.lineWidth=(e.kind==='background'?.7:1.2)/transform.k;ctx.setLineDash(e.kind==='question'?[4/transform.k,4/transform.k]:[]);ctx.stroke();}ctx.setLineDash([]);
 const visible=new Set(nodes.filter(n=>n.active||n.kind==='question').map(n=>n.id));
 const important=nodes.filter(n=>n.kind==='topic'&&(n.active||!trace)).sort((a,b)=>(b.count||0)-(a.count||0)).slice(0,width<550?1:4);
 const labels=new Set(important.map(n=>n.id));if(selected)labels.add(selected);if(question)labels.add('request');
 for(const n of nodes){ctx.globalAlpha=trace&&!visible.has(n.id)?.18:1;ctx.beginPath();ctx.arc(n.x,n.y,n.radius,0,Math.PI*2);ctx.fillStyle=color(n);ctx.strokeStyle=color(n);ctx.lineWidth=1.8/transform.k;
  if(n.kind==='question'&&answer?.result_type==='not_found'){ctx.setLineDash([4/transform.k,3/transform.k]);ctx.stroke();ctx.setLineDash([]);}else ctx.fill();
  if(n.id===selected){ctx.beginPath();ctx.arc(n.x,n.y,n.radius+4/transform.k,0,Math.PI*2);ctx.strokeStyle='#f4fcf5';ctx.stroke();}
  ctx.fillStyle='#e0eee4';ctx.textAlign='center';ctx.font=`${12/transform.k}px Arial`;
  if(n.kind==='source'){ctx.fillStyle='#122c20';ctx.font=`bold ${10/transform.k}px Arial`;ctx.fillText(n.rank?String(n.rank):(n.used?'✓':'·'),n.x,n.y+3/transform.k);}
  if(labels.has(n.id)||transform.k>2.1&&n.active){ctx.fillStyle='#e0eee4';ctx.font=`${12/transform.k}px Arial`;const label=n.label.length>35?n.label.slice(0,32)+'…':n.label;const half=ctx.measureText(label).width/2;const lo=transform.invert([7,0])[0]+half,hi=transform.invert([width-7,0])[0]-half;ctx.fillText(label,Math.max(lo,Math.min(hi,n.x)),n.y+n.radius+16/transform.k);}
 }
 ctx.globalAlpha=1;ctx.restore();
}
function fit(animate=false){
 const relevant=nodes.filter(n=>!trace||n.active||n.kind==='question');if(!relevant.length)return;
 const xs=relevant.map(n=>n.x),ys=relevant.map(n=>n.y),loX=Math.min(...xs)-80,hiX=Math.max(...xs)+80,loY=Math.min(...ys)-65,hiY=Math.max(...ys)+75;
 const k=Math.max(.25,Math.min(1.6,(width-30)/(hiX-loX),(height-30)/(hiY-loY)));
 const target=d3.zoomIdentity.translate(width/2-(loX+hiX)*k/2,height/2-(loY+hiY)*k/2).scale(k);
 if(animate&&!reduced)d3.select(canvas).transition().duration(550).call(zoom.transform,target);else d3.select(canvas).call(zoom.transform,target);
}
function install(nextNodes,nextLinks,animate=false){
 if(simulation)simulation.stop();const positions=new Map(nodes.map(n=>[n.id,n]));nodes=nextNodes.map(n=>({...n,...(positions.has(n.id)?{x:positions.get(n.id).x,y:positions.get(n.id).y}:{})}));links=nextLinks.map(e=>({...e}));
 simulation=d3.forceSimulation(nodes).randomSource(d3.randomLcg(.42)).force('links',d3.forceLink(links).id(n=>n.id).distance(e=>e.kind==='background'?100:75).strength(e=>e.kind==='background'?.12:.65))
 .force('charge',d3.forceManyBody().strength(n=>n.active?-150:-70)).force('collision',d3.forceCollide(n=>n.radius+19)).force('centre',d3.forceCenter(width/2,height/2)).stop();
 simulation.tick(200);fit(animate);drawSoon();
 const picker=$('sm-picker');picker.replaceChildren(element('option','Выберите точку на карте'));picker.firstChild.value='';
 for(const n of nodes.filter(n=>!trace||n.active||n.kind==='question')){const option=element('option',n.label);option.value=n.id;picker.append(option);}
 if(selected&&nodes.some(n=>n.id===selected))picker.value=selected;else selected=null;
}
function build(animate=false){
 const ss=trace?.sources||[],used=new Set((answer?.citations||[]).map(c=>c.source_id));
 const shown=mode==='topics'?[]:ss.filter(s=>mode==='context'||s.role==='found'||used.has(s.citation.source_id));
 const active=new Set(ss.flatMap(s=>s.topic_ids));
 const topicData=trace?(trace.map_status==='ready'?(base?.corpus_revision===trace.corpus_revision?base.topics:trace.topics):[]):base?.topics||[];
 const ns=topicData.map(t=>({...t,id:topicNode(t.id),kind:'topic',label:t.label,active:active.has(t.id),radius:Math.min(25,9+Math.sqrt(t.count||1))}));
 const existing=new Set(ns.map(n=>n.id));const es=(base&&(!trace||base.corpus_revision===trace.corpus_revision)?base.edges:[]).filter(e=>existing.has(topicNode(e.source))&&existing.has(topicNode(e.target))).map(e=>({source:topicNode(e.source),target:topicNode(e.target),kind:'background'}));
 if(question){ns.push({id:'request',kind:'question',label:question,active:true,radius:13});for(const id of active)if(existing.has(topicNode(id)))es.push({source:'request',target:topicNode(id),kind:'question'});}
 for(const s of shown){const c=s.citation;const id=sourceNode(c.source_id);ns.push({...s,id,kind:'source',label:(s.rank?'['+s.rank+'] ':'')+c.document_name,active:true,used:used.has(c.source_id),radius:used.has(c.source_id)?12:9});
  const parents=s.topic_ids.filter(t=>existing.has(topicNode(t)));
  for(const parent of (parents.length?parents:['request']))es.push({source:parent==='request'?'request':topicNode(parent),target:id,kind:s.role==='context'?'context':'found'});
 }
 install(ns,es,animate);
 $('sm-counts').textContent=trace?`Найдено: ${trace.retrieved_count} · контекст модели: ${state==='searched'?0:trace.evidence_source_ids.length} · использовано в ответе: ${used.size}`:(base?`${base.topics.length} тем · ${base.chunk_count.toLocaleString('ru')} фрагментов · ${base.documents.length} документов`:'Карта подготавливается…');
 $('sm-answer-link').hidden=!answer;
 for(const button of root.querySelectorAll('[data-sm-mode]'))button.setAttribute('aria-pressed',String(button.dataset.smMode===mode));
}
function setMode(value){mode=value;build(true);}
for(const button of root.querySelectorAll('[data-sm-mode]'))button.addEventListener('click',()=>setMode(button.dataset.smMode));
$('sm-fit').addEventListener('click',()=>fit(true));
function showNode(n){
 selected=n.id;$('sm-picker').value=n.id;drawSoon();const detail=$('sm-detail');detail.replaceChildren(element('h3',n.label));
 if(n.kind==='source'){const c=n.citation;detail.append(element('p',n.used?'Источник использован в ответе.':n.included&&state!=='searched'?'Фрагмент включён в контекст модели.':'Кандидат поиска; наличие ответа пока не подтверждено.'));
  detail.append(element('p',c.quote));const button=element('button','Открыть источник со строками');button.className='btn btn-secondary';button.type='button';button.addEventListener('click',()=>openSource?.(c.source_id,c.document_name));detail.append(button);
 }else if(n.kind==='topic'){detail.append(element('p',`${n.count} фрагментов. Название темы сформировано автоматически.`));
  if(trace){mode=mode==='topics'?'fragments':mode;build(true);const refs=(trace.sources||[]).filter(s=>s.topic_ids.includes(n.id.replace('topic:','')));detail.append(element('p',`В этом поиске из области отобрано источников: ${refs.length}.`));}
 }else{detail.append(element('p',answer?.result_type==='not_found'?'В найденных фрагментах ответ на этот вопрос не подтверждён.':answer?'Результат показан ниже. Зелёным выделены использованные источники.':'Связи появятся после фактического поиска. Вопрос не публикуется в общей карте автоматически.'));}
}
$('sm-picker').addEventListener('change',()=>{const n=nodes.find(n=>n.id===$('sm-picker').value);if(n)showNode(n);});
function hit(event){const box=canvas.getBoundingClientRect(),p=transform.invert([event.clientX-box.left,event.clientY-box.top]);let nearest=null,d=Infinity;for(const n of nodes){const dd=Math.hypot(n.x-p[0],n.y-p[1]);if(dd<n.radius+10/transform.k&&dd<d){nearest=n;d=dd;}}return nearest;}
canvas.addEventListener('click',event=>{if(event.defaultPrevented)return;const n=hit(event);if(n)showNode(n);});
canvas.addEventListener('mousemove',event=>{const n=hit(event),tip=$('sm-tooltip');canvas.style.cursor=n?'pointer':'grab';tip.hidden=!n;if(!n)return;tip.textContent=n.label;const b=canvas.getBoundingClientRect();tip.style.left=Math.max(6,Math.min(width-tip.offsetWidth-7,event.clientX-b.left+10))+'px';tip.style.top=Math.max(6,event.clientY-b.top-40)+'px';});
canvas.addEventListener('mouseleave',()=>{$('sm-tooltip').hidden=true;});
new ResizeObserver(()=>{const b=canvas.getBoundingClientRect();width=b.width;height=b.height;const r=Math.min(devicePixelRatio||1,1.5);canvas.width=Math.round(width*r);canvas.height=Math.round(height*r);fit();drawSoon();}).observe(canvas);
async function loadBase(){
 try{for(let i=0;i<60;i++){const res=await fetch('/api/map?include_questions=false'),data=await res.json();if(!res.ok)throw new Error('map');if(data.status==='building'){await new Promise(resolve=>setTimeout(resolve,1800));continue;}base=data;if(!trace){build();if(state==='idle')setStatus('Задайте вопрос: здесь появятся найденные области и источники.');}return;}}
 catch(error){if(state==='idle')setStatus('Обзор тем временно недоступен. Поиск и показ найденных фрагментов остаются доступны.');}
}
window.SmenaSearchMap={
 setOpenSource(callback){openSource=callback;},
 start(text,operation){token++;trace=null;answer=null;question=text;mode='fragments';state=operation==='search'?'searching':'asking';selected=null;$('sm-detail').replaceChildren(element('p','Ожидаем фактические результаты поиска.'));stages(0);setStatus('Вопрос принят. Готовим смысловой поиск…');build();root.scrollIntoView({block:'start',behavior:reduced?'auto':'smooth'});},
 event(event){
  if(event.type==='stage'){
   if(event.stage==='embedding'){stages(0);setStatus(event.status==='complete'?'Смысловое представление вопроса готово.':'Готовим смысловое представление вопроса…');}
   if(event.stage==='retrieval'){stages(1);setStatus(`Ищем по документам${event.parts>1?' · часть '+event.part+' из '+event.parts:''}…`);}
   if(event.stage==='context'){stages(1);setStatus('Отбираем фрагменты и соседний контекст…');}
   if(event.stage==='generation'){stages(2);setStatus(event.attempt>1?'Повторяем запрос к модели после проверки предыдущего ответа…':'Фрагменты найдены. Модель формирует ответ по выбранным источникам…');}
  }else if(event.type==='retrieval'){trace=event.trace;state='retrieved';stages(2);setStatus(trace.retrieved_count?'Найденные области раскрыты в фрагменты. Подготавливаем ответ…':'Выполненный поиск не нашёл кандидатов.');build(true);if(trace.map_status!=='ready')$('sm-detail').replaceChildren(element('p','Группировка тем обновляется или недоступна. На карте показаны фактически найденные фрагменты.'));
  }else if(event.type==='answer'){answer=event.answer;state='answered';stages(3);setStatus(answer.result_type==='not_found'?'В найденных фрагментах ответ не подтверждён.':'Ответ получен: зелёным выделены процитированные источники.');build(true);
  }else if(event.type==='search_complete'){state='searched';stages(1);setStatus('Поиск завершён. Показаны кандидаты; ответ не генерировался и не проверялся.');build();}
 },
 fail(message,cancelled=false){answer=null;state=cancelled?'cancelled':'error';setStatus(message,true);build();},
};
loadBase();
})();
