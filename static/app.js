const $ = s => document.querySelector(s);
const $$ = s => [...document.querySelectorAll(s)];
let selectedFile = null, historyPage = 1, currentLibrary = [];
const pageTitles={dashboard:'แดชบอร์ด',analyze:'วิเคราะห์ด้วย AI',history:'ประวัติการวิเคราะห์',library:'คลังอุปกรณ์',models:'ศูนย์โมเดล AI',about:'เกี่ยวกับโครงการ'};

function esc(v){return String(v??'').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[m]))}
function apiData(d){return d?.data && typeof d.data==='object'?d.data:d}
function apiMessage(d,fallback='เกิดข้อผิดพลาด'){return typeof d?.error==='string'?d.error:(d?.error?.message||d?.message||fallback)}
async function readApi(r){const text=await r.text();let data=null;try{data=text?JSON.parse(text):null}catch{throw Error(`เซิร์ฟเวอร์ตอบกลับไม่ใช่ JSON (HTTP ${r.status})`)}return data}
function toast(message,type='success'){const el=document.createElement('div');el.className='toast '+type;el.textContent=message;$('#toastRegion')?.append(el);setTimeout(()=>el.remove(),3800)}
function showError(msg){const e=$('#error');if(e){e.textContent=msg;e.classList.remove('hidden')}toast(msg,'error')}
function clearError(){$('#error')?.classList.add('hidden')}
function confirmAction(message,title='ยืนยันการทำรายการ'){return new Promise(resolve=>{const m=$('#confirmModal');$('#confirmTitle').textContent=title;$('#confirmText').textContent=message;m.classList.remove('hidden');const done=v=>{m.classList.add('hidden');resolve(v)};$('#confirmOk').onclick=()=>done(true);$('#confirmCancel').onclick=()=>done(false)})}

function activateTab(name){const panel=$('#'+name);if(!panel)return;$$('.tab-panel').forEach(x=>x.classList.remove('active'));panel.classList.add('active');$$('.side-link[data-tab],.bottom-nav button').forEach(x=>x.classList.toggle('active',x.dataset.tab===name));$('#pageTitle').textContent=pageTitles[name]||name;$('#sidebar').classList.remove('mobile-open');$('#sidebarOverlay').classList.remove('show');window.scrollTo({top:0,behavior:'smooth'});if(name==='dashboard')loadDashboard();if(name==='history')loadHistory();if(name==='library')loadLibrary();if(name==='models')loadModels()}
$$('[data-tab]').forEach(x=>x.addEventListener('click',()=>activateTab(x.dataset.tab)));

async function status(){try{const r=await fetch('/api/status',{cache:'no-store'});const d=apiData(await readApi(r));const ready=!!d.ready;$('#statusDot').style.background=ready?'#42d392':d.loading?'#f6c75a':'#ff7188';$('#sideHealthDot').style.background=ready?'#42d392':d.loading?'#f6c75a':'#ff7188';$('#statusText').textContent=ready?`AI พร้อม · ${d.custom_model?'YOLO Hybrid':(d.gemini?.client_ready?'Gemini Vision':'CLIP')}`:d.loading?'กำลังโหลดโมเดล...':'AI ยังไม่พร้อม';$('#sideHealth').textContent=ready?'AI พร้อมใช้งาน':d.loading?'กำลังโหลดโมเดล':'AI ทำงานได้บางส่วน';$('#modelState').textContent=d.custom_model?(d.gemini?.client_ready?'YOLO + Gemini Vision fallback':'YOLO แบบกำหนดเอง + ตรวจสอบด้วย CLIP'):(d.gemini?.client_ready?'Gemini Vision fallback':(d.model||'AI สำรอง'));if(!ready&&d.loading)setTimeout(status,1800)}catch{ $('#statusText').textContent='เชื่อมต่อเซิร์ฟเวอร์ไม่ได้';$('#sideHealth').textContent='เซิร์ฟเวอร์ออฟไลน์'}}

