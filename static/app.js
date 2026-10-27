const $ = (id) => document.getElementById(id);
let selectedFile = null;
let selectedTab = 'video';
let toastTimer;
let uploadedFilename = null;
let knownAllocationIds = new Set();
let initialAllocationCheck = true;
function toast(message){const el=$('toast');el.textContent=message;el.classList.add('show');clearTimeout(toastTimer);toastTimer=setTimeout(()=>el.classList.remove('show'),3500)}
function updateClock(){ $('clock').textContent = new Date().toLocaleTimeString(); }
updateClock(); setInterval(updateClock,1000);
$('dismiss-banner').addEventListener('click',()=>document.querySelector('.banner').remove());
document.querySelectorAll('.tab').forEach(btn=>btn.addEventListener('click',()=>{
  document.querySelectorAll('.tab').forEach(b=>b.classList.toggle('active',b===btn)); selectedTab=btn.dataset.tab;
  $('upload-pane').classList.toggle('hidden',selectedTab==='live'); $('live-pane').classList.toggle('hidden',selectedTab!=='live');
  $('media-file').accept=selectedTab==='image'?'image/jpeg,image/png':'video/*,.mkv';
  $('upload-btn').textContent=selectedTab==='live'?'Live source selected':'Upload file';
}));
$('go-settings').addEventListener('click',()=>document.querySelector('#integration').scrollIntoView({behavior:'smooth'}));
$('choose-file').addEventListener('click',()=>$('media-file').click());
$('dropzone').addEventListener('click',(e)=>{if(e.target.id!=='choose-file') $('media-file').click()});
$('dropzone').addEventListener('dragover',e=>{e.preventDefault();$('dropzone').style.borderColor='#4169ef'});
$('dropzone').addEventListener('dragleave',()=>{$('dropzone').style.borderColor=''});
$('dropzone').addEventListener('drop',e=>{e.preventDefault();$('dropzone').style.borderColor='';if(e.dataTransfer.files.length){setFile(e.dataTransfer.files[0])}});
$('media-file').addEventListener('change',e=>{if(e.target.files.length)setFile(e.target.files[0])});
function setFile(file){selectedFile=file;$('selected-file').textContent=`${file.name} · ${(file.size/1024/1024).toFixed(2)} MB`;$('preview-type').textContent=file.type.startsWith('image/')?'IMAGE SELECTED':'VIDEO SELECTED';const url=URL.createObjectURL(file);const preview=$('media-preview');preview.innerHTML='';let el;if(file.type.startsWith('image/')){el=document.createElement('img');el.alt='Selected image preview';el.src=url}else{el=document.createElement('video');el.controls=true;el.preload='metadata';el.src=url}preview.appendChild(el);$('analysis-status').textContent='Ready to upload';uploadedFilename=null;$('analyze-btn').disabled=true;$('analysis-results').classList.add('hidden')}
$('upload-btn').addEventListener('click',async()=>{if(selectedTab==='live'){toast('Live CCTV processing is not activated yet. Upload a clip for analysis.');return}if(!selectedFile){toast('Choose a video or image first.');return}const fd=new FormData();fd.append('file',selectedFile);$('upload-progress').classList.add('show');$('upload-message').textContent='Uploading…';$('upload-btn').disabled=true;$('analyze-btn').disabled=true;try{const res=await fetch('/api/upload',{method:'POST',body:fd});const data=await res.json();if(!res.ok)throw new Error(data.error||'Upload failed');uploadedFilename=data.filename;$('upload-message').textContent='Upload complete. Click Analyse media to run the detector.';$('analysis-status').textContent='Uploaded · ready for AI analysis';$('analyze-btn').disabled=false;toast('Upload saved. Ready to analyse.');await refreshEvents()}catch(err){$('upload-message').textContent=err.message;toast(err.message)}finally{$('upload-btn').disabled=false;$('upload-progress').querySelector('span').style.width='100%'}});
$('analyze-btn').addEventListener('click',async()=>{if(!uploadedFilename){toast('Upload the selected media first.');return}const btn=$('analyze-btn');btn.disabled=true;$('analysis-status').textContent='Analysing… this may take a while for long videos';$('upload-message').textContent='Running YOLO person detection on the server…';$('analysis-results').classList.add('hidden');try{const d=await postJSON('/api/analyze',{filename:uploadedFilename});const r=d.result;$('occupancy').textContent=r.peak_people_detected_in_frame;$('entries').textContent='—';$('exits').textContent='—';$('crowd-status').textContent=r.crowd_status;$('analysis-status').textContent=`Analysis complete in ${r.processing_seconds}s`;$('analysis-results').innerHTML=`<h3>Analysis results</h3><p><b>Peak people detected in one frame:</b> ${esc(r.peak_people_detected_in_frame)}</p><p><b>Frames sampled:</b> ${esc(r.frames_analyzed)} · <b>Processing time:</b> ${esc(r.processing_seconds)} sec</p><p><b>Crowd threshold:</b> ${esc(r.configured_limit)} · <b>Status:</b> ${esc(r.crowd_status)}</p><p>${esc(r.note)}</p><p><a href="${esc(r.output_url)}" target="_blank" rel="noopener">Open annotated ${r.media_type==='image'?'image':'video'}</a></p>`;$('analysis-results').classList.remove('hidden');$('upload-message').textContent='Analysis complete. Annotated output is available below.';if(d.alert_triggered){speakBilingual(`Warning. The crowd threshold was reached. ${r.peak_people_detected_in_frame} people were detected in one frame, and the configured threshold is ${r.configured_limit}. Please do not crowd the entrance.`,`எச்சரிக்கை. கூட்ட நெரிசல் வரம்பு எட்டப்பட்டுள்ளது. ஒரு காட்சியில் ${r.peak_people_detected_in_frame} பேர் கண்டறியப்பட்டனர். நுழைவாயிலில் கூட்டமாக நிற்க வேண்டாம்.`);toast('Crowd threshold detected. Announcement triggered.')}else{toast('Analysis completed. No crowd-threshold alert was triggered.')}await refreshEvents()}catch(e){$('analysis-status').textContent='Analysis failed';$('upload-message').textContent=e.message;toast(e.message)}finally{btn.disabled=false}});
async function postJSON(url,data){const r=await fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});const j=await r.json();if(!r.ok)throw new Error(j.error||'Request failed');return j}
$('save-settings').addEventListener('click',async()=>{try{const d=await postJSON('/api/settings',{max_passengers:$('passenger-limit').value,bus_id:$('bus-input').value,alert_at_limit:true});$('limit-caption').textContent='Configured limit: '+d.config.max_passengers;$('bus-id').textContent=d.config.bus_id;$('settings-result').textContent='Settings saved.';toast('Settings saved');await refreshEvents()}catch(e){$('settings-result').textContent=e.message;toast(e.message)}});
async function saveIntegration(button,fields){try{const data={max_passengers:$('passenger-limit').value,bus_id:$('bus-input').value};for(const [key,id] of Object.entries(fields)){const value=$(id).value;if(key!=='authority_api_token'||value.trim())data[key]=value}await postJSON('/api/settings',data);if(fields.authority_api_token)$('api-token').value='';toast('Integration settings saved');await refreshStatus();await refreshEvents()}catch(e){toast(e.message)}}
$('save-authority').addEventListener('click',()=>saveIntegration(null,{authority_webhook_url:'webhook-url',authority_api_token:'api-token'}));
$('save-iot').addEventListener('click',()=>saveIntegration(null,{iot_mode:'iot-mode',iot_endpoint:'iot-endpoint'}));
$('save-cctv').addEventListener('click',()=>saveIntegration(null,{cctv_source:'cctv-source'}));
function speakBilingual(en,ta){if(!$('announcements').checked){toast('Announcements are disabled in settings');return}if(!('speechSynthesis'in window)){toast('Browser text-to-speech is unavailable on this device');return}speechSynthesis.cancel();const first=new SpeechSynthesisUtterance(en);first.lang='en-IN';first.rate=.92;const second=new SpeechSynthesisUtterance(ta);second.lang='ta-IN';second.rate=.88;first.onend=()=>speechSynthesis.speak(second);speechSynthesis.speak(first)}
async function logAlert(type,message,level='warning'){try{await postJSON('/api/alert',{type,message,level});await refreshEvents()}catch(e){toast(e.message)}}
$('test-crowd').addEventListener('click',()=>{speakBilingual('This is a system audio test. No overcrowding has been detected.','இது ஒலி அமைப்பைச் சோதிக்கும் அறிவிப்பு. கூட்ட நெரிசல் கண்டறியப்படவில்லை.');toast('Audio test only; no crowd alert was created')});
$('test-door').addEventListener('click',()=>{speakBilingual('This is a door-warning audio test. No obstruction has been detected.','இது கதவு எச்சரிக்கை ஒலி சோதனை. கதவில் தடை எதுவும் கண்டறியப்படவில்லை.');toast('Audio test only; no obstruction alert was created')});
$('test-iot').addEventListener('click',async()=>{try{const d=await postJSON('/api/iot/test',{});toast(d.message);await refreshEvents()}catch(e){toast(e.message)}});
async function refreshEvents(){try{const r=await fetch('/api/events');if(!r.ok)throw new Error(`Could not load event history (HTTP ${r.status})`);const d=await r.json();const root=$('event-list');if(!d.events.length){root.innerHTML='<div class="empty-events">No events yet. Analyse media or run an audio test.</div>';return}root.innerHTML=d.events.map(e=>`<div class="event-row"><span class="event-dot ${esc(e.level)}"></span><div class="event-copy"><b>${esc(e.message)}</b><small>${esc(e.type)} · ${esc(e.timestamp)}</small></div><span class="event-level ${esc(e.level)}">${esc(e.level).toUpperCase()}</span><button class="event-delete" data-delete-event="${esc(e.id)}" title="Delete this event" aria-label="Delete event ${esc(e.type)}"><svg aria-hidden="true" viewBox="0 0 24 24"><path d="M3 6h18M8 6V4h8v2m3 0-1 14H6L5 6m4 4v6m6-6v6"/></svg></button></div>`).join('')}catch(e){console.error(e);toast(e.message)}}
$('event-list').addEventListener('click',async e=>{const btn=e.target.closest('[data-delete-event]');if(!btn)return;if(!confirm('Delete this history entry?'))return;btn.disabled=true;try{const r=await fetch('/api/events/'+encodeURIComponent(btn.dataset.deleteEvent),{method:'DELETE'});const d=await r.json();if(!r.ok)throw new Error(d.error||'Could not delete history entry');await refreshEvents();toast('History entry deleted')}catch(err){btn.disabled=false;toast(err.message)}});
$('clear-events').addEventListener('click',async()=>{if(!confirm('Clear all event history? This does not delete uploaded media.'))return;try{const r=await fetch('/api/events',{method:'DELETE'});if(!r.ok)throw new Error('Could not clear history');await refreshEvents();toast('Event history cleared')}catch(e){toast(e.message)}});
function esc(s){return String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}
async function refreshStatus(){try{const r=await fetch('/api/status');if(!r.ok)throw new Error(`Could not load integration status (HTTP ${r.status})`);const d=await r.json();$('authority-state').textContent=d.authority_configured?'ENDPOINT SAVED':'NOT CONFIGURED';$('authority-state').classList.toggle('ready',d.authority_configured);$('iot-state').textContent=d.iot_mode.toUpperCase()+' MODE';$('cctv-state').textContent=d.cctv_configured?'SOURCE SAVED':'NOT CONFIGURED';$('cctv-state').classList.toggle('ready',d.cctv_configured)}catch(e){console.error(e);toast(e.message)}}
$('refresh-events').addEventListener('click',refreshEvents);refreshStatus();
async function checkAuthorityAllocations(){
  try{
    const response=await fetch('/api/authority/allocations',{cache:'no-store'});
    if(!response.ok)throw new Error(`Authority notification check failed (HTTP ${response.status})`);
    const data=await response.json();
    const updates=Array.isArray(data.events)?data.events:[];
    if(!updates.length){initialAllocationCheck=false;return}
    const unseen=updates.filter(event=>!knownAllocationIds.has(event.id));
    updates.forEach(event=>knownAllocationIds.add(event.id));
    showAuthorityAllocation(updates[0]);
    if(!initialAllocationCheck&&unseen.length){
      const newest=unseen[0];
      toast(newest.type==='authority_bus_allocated'
        ? `Transport authority: bus allocated${newest.details.bus_id?` (${newest.details.bus_id})`:''}.`
        : `Transport authority: bus not allocated${newest.details.bus_id?` (${newest.details.bus_id})`:''}.`);
    }
    initialAllocationCheck=false;
  }catch(error){console.error(error)}
}
function showAuthorityAllocation(event){
  const allocated=event.type==='authority_bus_allocated';
  const notification=$('authority-notification');
  notification.classList.remove('hidden','allocated','not-allocated');
  notification.classList.add(allocated?'allocated':'not-allocated');
  $('authority-notification-icon').textContent=allocated?'✓':'!';
  $('authority-notification-title').textContent=allocated?'Bus allocated by transport authority':'Bus not allocated by transport authority';
  $('authority-notification-message').textContent=event.message;
  $('authority-notification-time').textContent=`Received ${new Date(event.timestamp).toLocaleString()}`;
}
checkAuthorityAllocations();
setInterval(checkAuthorityAllocations,10000);

