const $ = (id) => document.getElementById(id);
const state = { project: null, page: 1, active: null, marked: new Set(), drag: null, drawing: null, graphicMode: false };

function toast(message) {
  const node = $('toast'); node.textContent = message; node.classList.add('show');
  clearTimeout(node.timer); node.timer = setTimeout(() => node.classList.remove('show'), 3500);
}

async function api(path, options = {}) {
  const response = await fetch(path, options);
  const body = response.headers.get('content-type')?.includes('json') ? await response.json() : null;
  if (!response.ok) throw new Error(body?.error || ('请求失败 (' + response.status + ')'));
  return body;
}

const projectPath = (tail = '') => '/api/projects/' + state.project.project_id + tail;
const pageCandidates = () => state.project.candidates.filter((item) => item.pdf_page === state.page);
const activeCandidate = () => state.project?.candidates.find((item) => item.id === state.active);

function showProject(project) {
  state.project = project;
  state.page = project.pages[0]?.flat_page || 1;
  state.active = project.candidates[0]?.id || null;
  $('uploadStep').classList.add('hidden'); $('workspace').classList.remove('hidden'); $('finishBar').classList.remove('hidden');
  $('numbering').value = project.layout?.numbering || 'preserve';
  $('answerLines').value = project.layout?.answer_space_lines || 5;
  render();
}

function render() {
  if (!state.project) return;
  const page = state.project.pages.find((item) => item.flat_page === state.page);
  $('pageImage').src = projectPath('/files/' + page.image);
  $('pageImage').onload = renderOverlays;
  $('pageLabel').textContent = page.source_file;
  const source = state.project.source_pdfs.find((item) => item.name === page.source_file);
  const first = state.project.pages.find((item) => item.source_file === page.source_file)?.flat_page || 1;
  const sourcePage = state.page - first + 1;
  const meta = source?.pages?.find((item) => item.pdf_page === sourcePage);
  $('pageMeta').textContent = 'PDF 第 ' + sourcePage + ' 页' + (meta?.book_page ? ' · 原书第 ' + meta.book_page + ' 页' : '') + (meta?.has_text_layer ? '' : ' · 无文本层');
  $('pageIndex').textContent = state.page + ' / ' + state.project.pages.length;
  renderCandidates(); renderReview(); updateCount();
}

function updateCount() {
  const count = state.project.candidates.filter((item) => item.selected).length;
  $('selectedCount').textContent = '已选 ' + count + ' / ' + state.project.candidates.length;
}

function confidenceClass(value) { return value < .5 ? 'confidence-low' : value < .75 ? 'confidence-mid' : ''; }

function renderCandidates() {
  const list = $('candidateList'); list.innerHTML = '';
  [...state.project.candidates].sort((a,b) => a.order-b.order).forEach((item) => {
    const card = document.createElement('div'); card.className = 'candidate-card ' + (item.id === state.active ? 'active' : '');
    card.draggable = true; card.dataset.id = item.id;
    const check = document.createElement('input'); check.type = 'checkbox'; check.checked = item.selected;
    check.addEventListener('click', (event) => { event.stopPropagation(); patchCandidate(item.id, {selected: check.checked}); });
    const info = document.createElement('div');
    const title = item.question_number ? '第 ' + escapeHtml(item.question_number) + ' 题' : '待定题号';
    const relation = (item.relations || []).some((value) => value.type === 'continuation_of') ? ' · 跨页续题' : '';
    const shared = item.shared_stem ? ' · 共用题干' : '';
    const meta = escapeHtml(item.source_file) + ' · PDF ' + (item.source_pdf_page || item.pdf_page) + ' · 置信度 ' + Math.round(item.confidence*100) + '%' + relation + shared;
    info.innerHTML = '<div class="name">' + title + '</div><div class="meta ' + confidenceClass(item.confidence) + '">' + meta + '</div>';
    const mark = document.createElement('input'); mark.type = 'checkbox'; mark.title = '加入合并/关联选择'; mark.checked = state.marked.has(item.id);
    mark.addEventListener('click', (event) => { event.stopPropagation(); mark.checked ? state.marked.add(item.id) : state.marked.delete(item.id); });
    card.append(check, info, mark);
    card.addEventListener('click', () => { state.active = item.id; state.page = item.pdf_page; render(); });
    card.addEventListener('dragstart', () => card.classList.add('dragging'));
    card.addEventListener('dragend', () => card.classList.remove('dragging'));
    card.addEventListener('dragover', (event) => event.preventDefault());
    card.addEventListener('drop', async (event) => {
      event.preventDefault(); const dragged = list.querySelector('.dragging'); if (!dragged || dragged === card) return;
      const sourceItem = state.project.candidates.find((x) => x.id === dragged.dataset.id); const old = sourceItem.order;
      sourceItem.order = item.order; item.order = old;
      await patchCandidate(sourceItem.id,{order:sourceItem.order},false);
      await patchCandidate(item.id,{order:item.order},false);
      renderCandidates();
    });
    list.append(card);
  });
}