function selectFile(f){if(!f)return;const ok=['image/jpeg','image/png','image/webp','image/bmp'];if(!ok.includes(f.type)){showError('รองรับเฉพาะ JPG, PNG, WEBP และ BMP');return}if(f.size>12*1024*1024){showError('ไฟล์ใหญ่เกิน 12 MB');return}selectedFile=f;clearError();const reader=new FileReader();reader.onload=()=>{$('#preview').src=reader.result;$('#previewName').textContent=f.name;$('#previewWrap').classList.remove('hidden');$('#dropzone').classList.add('hidden');$('#result').classList.add('hidden');$('#quality').classList.add('hidden')};reader.readAsDataURL(f)}
$('#chooseBtn').onclick=e=>{e.stopPropagation();$('#fileInput').click()};$('#cameraBtn').onclick=e=>{e.stopPropagation();$('#cameraInput').click()};$('#fileInput').onchange=e=>selectFile(e.target.files[0]);$('#cameraInput').onchange=e=>selectFile(e.target.files[0]);$('#dropzone').onclick=()=>$('#fileInput').click();$('#dropzone').onkeydown=e=>{if(e.key==='Enter'||e.key===' ')$('#fileInput').click()};
['dragenter','dragover'].forEach(type=>$('#dropzone').addEventListener(type,e=>{e.preventDefault();$('#dropzone').classList.add('drag')}));['dragleave','drop'].forEach(type=>$('#dropzone').addEventListener(type,e=>{e.preventDefault();$('#dropzone').classList.remove('drag')}));$('#dropzone').addEventListener('drop',e=>selectFile(e.dataTransfer.files[0]));
$('#clearBtn').onclick=()=>{selectedFile=null;$('#fileInput').value='';$('#cameraInput').value='';$('#previewWrap').classList.add('hidden');$('#dropzone').classList.remove('hidden');$('#result').classList.add('hidden');$('#quality').classList.add('hidden');clearError()};
function processing(on,step=0){
  const el=$('#processing');
  if(!on){el?.classList.add('hidden');return}
  const names=['ตรวจสอบคุณภาพภาพ','ตรวจจับวัตถุหลายชิ้น','ตรวจสอบผลด้วย AI','สรุปผลและบันทึก'];
  el.innerHTML=`<b>กำลังประมวลผลด้วย Electronics AI</b><div class="steps">${names.map((x,i)=>`<div class="step ${i===step?'active':''}">${i+1}. ${x}</div>`).join('')}</div>`;
  el.classList.remove('hidden');
}
$('#analyzeBtn').onclick=async()=>{
  if(!selectedFile)return;
  clearError();
  const btn=$('#analyzeBtn'); btn.disabled=true; btn.textContent='กำลังวิเคราะห์...';
  let step=0; processing(true,step);
  const stepTimer=setInterval(()=>{step=Math.min(3,step+1);processing(true,step)},700);
  try{
    const fd=new FormData(); fd.append('image',selectedFile);
    const r=await fetch('/api/analyze',{method:'POST',body:fd});
    const raw=await readApi(r);
    if(!r.ok)throw Error(apiMessage(raw,'วิเคราะห์ไม่สำเร็จ'));
    const d=apiData(raw); renderQuality(d.quality); renderResult(d);
    toast(d.name==='Unknown'?'วิเคราะห์เสร็จแล้ว แต่ยังระบุอุปกรณ์ไม่ได้อย่างมั่นใจ':'วิเคราะห์และบันทึกประวัติเรียบร้อยแล้ว',
      d.name==='Unknown'?'error':'success');
    loadDashboard();
  }catch(e){showError(e.message)}
  finally{clearInterval(stepTimer);processing(false);btn.disabled=false;btn.textContent='✨ เริ่มวิเคราะห์ด้วย AI'}
};
function renderQuality(q){if(!q)return;const cls=q.status|| (q.ok?'good':'warning');$('#quality').className='quality '+cls;const items=q.warnings?.length?q.warnings.map(x=>`<span>⚠ ${esc(x)}</span>`).join(''):'<span>✓ คุณภาพภาพอยู่ในเกณฑ์ที่เหมาะสม</span>';const tips=q.tips?.length?`<div class="tips">${q.tips.map(x=>`<div>💡 ${esc(x)}</div>`).join('')}</div>`:'';$('#quality').innerHTML=`<b>คุณภาพภาพ · ${esc(q.width)}×${esc(q.height)}</b><div class="quality-items">${items}</div>${tips}`;$('#quality').classList.remove('hidden')}
let currentAnalysisId=null;
let feedbackBusy=false;