$('reportForm').addEventListener('submit', async (e) => {
    e.preventDefault();

    const form = $('reportForm');
    const button = form.querySelector('button[type="submit"]');
    const msg = $('reportMsg');
    const payload = {
        vehicle_id: $('reportVehicle').value.trim(),
        route: $('reportRoute').value.trim(),
        event_type: $('reportType').value,
        severity: $('reportSeverity').value,
        stop_name: $('reportLocation').value.trim(),
        occupancy: $('reportOccupancy').value || null,
        message: $('reportMessage').value.trim(),
        source: 'driver'
    };

    button.disabled = true;
    msg.style.color = '#ad6b0b';
    msg.textContent = 'Sending report to the configured transport authority...';

    try {
        const response = await fetch('/api/driver-report', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(payload)
        });

        const data = await response.json().catch(() => null);

        if (!response.ok) {
            const receipt = data && data.alert_id != null
                ? ` Local record #${data.alert_id}.`
                : '';
            throw new Error(`${data && data.error ? data.error : `Request failed (HTTP ${response.status}).`}${receipt}`);
        }

        if (!data || data.alert_id == null) {
            throw new Error(
                'Server responded without an alert ID. Report receipt is unconfirmed.'
            );
        }

        msg.style.color = '#07875f';
        msg.textContent =
            `SUCCESS: Report accepted by authority. Alert ID: #${data.alert_id}`;

        form.reset();
        await Promise.all([loadAlertLogs(), refreshEvents()]);

    } catch (error) {
        msg.style.color = 'red';
        msg.textContent = `NOT SUCCESSFUL: ${error.message || 'Unknown connection error.'}`;

        console.error('Driver report error:', error);
        await Promise.all([loadAlertLogs(), refreshEvents()]);

    } finally {
        button.disabled = false;
    }
});



async function loadAlertLogs() {
    const tbody = document.getElementById('alertLogRows');

    try {
        const response = await fetch('/api/alert-logs');

        if (!response.ok) {
            throw new Error(`Log API returned HTTP ${response.status}`);
        }

        const data = await response.json();
        const logs = data.logs;

        if (!Array.isArray(logs) || !logs.length) {
            tbody.innerHTML =
                '<tr><td colspan="5">No alert logs recorded yet.</td></tr>';
            return;
        }

        tbody.innerHTML = logs.map(log => `
            <tr>
                <td>${esc(new Date(log.timestamp).toLocaleString())}</td>
                <td>${esc(log.vehicle_id || '—')}</td>
                <td>${esc(log.event_type || '—')}</td>
                <td>${esc(log.result)}</td>
                <td>${esc(log.error || '—')}</td>
            </tr>
        `).join('');

    } catch (error) {
        console.error('Could not load alert logs:', error);
        tbody.innerHTML =
            `<tr><td colspan="5">${esc(error.message)}</td></tr>`;
    }
}

loadAlertLogs();