function renderOverlays() {
  const layer = $('overlayLayer'); layer.innerHTML = '';
  pageCandidates().forEach((item) => {
    const [x0,y0,x1,y1] = item.bbox; const box = document.createElement('div');
    box.className = 'candidate-box ' + (item.selected ? 'selected ' : '') + (item.id === state.active ? 'active' : '');
    Object.assign(box.style,{left:(x0*100)+'%',top:(y0*100)+'%',width:((x1-x0)*100)+'%',height:((y1-y0)*100)+'%'});
    box.innerHTML = '<span>' + escapeHtml(item.question_number || '待定') + '</span><i class="resize"></i>';
    box.addEventListener('pointerdown', (event) => beginDrag(event,item,event.target.classList.contains('resize')?'resize':'move'));
    box.addEventListener('click', (event) => { event.stopPropagation(); state.active=item.id; renderCandidates(); renderReview(); renderOverlays(); });
    layer.append(box);
    (item.preserve_graphics || []).forEach((graphic) => {
      const [gx0,gy0,gx1,gy1] = graphic; const graphicBox = document.createElement('div');
      graphicBox.className = 'graphic-box';
      Object.assign(graphicBox.style,{left:(gx0*100)+'%',top:(gy0*100)+'%',width:((gx1-gx0)*100)+'%',height:((gy1-gy0)*100)+'%'});
      layer.append(graphicBox);
    });
  });
}

function beginDrag(event,item,mode) {
  if (state.graphicMode) return;
  event.preventDefault(); event.currentTarget.setPointerCapture(event.pointerId); state.active=item.id;
  state.drag={item,mode,startX:event.clientX,startY:event.clientY,bbox:[...item.bbox],node:event.currentTarget};
  event.currentTarget.addEventListener('pointermove', moveDrag); event.currentTarget.addEventListener('pointerup', endDrag,{once:true});
}
function moveDrag(event) {
  if(!state.drag)return; const rect=$('pageImage').getBoundingClientRect(); let [x0,y0,x1,y1]=state.drag.bbox;
  const dx=(event.clientX-state.drag.startX)/rect.width,dy=(event.clientY-state.drag.startY)/rect.height;
  if(state.drag.mode==='move'){const w=x1-x0,h=y1-y0;x0=Math.max(0,Math.min(1-w,x0+dx));y0=Math.max(0,Math.min(1-h,y0+dy));x1=x0+w;y1=y0+h;}
  else{x1=Math.max(x0+.02,Math.min(1,x1+dx));y1=Math.max(y0+.02,Math.min(1,y1+dy));}
  state.drag.item.bbox=[x0,y0,x1,y1]; Object.assign(state.drag.node.style,{left:(x0*100)+'%',top:(y0*100)+'%',width:((x1-x0)*100)+'%',height:((y1-y0)*100)+'%'});
}
async function endDrag() { const drag=state.drag; state.drag=null; drag.node.removeEventListener('pointermove',moveDrag); await patchCandidate(drag.item.id,{bbox:drag.item.bbox},false); renderReview(); }