function feedbackFormHtml(){
  return `<div class="correction-form">
    <label for="correctLabel"><b>AI ทายผิด — อุปกรณ์นี้คืออะไร?</b></label>
    <input id="correctLabel" list="componentNames" placeholder="พิมพ์ชื่ออุปกรณ์ เช่น Arduino UNO" autocomplete="off">
    <datalist id="componentNames"></datalist>
    <div class="correction-actions">
      <button class="primary" id="submitCorrection" type="button">✓ บันทึกคำตอบและให้ AI จำ</button>
      <button class="secondary" id="cancelCorrection" type="button">ยกเลิก</button>
    </div>
    <small class="muted">เมื่อบันทึกแล้ว ระบบจะจำภาพนี้และเก็บตัวอย่างไว้ในคิวพัฒนาโมเดล</small>
  </div>`;
}

function renderResult(d){
  currentAnalysisId=d.id||d.analysis_id||null;
  const det=(d.detections||[]).map((x,i)=>{
    const v=x.verification;
    return `<div class="prediction"><div><b>#${i+1} ${esc(x.name)}</b><small>คะแนนการตรวจจับ · ${Math.round((x.score||0)*100)}%${v?` · ตรวจสอบด้วย CLIP: ${esc(v.name)} (${Math.round((v.similarity||0)*100)}% ความคล้ายคลึง)`:''}</small><div class="bar"><i style="width:${Math.min(100,(x.score||0)*100)}%"></i></div></div><strong>${Math.round((x.score||0)*100)}%</strong></div>`
  }).join('');
  const preds=(d.predictions||[]).map(x=>`<div class="prediction"><div><b>${esc(x.name_th)}</b><small>${esc(x.name)}</small><div class="bar"><i style="width:${Math.min(100,x.score_percent||0)}%"></i></div></div><strong>${esc(x.score_percent)}%</strong></div>`).join('');
  const ca=d.circuit_analysis||{};
  const notes=(ca.notes||[]).map(n=>`<div class="note ${esc(n.level)}">${esc(n.text)}</div>`).join('');
  const circuits=(ca.possible_circuits||[]).map(x=>`<li>${esc(x)}</li>`).join('');
  const scoreLabel=d.confidence_kind==='model confidence score'?'คะแนนความมั่นใจจากโมเดล YOLO':(d.confidence_kind==='learned memory match'?'ความตรงกับความจำจาก feedback':'คะแนนความคล้ายคลึง / การจัดอันดับโดยประมาณ');
  const feedbackDisabled=d.feedback?'disabled':'';
  $('#result').innerHTML=`<div class="result-main"><article class="card"><span class="badge">${esc(d.level)}</span><h2 class="result-title">${esc(d.name_th)}</h2><div class="thai">${esc(d.name)}</div><p class="muted">${esc(d.type||'Unknown')} · ${esc(d.category||'อื่น ๆ')}</p><div class="score">${esc(d.score_percent)}%</div><p class="muted">${scoreLabel}</p>${d.memory?`<div class="note good">🧠 ${d.memory.match==='exact'?'ระบบจำภาพนี้จาก feedback เดิมแล้ว':'ระบบพบตัวอย่างที่เคยเรียนรู้และนำมาช่วยตัดสินใจ'} (${Math.round((d.memory.similarity||0)*100)}%)</div>`:''}${d.memory_hint?`<div class="note">🧠 มีตัวอย่างที่เคยเรียนรู้ใกล้เคียง (${Math.round((d.memory_hint.similarity||0)*100)}%) แต่ยังยึดผลจากโมเดลเป็นหลัก</div>`:''}<div class="detail"><h4>คำอธิบายผลจาก AI</h4><p>${d.name==='Unknown'?'ผลลัพธ์ยังไม่ชัดเจนพอ ระบบจึงไม่ควรยืนยันชื่ออุปกรณ์':`ผลลัพธ์นี้มาจากการตรวจจับและเปรียบเทียบลักษณะภาพกับข้อมูลที่โมเดลเรียนรู้ (${esc(d.engine)}).`}</p><h4>รายละเอียด</h4><p>${esc(d.description)}</p><h4>การใช้งาน</h4><p>${esc(d.uses)}</p><h4>สเปก</h4><p>${esc(d.specs)}</p><h4>ข้อควรระวัง</h4><p>${esc(d.safety)}</p></div></article><article class="card"><div class="card-head"><div><h3>อุปกรณ์ที่ตรวจพบ</h3><p>พบ ${esc(ca.component_count||0)} ชิ้น · ${esc(d.processing_time_ms||'—')} ms</p></div><span class="live-badge">${esc(d.engine)}</span></div>${det||preds||'<div class="empty-state">ไม่พบผลลัพธ์เพิ่มเติม</div>'}<div class="circuit"><h3>ความสัมพันธ์ของวงจรที่เป็นไปได้</h3>${circuits?`<ul class="possible-list">${circuits}</ul>`:'<p class="muted">ยังไม่มีรูปแบบวงจรที่เฉพาะเจาะจง</p>'}${notes}<small class="muted">${esc(ca.disclaimer||'')}</small></div><div class="feedback-box"><b>ผลลัพธ์นี้ถูกต้องหรือไม่?</b><div class="feedback-actions"><button class="secondary" id="feedbackYes" data-feedback="yes" type="button" ${feedbackDisabled}>✓ AI ทายถูก</button><button class="secondary" id="feedbackNo" data-feedback="no" type="button" ${feedbackDisabled}>✕ AI ทายผิด</button></div><div id="feedbackCorrection" class="feedback-correction hidden"></div><small id="feedbackStatus" class="muted" aria-live="polite">${d.feedback?'✓ มี Feedback สำหรับรายการนี้แล้ว':''}</small></div></article></div>`;
  $('#result').classList.remove('hidden');
  setupFeedbackSuggestions();
  if(d.feedback){ $('#feedbackYes')?.setAttribute('disabled','disabled'); $('#feedbackNo')?.setAttribute('disabled','disabled'); }
}

async function postFeedback(isCorrect, corrected=''){
  const aid=currentAnalysisId;
  const statusEl=$('#feedbackStatus');
  const correctionEl=$('#feedbackCorrection');
  const yes=$('#feedbackYes'), no=$('#feedbackNo'), submit=$('#submitCorrection');
  if(!aid){ toast('ไม่พบรหัสรายการวิเคราะห์ จึงบันทึก Feedback ไม่ได้','error'); return; }
  if(feedbackBusy)return;
  if(!isCorrect && !String(corrected||'').trim()){
    toast('กรุณาระบุชื่ออุปกรณ์ที่ถูกต้อง','error');
    $('#correctLabel')?.focus();
    return;
  }
  feedbackBusy=true;
  [yes,no,submit].forEach(x=>x?.setAttribute('disabled','disabled'));
  if(statusEl)statusEl.textContent='⏳ กำลังบันทึก Feedback และความจำของ AI...';
  try{
    const r=await fetch(`/api/feedback/${encodeURIComponent(aid)}`,{
      method:'POST',headers:{'Content-Type':'application/json','Accept':'application/json'},
      body:JSON.stringify({is_correct:isCorrect,corrected_label:String(corrected||'').trim()||null}),cache:'no-store'
    });
    const raw=await readApi(r);
    if(!r.ok)throw Error(apiMessage(raw,`บันทึก Feedback ไม่สำเร็จ (HTTP ${r.status})`));
    const data=apiData(raw)||{};
    if(statusEl)statusEl.textContent=isCorrect
      ? `✓ บันทึกสำเร็จ · AI จำภาพนี้แล้ว · ${new Date().toLocaleTimeString('th-TH')}`
      : `✓ บันทึกสำเร็จ · AI จำว่า “${corrected}” คือคำตอบที่ถูกต้อง · ส่งเข้าคิวพัฒนาโมเดล`;
    correctionEl?.classList.add('hidden');
    yes?.setAttribute('disabled','disabled'); no?.setAttribute('disabled','disabled');
    toast(isCorrect?'✓ AI จำภาพนี้แล้ว':'✓ AI จำคำตอบที่ถูกต้องแล้ว');
    if(data.training_queue?.requires_annotation && statusEl)statusEl.textContent+=' · ต้องตีกรอบวัตถุก่อนฝึก';
    loadDashboard(); loadLearningStats();
  }catch(e){
    feedbackBusy=false;
    [yes,no,submit].forEach(x=>x?.removeAttribute('disabled'));
    if(statusEl)statusEl.textContent='❌ บันทึกไม่สำเร็จ: '+e.message;
    toast(e.message,'error');
  } finally { feedbackBusy=false; }
}