function startGraphic(event) {
  if (!state.graphicMode || !activeCandidate()) return;
  event.preventDefault();
  const imageRect = $('pageImage').getBoundingClientRect();
  const x = Math.max(0, Math.min(1, (event.clientX-imageRect.left)/imageRect.width));
  const y = Math.max(0, Math.min(1, (event.clientY-imageRect.top)/imageRect.height));
  const node = document.createElement('div'); node.className = 'graphic-box'; $('overlayLayer').append(node);
  $('pageWrap').setPointerCapture(event.pointerId);
  state.drawing = {x,y,node,imageRect};
  $('pageWrap').addEventListener('pointermove', moveGraphic);
  $('pageWrap').addEventListener('pointerup', endGraphic, {once:true});
}
function moveGraphic(event) {
  if (!state.drawing) return;
  const value = state.drawing, x = Math.max(0, Math.min(1, (event.clientX-value.imageRect.left)/value.imageRect.width));
  const y = Math.max(0, Math.min(1, (event.clientY-value.imageRect.top)/value.imageRect.height));
  const x0=Math.min(value.x,x),y0=Math.min(value.y,y),x1=Math.max(value.x,x),y1=Math.max(value.y,y);
  Object.assign(value.node.style,{left:(x0*100)+'%',top:(y0*100)+'%',width:((x1-x0)*100)+'%',height:((y1-y0)*100)+'%'});
  value.bbox=[x0,y0,x1,y1];
}
async function endGraphic() {
  const value=state.drawing; state.drawing=null; $('pageWrap').removeEventListener('pointermove',moveGraphic);
  state.graphicMode=false; $('pageStage').classList.remove('graphic-mode'); $('graphicBtn').classList.remove('primary');
  if (!value?.bbox || value.bbox[2]-value.bbox[0] < .01 || value.bbox[3]-value.bbox[1] < .01) { renderOverlays(); return; }
  const item=activeCandidate(), graphics=[...(item.preserve_graphics||[]),value.bbox];
  await patchCandidate(item.id,{preserve_graphics:graphics},false); renderReview(); renderOverlays();
}
$('pageWrap').addEventListener('pointerdown', startGraphic);