function showCorrectionForm(){
  const el=$('#feedbackCorrection');
  if(!el)return;
  el.innerHTML=feedbackFormHtml();
  el.classList.remove('hidden');
  const input=$('#correctLabel');
  input?.focus();
  $('#cancelCorrection')?.addEventListener('click',()=>el.classList.add('hidden'),{once:true});
  $('#submitCorrection')?.addEventListener('click',()=>postFeedback(false,input?.value?.trim()||''),{once:true});
  input?.addEventListener('keydown',e=>{if(e.key==='Enter'){e.preventDefault();postFeedback(false,input.value.trim())}},{once:false});
}

async function setupFeedbackSuggestions(){
  try{
    if(!currentLibrary.length){
      const r=await fetch('/api/components?q=',{cache:'no-store',headers:{'Accept':'application/json'}});
      const payload=apiData(await readApi(r));
      currentLibrary=payload.items||[];
    }
    const list=$('#componentNames');
    if(list)list.innerHTML=currentLibrary.map(x=>`<option value="${esc(x.name)}">${esc(x.name_th)}</option>`).join('');
  }catch(e){/* free-text input still works */}
}

// ONE permanent delegated handler. It survives every innerHTML re-render and
// makes the two feedback buttons observable even if the result card is rebuilt.
document.addEventListener('click',e=>{
  const btn=e.target.closest?.('[data-feedback]');
  if(!btn)return;
  e.preventDefault();
  if(btn.dataset.feedback==='yes'){
    const status=$('#feedbackStatus');
    if(status)status.textContent='✓ รับคำสั่งแล้ว · กำลังบันทึกให้ AI จำ...';
    postFeedback(true);
  }else if(btn.dataset.feedback==='no'){
    showCorrectionForm();
    const status=$('#feedbackStatus');
    if(status)status.textContent='✎ เปิดช่องแก้ไขแล้ว · กรุณาระบุคำตอบที่ถูกต้อง';
  }
});

async function loadHistory(){try{const q=encodeURIComponent($('#historySearch').value||'');const period=$('#historyPeriod').value;const r=await fetch(`/api/history?q=${q}&period=${period}&page=${historyPage}&per_page=20`);const d=apiData(await readApi(r));if(!r.ok)throw Error(apiMessage(d));const items=d.items||[];$('#historyList').innerHTML=items.length?items.map(x=>`<article class="history-item"><img src="${esc(x.image_url)}" alt="${esc(x.component_th)}"><div><b>${esc(x.component_th)}</b><div class="muted">${esc(x.component)} · ${new Date(x.created_at).toLocaleString('th-TH')}</div><span class="badge">${esc(x.confidence)}% · ${esc(x.level)}</span></div><div class="history-actions"><button class="secondary" onclick="viewHistory('${esc(x.id)}')">ดู</button><button class="secondary" onclick="reanalyzeHistory('${esc(x.id)}')">วิเคราะห์ซ้ำ</button><button class="danger" onclick="deleteHistory('${esc(x.id)}')">ลบ</button></div></article>`).join('')+`<div class="pagination"><button class="secondary" ${d.page<=1?'disabled':''} onclick="historyPage=Math.max(1,historyPage-1);loadHistory()">‹ ก่อนหน้า</button><span class="muted">หน้า ${d.page}/${d.pages}</span><button class="secondary" ${d.page>=d.pages?'disabled':''} onclick="historyPage++;loadHistory()">ถัดไป ›</button></div>`:'<div class="empty-state">ยังไม่มีประวัติการวิเคราะห์</div>'}catch(e){showError('โหลดประวัติไม่สำเร็จ: '+e.message)}}
async function viewHistory(id){try{const r=await fetch('/api/history/'+encodeURIComponent(id));const raw=await readApi(r);if(!r.ok)throw Error(apiMessage(raw));const d=apiData(raw);activateTab('analyze');$('#preview').src=d.image_url;$('#previewName').textContent=d.filename||'ภาพจากประวัติ';$('#previewWrap').classList.remove('hidden');$('#dropzone').classList.add('hidden');renderQuality(d.quality);renderResult(d)}catch(e){showError(e.message)}}
async function reanalyzeHistory(id){if(!(await confirmAction('ระบบจะใช้ภาพต้นฉบับวิเคราะห์ใหม่ด้วยโมเดลปัจจุบัน และสร้างประวัติรายการใหม่','วิเคราะห์ซ้ำ?')))return;processing(true,1);try{const r=await fetch(`/api/history/${encodeURIComponent(id)}/reanalyze`,{method:'POST'});const raw=await readApi(r);if(!r.ok)throw Error(apiMessage(raw));const d=apiData(raw);activateTab('analyze');renderQuality(d.quality);renderResult(d);toast('วิเคราะห์ซ้ำเรียบร้อยแล้ว');loadHistory();loadDashboard()}catch(e){showError(e.message)}finally{processing(false)}}
async function deleteHistory(id){if(!(await confirmAction('ต้องการลบประวัติรายการนี้หรือไม่?','ยืนยันการลบ')))return;try{const r=await fetch('/api/history/'+encodeURIComponent(id),{method:'DELETE'});if(!r.ok)throw Error(apiMessage(await readApi(r)));toast('ลบประวัติเรียบร้อยแล้ว');loadHistory();loadDashboard()}catch(e){showError(e.message)}}
window.viewHistory=viewHistory;window.reanalyzeHistory=reanalyzeHistory;window.deleteHistory=deleteHistory;let histTimer;$('#historySearch').oninput=()=>{historyPage=1;clearTimeout(histTimer);histTimer=setTimeout(loadHistory,300)};$('#historyPeriod').onchange=()=>{historyPage=1;loadHistory()};

async function loadLibrary(){try{const q=encodeURIComponent($('#librarySearch').value||'');const c=encodeURIComponent($('#libraryCategory').value||'all');const r=await fetch(`/api/components?q=${q}&category=${c}`);const raw=await readApi(r);const d=apiData(raw);currentLibrary=d.items||[];const category=$('#libraryCategory');const current=category.value;if(category.options.length===1){(d.categories||[]).forEach(x=>category.insertAdjacentHTML('beforeend',`<option value="${esc(String(x).toLowerCase())}">${esc(x)}</option>`));category.value=current}const sort=$('#librarySort').value;const items=[...currentLibrary].sort((a,b)=>sort==='category'?String(a.category).localeCompare(String(b.category)):String(a.name_th).localeCompare(String(b.name_th)));$('#libraryCount').textContent=`${items.length} รายการอุปกรณ์`;$('#libraryGrid').innerHTML=items.length?items.map(x=>`<article class="library-card" tabindex="0" onclick="openComponent('${esc(encodeURIComponent(x.name))}')" onkeydown="if(event.key==='Enter')openComponent('${esc(encodeURIComponent(x.name))}')"><span>${esc(x.category||x.type||'อื่น ๆ')}</span><b>${esc(x.name_th)}</b><div class="en">${esc(x.name)}</div><p>${esc(x.description||'ยังไม่มีคำอธิบาย')}</p><div class="more">ดูรายละเอียด →</div></article>`).join(''):'<div class="empty-state">ไม่พบอุปกรณ์ที่ตรงกับการค้นหา</div>'}catch(e){showError('โหลดคลังอุปกรณ์ไม่สำเร็จ')}}
async function openComponent(encoded){try{const name=decodeURIComponent(encoded);const r=await fetch('/api/components/'+encodeURIComponent(name));const raw=await readApi(r);if(!r.ok)throw Error(apiMessage(raw));const d=apiData(raw).item||apiData(raw);const blocks=[['คำอธิบาย',d.description],['การใช้งานทั่วไป',d.uses||d.usage],['ข้อมูลจำเพาะ',typeof d.specs==='object'?JSON.stringify(d.specs,null,2):d.specs],['ข้อควรระวัง',d.safety],['ตัวอย่างการใช้งาน',d.example],['ประเภท / หมวดหมู่',`${d.type||'—'} / ${d.category||'—'}`]].filter(x=>x[1]);$('#modalContent').innerHTML=`<p class="eyebrow">รายละเอียดอุปกรณ์</p><h2 id="modalTitle">${esc(d.name_th||d.name)}</h2><p class="muted">${esc(d.name||'')}</p><div class="detail-grid">${blocks.map(([h,v])=>`<div class="detail-block"><h4>${esc(h)}</h4><p>${esc(v)}</p></div>`).join('')}</div>`;$('#modalRoot').classList.remove('hidden')}catch(e){showError(e.message)}}
window.openComponent=openComponent;$('#librarySearch').oninput=()=>loadLibrary();$('#libraryCategory').onchange=()=>loadLibrary();$('#librarySort').onchange=()=>loadLibrary();