function renderReview() {
  const item=activeCandidate(); $('reviewEmpty').classList.toggle('hidden',!!item); $('reviewForm').classList.toggle('hidden',!item); if(!item)return;
  $('cropImage').src=projectPath('/crop/' + item.id + '?v=' + Date.now()); $('questionNumber').value=item.question_number||'';
  const t=item.transcription||{}; $('stem').value=t.stem||''; $('options').value=(t.options||[]).map(formatLine).join('\n'); $('subquestions').value=(t.subquestions||[]).map(formatLine).join('\n'); $('tables').value=serializeTables(t.tables||[]);
  $('graphics').value=(item.preserve_graphics||[]).map((box)=>box.join(',')).join('\n'); $('uncertaintiesConfirmed').checked=!!t.uncertainties_confirmed;
  $('subquestionsConfirmed').checked=!!t.subquestions_confirmed; $('answerLeakReviewed').checked=!!t.answer_leak_reviewed;
  const warnings=[]; if(item.manual_reason)warnings.push(item.manual_reason); if(item.answer_suspect)warnings.push('边界阶段发现疑似答案区域');
  if(item.shared_stem)warnings.push('检测到可能的共用题干，请确认关联的小题范围');
  (item.relations||[]).filter((value)=>value.type==='continuation_of').forEach(()=>warnings.push('已标记为跨页续题，导出时将与主问题合并'));
  (t.uncertainties||[]).forEach((u)=>warnings.push('低置信度：' + (u.fragment||'未知片段') + ' — ' + (u.reason||'请人工核对')));
  if(item.subquestions_detected)warnings.push('边界阶段观察到 ' + item.subquestions_detected + ' 个小问起始标记');
  $('warnings').innerHTML=warnings.map((w,i)=>'<div class="warning ' + (i===0&&item.answer_suspect?'danger':'') + '">' + escapeHtml(w) + '</div>').join('');
  renderReflowPreview();
}
function formatLine(value){return typeof value==='string'?value:(value.label||value.number||'')+((value.label||value.number)?'. ':'')+(value.text||'')}
function parseGraphics(value){return value.split(/\n+/).map(x=>x.trim()).filter(Boolean).map(line=>line.split(',').map(Number)).filter(box=>box.length===4&&box.every(Number.isFinite));}
function parseTables(value){return value.trim()?value.trim().split(/\n\s*\n/).map(block=>({rows:block.split('\n').filter(Boolean).map(row=>row.split('|').map(cell=>cell.trim()))})):[];}
function serializeTables(tables){return tables.map(table=>(table.headers?[table.headers,...(table.rows||[])]:table.rows||table).map(row=>row.join(' | ')).join('\n')).join('\n\n');}
function renderReflowPreview(){
  const item=activeCandidate(),t=item?.transcription||{};let stem=escapeHtml($('stem').value||'（待校对题干）');
  (t.uncertainties||[]).forEach(value=>{const fragment=escapeHtml(value.fragment||'');if(fragment)stem=stem.split(fragment).join('<span class="low-fragment">'+fragment+'</span>');});
  const options=$('options').value.split(/\n+/).filter(Boolean).map(value=>'<div>'+escapeHtml(value)+'</div>').join('');
  const questions=$('subquestions').value.split(/\n+/).filter(Boolean).map(value=>'<div>'+escapeHtml(value)+'</div>').join('');
  const tables=parseTables($('tables').value).map(table=>'<table>'+table.rows.map(row=>'<tr>'+row.map(cell=>'<td>'+escapeHtml(cell)+'</td>').join('')+'</tr>').join('')+'</table>').join('');
  $('reflowPreview').innerHTML='<strong>'+escapeHtml($('questionNumber').value||'题目')+'</strong><div>'+stem+'</div>'+options+questions+tables;
}
function escapeHtml(value){const node=document.createElement('div');node.textContent=String(value??'');return node.innerHTML;}

async function patchCandidate(id,changes,rerender=true){
  try{state.project=await api(projectPath('/candidates/'+id),{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify({...changes,revision:state.project.revision})});if(rerender)render();}
  catch(error){toast(error.message);render();}
}
async function action(name,body){try{state.project=await api(projectPath('/'+name),{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({...body,revision:state.project.revision})});state.marked.clear();render();return true}catch(error){toast(error.message);return false}}