function renderDaily(rows){const root=$('#dailyChart');if(!rows?.length){root.className='bar-chart empty-chart';root.innerHTML='';return}const max=Math.max(...rows.map(x=>x.n),1);root.className='bar-chart';root.innerHTML=rows.map(x=>`<div class="chart-column" title="${esc(x.day)}: ${esc(x.n)}"><i style="height:${Math.max(6,(x.n/max)*100)}%"></i><span>${esc(x.day.slice(5))}</span></div>`).join('')}
function renderDistribution(rows){const root=$('#confidenceChart');const order=['85-100','70-84','50-69','0-49'];const map=Object.fromEntries((rows||[]).map(x=>[x.bucket,x.n]));const max=Math.max(...Object.values(map),1);root.innerHTML=order.map(k=>`<div class="dist-row"><span>${k}%</span><div class="dist-track"><i style="width:${((map[k]||0)/max)*100}%"></i></div><b>${map[k]||0}</b></div>`).join('')}
async function loadDashboard(){try{const r=await fetch('/api/dashboard',{cache:'no-store'});const raw=await readApi(r);const d=apiData(raw);$('#dashTotal').textContent=d.total_analyses??'—';$('#dashToday').textContent=`วันนี้ ${d.today_analyses??0} · 7 วัน ${d.week_analyses??0}`;$('#dashAvg').textContent=`${d.average_confidence??0}%`;$('#dashSuccess').textContent=`${d.success_rate??0}%`;$('#dashLow').textContent=`ความมั่นใจต่ำ ${d.low_confidence_rate??0}%`;$('#dashTime').textContent=d.average_processing_time_ms?`${Math.round(d.average_processing_time_ms)} ms`:'—';$('#dashMost').textContent=d.most_detected?`พบมากที่สุด · ${d.most_detected.name_th}`:'ยังไม่มีอุปกรณ์ที่พบมากที่สุด';renderDaily(d.daily);renderDistribution(d.confidence_distribution);$('#topComponents').innerHTML=(d.top_components||[]).length?d.top_components.map((x,i)=>`<div class="rank-row"><span class="rank-no">0${i+1}</span><span>${esc(x.result_name_th)}</span><b>${esc(x.n)}</b></div>`).join(''):'<div class="empty-state">ยังไม่มีข้อมูล</div>';$('#recentAnalyses').innerHTML=(d.recent||[]).length?d.recent.map(x=>`<div class="recent-row"><img class="recent-thumb" src="${esc(x.image_url)}" alt=""><div><b>${esc(x.result_name_th)}</b><small>${new Date(x.created_at).toLocaleString('th-TH')}</small></div><span class="badge">${esc(x.confidence)}%</span></div>`).join(''):'<div class="empty-state">ยังไม่มีข้อมูล</div>'}catch(e){console.error(e)}}
$('#refreshDashboard').onclick=()=>{loadDashboard();toast('รีเฟรช แดชบอร์ด แล้ว')};

async function loadLearningStats(){
  const root=$('#learningStats');
  if(!root)return;
  try{
    const r=await fetch('/api/learning/stats',{cache:'no-store'});
    const d=apiData(await readApi(r));
    root.innerHTML=`<div class="learning-stat"><b>🧠 ${esc(d.memory_examples??0)}</b><small>ตัวอย่างที่ AI จำแล้ว</small></div><div class="learning-stat"><b>✓ ${esc(d.correct??0)}</b><small>ยืนยันว่าทายถูก</small></div><div class="learning-stat"><b>↻ ${esc(d.corrections??0)}</b><small>ตัวอย่างที่แก้ไข</small></div><div class="learning-stat"><b>📚 ${esc(d.queue_pending??0)}</b><small>รอตรวจสอบก่อนฝึก</small></div><div class="learning-stat"><b>🏷 ${esc(d.queue_ready_for_training??0)}</b><small>มีกรอบพร้อมฝึก</small></div><div class="learning-stat"><b>✎ ${esc(d.queue_requires_annotation??0)}</b><small>ต้องตีกรอบเพิ่ม</small></div>`;
  }catch(e){root.innerHTML='<div class="empty-state">โหลดสถานะการเรียนรู้ไม่สำเร็จ</div>'}
}

async function loadModels(){const root=$('#modelCards');try{const r=await fetch('/api/models',{cache:'no-store'});const raw=await readApi(r);const d=apiData(raw);const cards=[['ตัวตรวจจับ YOLO',d.yolo?.available?'พร้อมใช้งาน':'ไม่พร้อมใช้งาน',d.yolo?.path||'ไม่พบไฟล์โมเดล'],['การตรวจสอบด้วย CLIP',d.clip?.available?'พร้อมใช้งาน':'ยังไม่ได้โหลด',d.clip?.name||'โหมดสำรองเมื่อออฟไลน์'],['สภาพแวดล้อมการทำงาน',d.device||'CPU',`${d.classes??0} คลาส · ชุดข้อมูล ${d.dataset_version||'—'}`]];root.innerHTML=cards.map(([t,v,p])=>`<article class="model-card"><small>${esc(t)}</small><b>${esc(v)}</b><p>${esc(p)}</p></article>`).join('')}catch(e){root.innerHTML='<div class="empty-state">โหลดข้อมูลโมเดลไม่สำเร็จ</div>'}}
$('#refreshModels').onclick=()=>{loadModels();loadLearningStats()};

function closeModal(){$('#modalRoot').classList.add('hidden')}$('#modalClose').onclick=closeModal;$('#modalRoot').onclick=e=>{if(e.target===$('#modalRoot'))closeModal()};
const menu=$('#mobileMenu');menu?.addEventListener('click',()=>{$('#sidebar').classList.add('mobile-open');$('#sidebarOverlay').classList.add('show')});$('#sidebarClose').onclick=()=>{ $('#sidebar').classList.remove('mobile-open');$('#sidebarOverlay').classList.remove('show')};$('#sidebarOverlay').onclick=()=>{ $('#sidebar').classList.remove('mobile-open');$('#sidebarOverlay').classList.remove('show')};
const theme=$('#themeToggle'); function setTheme(mode){const light=mode==='light';document.body.classList.toggle('light-preview',light);document.documentElement.style.colorScheme=light?'light':'dark';theme.textContent=light?'☀':'☾';theme.setAttribute('aria-label',light?'เปลี่ยนเป็นโหมดมืด':'เปลี่ยนเป็นโหมดสว่าง');document.querySelector('meta[name=theme-color]')?.setAttribute('content',light?'#f7f9fc':'#07111f');try{localStorage.setItem('electronics-ai-theme',mode)}catch{}} let saved='dark';try{saved=localStorage.getItem('electronics-ai-theme')||'dark'}catch{} setTheme(saved); theme.onclick=()=>setTheme(document.body.classList.contains('light-preview')?'dark':'light');
const membersModal=$('#membersModal'); const membersBtn=$('#membersBtn'); const membersClose=$('#membersClose'); function openMembers(){membersModal?.classList.remove('hidden');document.body.style.overflow='hidden'} function closeMembers(){membersModal?.classList.add('hidden');document.body.style.overflow=''} membersBtn?.addEventListener('click',openMembers); membersClose?.addEventListener('click',closeMembers); membersModal?.addEventListener('click',e=>{if(e.target===membersModal)closeMembers()});
document.addEventListener('keydown',e=>{if(e.key==='Escape'){closeModal();closeMembers()}});
status();loadDashboard();loadLearningStats();