$('pdfInput').addEventListener('change',(e)=>{$('fileNames').textContent=[...e.target.files].map(f=>f.name).join('、')||'尚未选择文件'});
$('uploadForm').addEventListener('submit',async(e)=>{e.preventDefault();const btn=e.submitter;btn.disabled=true;$('uploadStatus').textContent='正在渲染页面并定位候选题…';try{showProject(await api('/api/projects',{method:'POST',body:new FormData(e.target)}));}catch(error){$('uploadStatus').textContent=error.message;}finally{btn.disabled=false;}});
$('prevPage').onclick=()=>{if(state.page>1){state.page--;render()}};$('nextPage').onclick=()=>{if(state.page<state.project.pages.length){state.page++;render()}};
$('selectPageBtn').onclick=async()=>{const items=pageCandidates(),selected=items.every(i=>i.selected);for(const item of items)await patchCandidate(item.id,{selected:!selected},false);render()};
$('mergeBtn').onclick=()=>action('merge',{ids:[...state.marked]});
$('splitBtn').onclick=()=>{if(!state.active)return toast('请先选择一个候选题');$('splitDialog').showModal()};
$('splitPosition').oninput=()=>{$('splitValue').textContent=$('splitPosition').value+'%'};
$('cancelSplit').onclick=()=>{$('splitDialog').close()};
$('splitForm').onsubmit=async(event)=>{event.preventDefault();const ok=await action('split',{candidate_id:state.active,split_y:Number($('splitPosition').value)/100});if(ok)$('splitDialog').close()};
$('linkBtn').onclick=()=>action('link',{ids:[...state.marked],type:'continuation_of'});
$('graphicBtn').onclick=()=>{if(!state.active)return toast('请先选择一个候选题');state.graphicMode=!state.graphicMode;$('pageStage').classList.toggle('graphic-mode',state.graphicMode);$('graphicBtn').classList.toggle('primary',state.graphicMode);if(state.graphicMode)toast('请在 PDF 页面上拖动框选必要图形');};
$('saveReview').onclick=()=>{const item=activeCandidate(),t={...(item.transcription||{}),stem:$('stem').value.trim(),options:$('options').value.split(/\n+/).filter(Boolean),subquestions:$('subquestions').value.split(/\n+/).filter(Boolean),tables:parseTables($('tables').value),uncertainties_confirmed:$('uncertaintiesConfirmed').checked,subquestions_confirmed:$('subquestionsConfirmed').checked,answer_leak_reviewed:$('answerLeakReviewed').checked};patchCandidate(item.id,{question_number:$('questionNumber').value.trim(),transcription:t,preserve_graphics:parseGraphics($('graphics').value)});};
async function recognize(ids){if(!ids.length)return toast('没有可识别的选中题目');const existing=ids.some(id=>{const item=state.project.candidates.find(value=>value.id===id);return item&&Object.prototype.hasOwnProperty.call(item,'transcription')&&item.transcription!==null});if(existing&&!window.confirm('所选题目已有识别文本，确认重新识别并替换吗？'))return;toast('正在高精度识别所选区域…');if(await action('recognize',{ids,replace_existing:existing})){toast('识别完成，请逐题校对低置信度内容')}}
$('recognizeCurrent').onclick=()=>{const item=activeCandidate();if(item&&!item.selected)return toast('请先勾选当前题目');recognize(item?[item.id]:[])};$('recognizeSelected').onclick=()=>recognize(state.project.candidates.filter(i=>i.selected).map(i=>i.id));
$('exportBtn').onclick=async()=>{state.project.layout={...state.project.layout,numbering:$('numbering').value,answer_space_lines:Number($('answerLines').value)};try{const result=await api(projectPath('/export'),{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({layout:state.project.layout,revision:state.project.revision})});state.project=result.project;const name=result.export.pdf.split(/[\\/]/).pop();$('downloadPdf').href=projectPath('/files/exports/'+encodeURIComponent(name));$('downloadPdf').setAttribute('download',name);$('retentionDialog').showModal();}catch(error){toast(error.message)}};
$('retentionDialog').addEventListener('click',async(e)=>{if(!e.target.classList.contains('retain'))return;e.preventDefault();try{const choice=e.target.value;const result=await api(projectPath('/retention'),{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({choice,revision:state.project.revision})});if(choice==='keep_project')state.project=result;$('retentionDialog').close();toast(choice==='keep_project'?'项目已获授权并长期保留':choice==='final_pdf_only'?'仅保留了最终 PDF':'临时项目和输出已安全清理');if(choice!=='keep_project')location.reload();}catch(error){toast(error.message)}});
$('resumeBtn').onclick=async()=>{const result=await api('/api/projects');$('projectList').innerHTML=result.projects.length?result.projects.map(p=>'<div class="project-row"><div><strong>'+escapeHtml(p.title)+'</strong><small>'+escapeHtml(p.updated_at||'')+' · '+(p.retention==='keep_project'?'已保留':'会话草稿')+'</small></div><button data-project="'+p.project_id+'">打开</button></div>').join(''):'<p>没有可恢复项目。</p>';$('projectList').querySelectorAll('[data-project]').forEach(btn=>btn.onclick=async()=>{showProject(await api('/api/projects/'+btn.dataset.project));$('resumeDialog').close()});$('resumeDialog').showModal()};
['questionNumber','stem','options','subquestions','tables'].forEach(id=>$(id).addEventListener('input',renderReflowPreview));
