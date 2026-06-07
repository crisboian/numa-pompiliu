/* NUMA Capture — Application JavaScript */
const API = '';
let sessionId = null;
let isLoading = false;
let selectedCat = 'decision';
let selectedTags = [];
const phaseColors = {A:'#3b82f6',B:'#f59e0b',C:'#22c55e',D:'#a855f7',E:'#ef4444'};
const phaseNames = {A:'Role Mapping',B:'Incidentes Críticos',C:'Verificación Inversa',D:'Lo No Escrito',E:'Conocimiento Negativo'};

function autoResize(el){el.style.height='auto';el.style.height=Math.min(el.scrollHeight,100)+'px'}
function handleKey(e){if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();sendAnswer()}}

/* ── TABS ── */
function switchTab(tab){
  document.querySelectorAll('.tab').forEach(t=>t.classList.toggle('active',t.dataset.tab===tab));
  ['interview','shadow','graph','history','rag','comparativa'].forEach(t=>document.getElementById('screen-'+t).classList.toggle('active',t===tab));
  if(tab==='shadow')loadShadow();
  if(tab==='graph')renderForceGraph();
  if(tab==='history')loadHistory();
  if(tab==='rag')loadRAG();
  if(tab==='comparativa')loadComparativa();
}

/* ── SESSION ── */
async function startSession(){
  const name=document.getElementById('input-name').value.trim()||'Experto';
  const role=document.getElementById('input-role').value.trim()||'Senior';
  const domain=document.getElementById('input-domain').value.trim()||'General';
  const org=document.getElementById('input-org').value.trim();
  try{
    const r=await fetch(API+'/api/sessions',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({expert_name:name,expert_role:role,domain,organization:org})});
    const d=await r.json();sessionId=d.id;
    localStorage.setItem('numa_session_id', sessionId);
    localStorage.setItem('numa_session_name', name);
    localStorage.setItem('numa_started_at', Date.now().toString());
    await startInterview();
  }catch(e){showToast('Error: '+e.message,'error')}
}
async function startInterview(){
  try{
    const r=await fetch(API+'/api/sessions/'+sessionId+'/start',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});
    const d=await r.json();
    document.getElementById('screen-setup').classList.remove('active');
    document.getElementById('screen-interview-active').classList.add('active');
    renderMessages(d.messages||[]);updatePhaseBar(d.current_phase,d);enableInput(true);
    document.getElementById('header-sub').textContent=d.expert_name;
  }catch(e){showToast('Error: '+e.message,'error')}
}
async function sendAnswer(){
  const input=document.getElementById('chat-input');
  const text=input.value.trim();
  if(!text||isLoading)return;
  addMessage({role:'user',content:text,phase:''});
  input.value='';input.style.height='auto';enableInput(false);showTyping();
  try{
    const r=await fetch(API+'/api/sessions/'+sessionId+'/answer',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({answer:text})});
    const d=await r.json();removeTyping();
    if(d.status==='completed'){showCompletion(d);return}
    const msgs=d.messages||[];const last=msgs[msgs.length-1];
    if(last&&last.role==='assistant')addMessage(last);
    updatePhaseBar(d.current_phase,d);enableInput(true);
  }catch(e){removeTyping();addMessage({role:'assistant',content:'Error de conexión. Intenta de nuevo.',phase:''});enableInput(true)}
}

/* ── CHAT RENDER ── */
function renderMessages(msgs){
  const c=document.getElementById('chat-msgs');c.innerHTML='';
  msgs.forEach(m=>{if(m.role==='assistant'||m.role==='user')c.appendChild(createMsgEl(m))});
  scrollBottom();
}
function addMessage(msg){document.getElementById('chat-msgs').appendChild(createMsgEl(msg));scrollBottom()}
function createMsgEl(msg){
  const el=document.createElement('div');el.className='msg '+msg.role;let html='';
  if(msg.phase&&phaseColors[msg.phase]){
    html+='<div class="mp" style="color:'+phaseColors[msg.phase]+'">Fase '+msg.phase+' · '+(phaseNames[msg.phase]||'')+'</div>';
  }
  let s=(msg.content||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
  s=s.replace(/\*\*(.*?)\*\*/g,'<strong>$1</strong>');
  s=s.replace(/\*(.*?)\*/g,'<em>$1</em>');
  s=s.replace(/```(\w*)\n([\s\S]*?)```/g,'<pre><code>$2</code></pre>');
  s=s.replace(/`([^`]+)`/g,'<code>$1</code>');
  s=s.replace(/\n/g,'<br>');
  html+='<div>'+s+'</div>';el.innerHTML=html;return el;
}
function showTyping(){
  const c=document.getElementById('chat-msgs');
  const el=document.createElement('div');el.className='msg assistant';el.id='typing-el';
  el.innerHTML='<div class="typing"><span></span><span></span><span></span></div>';
  c.appendChild(el);scrollBottom();
}
function removeTyping(){const el=document.getElementById('typing-el');if(el)el.remove()}
function scrollBottom(){const c=document.getElementById('chat-msgs');c.scrollTop=c.scrollHeight}
function updatePhaseBar(cp,data){
  const phases=['A','B','C','D','E'];
  document.querySelectorAll('.phase-step').forEach(el=>{
    el.classList.remove('active','done');
    const idx=phases.indexOf(el.dataset.phase);
    if(idx<phases.indexOf(cp))el.classList.add('done');
    else if(el.dataset.phase===cp&&data.status!=='completed')el.classList.add('active');
  });
}
function enableInput(enabled){
  isLoading=!enabled;
  document.getElementById('chat-input').disabled=!enabled;
  document.getElementById('chat-send').disabled=!enabled;
  if(enabled)document.getElementById('chat-input').focus();
}
async function showCompletion(data){
  document.getElementById('screen-interview-active').classList.remove('active');
  document.getElementById('screen-completion').classList.add('active');
  document.getElementById('stat-items').textContent=(data.knowledge_items||[]).length;
  try{const r=await fetch(API+'/api/sessions/'+sessionId+'/export');const ed=await r.json();document.getElementById('stat-items').textContent=(ed.knowledge_items||[]).length}catch(e){}
}
async function exportSession(){
  try{const r=await fetch(API+'/api/sessions/'+sessionId+'/export');const d=await r.json();const b=new Blob([JSON.stringify(d,null,2)],{type:'application/json'});const u=URL.createObjectURL(b);const a=document.createElement('a');a.href=u;a.download='numa-capture-'+sessionId.slice(0,8)+'.json';a.click();URL.revokeObjectURL(u)}catch(e){showToast('Error: '+e.message,'error')}
}
function resetSession(){
  sessionId=null;document.getElementById('chat-msgs').innerHTML='';
  document.getElementById('screen-completion').classList.remove('active');
  document.getElementById('screen-setup').classList.add('active');
  document.getElementById('header-sub').textContent='Entrevista Experto';
  ['input-name','input-role','input-domain','input-org'].forEach(id=>document.getElementById(id).value='');
  localStorage.removeItem('numa_session_id');
  localStorage.removeItem('numa_session_name');
  localStorage.removeItem('numa_started_at');
  document.getElementById('continue-session').style.display='none';
}

/* ── LOCALSTORAGE SESSION ── */
function checkStoredSession(){
  const sid=localStorage.getItem('numa_session_id');
  if(!sid)return;
  const name=localStorage.getItem('numa_session_name')||'?';
  document.getElementById('continue-info').textContent='Entrevista de '+name+' — ID: '+sid.slice(0,8)+'...';
  document.getElementById('continue-session').style.display='block';
}
async function continueSession(){
  const sid=localStorage.getItem('numa_session_id');
  if(!sid)return;
  sessionId=sid;
  try{
    const r=await fetch(API+'/api/sessions/'+sid);
    if(!r.ok){clearStoredSession();return}
    const d=await r.json();
    if(d.status==='completed'||d.status==='pending'){clearStoredSession();return}
    document.getElementById('screen-setup').classList.remove('active');
    document.getElementById('screen-interview-active').classList.add('active');
    renderMessages(d.messages||[]);updatePhaseBar(d.current_phase,d);enableInput(true);
    document.getElementById('header-sub').textContent=d.expert_name;
  }catch(e){console.warn('Continue failed:',e);clearStoredSession()}
}
function clearStoredSession(){
  localStorage.removeItem('numa_session_id');
  localStorage.removeItem('numa_session_name');
  localStorage.removeItem('numa_started_at');
  document.getElementById('continue-session').style.display='none';
}

/* ── SHADOW ── */
function openShadowModal(){document.getElementById('modal-shadow').classList.add('active');document.getElementById('shadow-content').focus()}
function closeShadowModal(){document.getElementById('modal-shadow').classList.remove('active')}
function selectCat(el){
  document.querySelectorAll('#shadow-cats .cat-btn').forEach(b=>b.classList.remove('active'));
  el.classList.add('active');selectedCat=el.dataset.cat;
}
function selectTag(el){
  const tag=el.dataset.tag;
  if(!tag)return;
  el.classList.toggle('active');
  if(selectedTags.includes(tag)){selectedTags=selectedTags.filter(t=>t!==tag)}
  else{selectedTags.push(tag)}
}
async function saveShadow(){
  const content=document.getElementById('shadow-content').value.trim();
  if(!content){showToast('Escribe algo primero','error');return}
  const context=document.getElementById('shadow-context').value.trim();
  try{
    const r=await fetch(API+'/api/shadow',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({content,category:selectedCat,context,tags:selectedTags.join(','),session_id:sessionId,expert_name:localStorage.getItem('numa_session_name')||''})});
    const d=await r.json();
    if(d.status==='ok'){
      document.getElementById('shadow-content').value='';
      document.getElementById('shadow-context').value='';
      selectedTags=[];selectedCat='decision';
      document.querySelectorAll('#shadow-cats .cat-btn').forEach(b=>b.classList.remove('active'));
      document.querySelector('#shadow-cats .cat-btn').classList.add('active');
      document.querySelectorAll('[data-tag]').forEach(b=>b.classList.remove('active'));
      closeShadowModal();
      loadShadow();
      showToast('✅ Captura guardada','success');
    }
  }catch(e){showToast('Error: '+e.message,'error')}
}
async function loadShadow(){
  try{
    const r=await fetch(API+'/api/shadow');const d=await r.json();
    const s=await fetch(API+'/api/shadow/stats');const st=await s.json();
    document.getElementById('shadow-stats').innerHTML=`
      <span style="font-size:13px;color:var(--txt2)">📊 Hoy: <strong style="color:var(--accent2)">${st.today}</strong></span>
      <span style="font-size:13px;color:var(--txt2)">Total: <strong style="color:var(--txt)">${st.total}</strong></span>
      ${Object.entries(st.categories).map(([k,v])=>`<span style="font-size:12px;color:var(--txt3);background:var(--bg3);padding:2px 10px;border-radius:20px;border:1px solid var(--border)">${k}: ${v}</span>`).join('')}
    `;
    const list=document.getElementById('shadow-list');
    if(!d.entries||d.entries.length===0){list.innerHTML='<p style="color:var(--txt3);font-size:13px;text-align:center;padding:20px">Sin capturas todavía</p>';return}
    list.innerHTML=d.entries.map(e=>`
      <div style="background:var(--bg3);border:1px solid var(--border);border-radius:var(--rs);padding:12px;margin-bottom:8px">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px">
          <span style="font-size:11px;color:var(--txt3)">${new Date(e.created_at).toLocaleString('es-ES')}</span>
          <span style="font-size:11px;padding:2px 8px;border-radius:10px;background:var(--bg4);color:var(--txt2)">${e.category||'?'}</span>
        </div>
        <div style="font-size:14px;color:var(--txt)">${escapeHtml(e.content)}</div>
        ${e.context?`<div style="font-size:12px;color:var(--txt3);margin-top:4px">📎 ${escapeHtml(e.context)}</div>`:''}
        ${e.tags&&e.tags.length?`<div style="margin-top:6px;display:flex;gap:4px;flex-wrap:wrap">${e.tags.map(t=>`<span style="font-size:10px;padding:2px 8px;border-radius:10px;background:var(--bg4);color:var(--accent2)">${t}</span>`).join('')}</div>`:''}
      </div>
    `).join('');
  }catch(e){console.warn('Shadow load error:',e)}
}

/* ── INDUSTRIAL GRAPH ── */

async function renderForceGraph() {
  const container = document.getElementById('graph-viz-container');
  const emptyEl = document.getElementById('graph-empty');
  const svgEl = document.getElementById('graph-svg');
  const legendEl = document.getElementById('graph-legend');
  const tooltipEl = document.getElementById('graph-tooltip');

  // Show spinner, hide empty state
  if (emptyEl) emptyEl.style.display = 'none';
  svgEl.style.display = 'block';
  container.innerHTML = '<div class="spinner"><div class="sp-dot"></div><div class="sp-dot"></div><div class="sp-dot"></div><span class="spinner-text">Generating graph...</span></div>';

  try {
    const r = await fetch(API + '/api/industrial/graph');
    const d = await r.json();

    if (!d.entities || d.entities.length === 0) {
      container.innerHTML = '';
      if (emptyEl) emptyEl.style.display = 'block';
      svgEl.style.display = 'none';
      return;
    }

    // Entity type colors (gold-inspired palette)
    const typeColors = {
      machine: '#3b82f6', procedure: '#22c55e', incident: '#ef4444',
      safety_rule: '#f59e0b', regulation: '#a855f7', role: '#ec4899',
      material: '#14b8a6', tool: '#f97316', alarm: '#eab308',
      area: '#06b6d4', risk: '#8b5cf6'
    };
    const typeLabels = {
      machine: 'Machine', procedure: 'Procedure', incident: 'Incident',
      safety_rule: 'Safety', regulation: 'Regulation', role: 'Role',
      material: 'Material', tool: 'Tool', alarm: 'Alarm',
      area: 'Area', risk: 'Risk'
    };

    const nodes = d.entities.map(e => ({
      id: e.id, name: e.name || e.id,
      type: e.entity_type, description: e.description,
      session_id: e.session_id, attributes: e.attributes
    }));

    const links = d.relations.map(r => ({
      source: r.source_id, target: r.target_id,
      type: r.relation_type, weight: r.weight || 1,
      notes: r.notes
    }));

    // Compute degree
    const degree = {};
    nodes.forEach(n => degree[n.id] = 0);
    links.forEach(l => {
      if (degree[l.source] !== undefined) degree[l.source]++;
      if (degree[l.target] !== undefined) degree[l.target]++;
    });
    const maxDeg = Math.max(...Object.values(degree), 1);

    const width = container.clientWidth || 800;
    const height = 500;

    // Rebuild container with SVG
    container.innerHTML = `
      <svg id="graph-svg" width="100%" height="${height}" style="display:block;background:var(--bg);border-radius:8px"></svg>
      <div id="graph-tooltip" style="display:none;position:absolute;pointer-events:none;background:rgba(15,21,37,0.95);color:var(--text);padding:10px 14px;border-radius:8px;border:1px solid var(--border-strong);font-size:13px;box-shadow:0 8px 32px rgba(0,0,0,0.5);z-index:100;max-width:280px;backdrop-filter:blur(12px)"></div>
      <div id="graph-legend" style="position:absolute;top:12px;right:12px;background:rgba(10,14,26,0.85);padding:10px 14px;border-radius:8px;border:1px solid var(--border);font-size:11px;font-family:var(--mono);color:var(--text-muted);line-height:1.8;backdrop-filter:blur(8px);letter-spacing:0.03em"></div>
    `;

    const svg = d3.select('#graph-svg');
    const tooltip = d3.select('#graph-tooltip');
    const legend = d3.select('#graph-legend');

    svg.attr('viewBox', [0, 0, width, height]);

    // --- Defs: gradients, filters, markers ---
    const defs = svg.append('defs');

    // Glow filter
    const filter = defs.append('filter').attr('id', 'glow');
    filter.append('feGaussianBlur').attr('stdDeviation', '3').attr('result', 'blur');
    const merge = filter.append('feMerge');
    merge.append('feMergeNode').attr('in', 'blur');
    merge.append('feMergeNode').attr('in', 'SourceGraphic');

    // Arrow marker
    defs.append('marker')
      .attr('id', 'arrow')
      .attr('viewBox', '0 -5 10 10')
      .attr('refX', 28)
      .attr('refY', 0)
      .attr('markerWidth', 6)
      .attr('markerHeight', 6)
      .attr('orient', 'auto')
      .append('path')
      .attr('d', 'M0,-4L8,0L0,4')
      .attr('fill', 'none')
      .attr('stroke', 'var(--text-dim)')
      .attr('stroke-width', '1.2');

    // Radial gradients per type
    Object.entries(typeColors).forEach(([t, c]) => {
      const grad = defs.append('radialGradient').attr('id', 'grad-' + t);
      grad.append('stop').attr('offset', '0%').attr('stop-color', c).attr('stop-opacity', 1);
      grad.append('stop').attr('offset', '70%').attr('stop-color', c).attr('stop-opacity', 0.85);
      grad.append('stop').attr('offset', '100%').attr('stop-color', c).attr('stop-opacity', 0.6);
    });

    // --- Zoom ---
    const g = svg.append('g');
    const zoom = d3.zoom()
      .scaleExtent([0.15, 5])
      .on('zoom', (event) => { g.attr('transform', event.transform); });
    svg.call(zoom);

    // --- Force simulation ---
    const simulation = d3.forceSimulation(nodes)
      .force('link', d3.forceLink(links).id(d => d.id).distance(150))
      .force('charge', d3.forceManyBody().strength(-400))
      .force('center', d3.forceCenter(width / 2, height / 2))
      .force('collision', d3.forceCollide().radius(d => 12 + (degree[d.id] / maxDeg) * 18));

    // --- Links (curved paths) ---
    const link = g.append('g').selectAll('path')
      .data(links).join('path')
      .attr('fill', 'none')
      .attr('stroke', 'var(--text-dim)')
      .attr('stroke-opacity', 0.25)
      .attr('stroke-width', d => Math.max(0.8, Math.min(2.5, (d.weight || 1) * 1.2)))
      .attr('marker-end', 'url(#arrow)');

    // Relation labels
    const linkLabel = g.append('g').selectAll('text')
      .data(links).join('text')
      .text(d => d.type.replace(/_/g, ' '))
      .attr('font-size', '8px')
      .attr('font-family', 'var(--mono)')
      .attr('fill', 'var(--text-dim)')
      .attr('text-anchor', 'middle')
      .attr('dy', -4)
      .style('pointer-events', 'none')
      .style('opacity', 0);

    // --- Nodes ---
    const node = g.append('g').selectAll('g')
      .data(nodes).join('g')
      .style('cursor', 'pointer');

    // Outer glow ring
    node.append('circle')
      .attr('r', d => 10 + (degree[d.id] / maxDeg) * 18)
      .attr('fill', d => 'url(#grad-' + d.type + ')')
      .attr('filter', 'url(#glow)')
      .attr('opacity', 0.6);

    // Inner solid circle
    node.append('circle')
      .attr('r', d => 7 + (degree[d.id] / maxDeg) * 14)
      .attr('fill', d => typeColors[d.type] || '#666')
      .attr('stroke', 'rgba(201,169,78,0.3)')
      .attr('stroke-width', 1.5)
      .style('transition', 'stroke 0.2s, stroke-width 0.2s');

    // Node label
    node.append('text')
      .text(d => d.name.length > 18 ? d.name.substring(0, 17) + '...' : d.name)
      .attr('dx', d => 12 + (degree[d.id] / maxDeg) * 16)
      .attr('dy', 4)
      .attr('font-size', '10px')
      .attr('font-family', 'var(--sans)')
      .attr('fill', 'var(--text-muted)')
      .style('pointer-events', 'none')
      .style('text-shadow', '0 1px 3px rgba(0,0,0,0.8)')
      .style('opacity', 0.85);

    // Hover/click on node groups
    node.on('mouseover', function(event, d) {
      d3.select(this).selectAll('circle').attr('stroke', 'var(--gold)').attr('stroke-width', 2.5);
      const rect = container.getBoundingClientRect();
      tooltip.style('display', 'block')
        .style('left', (event.clientX - rect.left + 14) + 'px')
        .style('top', (event.clientY - rect.top - 12) + 'px')
        .html('<strong style="color:var(--gold);font-family:var(--serif);font-size:14px">' + d.name + '</strong><br>' +
          '<span style="color:var(--text-muted);font-size:11px">' + (typeLabels[d.type] || d.type.replace(/_/g, ' ')) + '</span>' +
          (d.description ? '<br><span style="color:var(--text-dim);font-size:10px;line-height:1.4">' + d.description.substring(0, 120) + '</span>' : '') +
          '<br><span style="color:var(--gold);font-size:9px;font-family:var(--mono)">' + degree[d.id] + ' connections</span>');
    })
    .on('mousemove', function(event) {
      const rect = container.getBoundingClientRect();
      tooltip.style('left', (event.clientX - rect.left + 14) + 'px')
        .style('top', (event.clientY - rect.top - 12) + 'px');
    })
    .on('mouseout', function() {
      d3.select(this).selectAll('circle').attr('stroke', 'rgba(201,169,78,0.3)').attr('stroke-width', 1.5);
      tooltip.style('display', 'none');
    })
    .on('click', function(event, d) {
      event.stopPropagation();
      showEntityDetail(d);
    })
    .call(d3.drag()
      .on('start', dragstarted)
      .on('drag', dragged)
      .on('end', dragended));

    // --- Tick ---
    simulation.on('tick', () => {
      // Curved links: compute midpoint offset for bezier
      link.attr('d', d => {
        const dx = d.target.x - d.source.x;
        const dy = d.target.y - d.source.y;
        const dr = Math.sqrt(dx * dx + dy * dy) * 1.2;
        return 'M' + d.source.x + ',' + d.source.y +
          'A' + dr + ',' + dr + ' 0 0,1 ' + d.target.x + ',' + d.target.y;
      });

      // Relation labels at midpoint
      linkLabel.attr('x', d => (d.source.x + d.target.x) / 2)
        .attr('y', d => (d.source.y + d.target.y) / 2)
        .style('opacity', 0.6);

      // Nodes
      node.attr('transform', d => 'translate(' + d.x + ',' + d.y + ')');
    });

    // --- Drag ---
    function dragstarted(event, d) {
      if (!event.active) simulation.alphaTarget(0.3).restart();
      d.fx = d.x;
      d.fy = d.y;
    }
    function dragged(event, d) {
      d.fx = event.x;
      d.fy = event.y;
    }
    function dragended(event, d) {
      if (!event.active) simulation.alphaTarget(0);
      d.fx = null;
      d.fy = null;
    }

    // --- Legend ---
    const types = [...new Set(nodes.map(n => n.type))];
    legend.html(types.map(t =>
      '<div style="display:flex;align-items:center;gap:6px;padding:1px 0">' +
        '<span style="display:inline-block;width:10px;height:10px;border-radius:50%;background:' + (typeColors[t] || '#666') + ';box-shadow:0 0 6px ' + (typeColors[t] || '#666') + '"></span>' +
        '<span>' + (typeLabels[t] || t.replace(/_/g, ' ')) + '</span>' +
      '</div>'
    ).join(''));

    // Click background to reset zoom
    svg.on('click', function() {
      svg.transition().duration(500).call(zoom.transform, d3.zoomIdentity);
    });

    // Fade in animation
    node.attr('opacity', 0).transition().duration(600).attr('opacity', 1);
    link.attr('opacity', 0).transition().duration(800).attr('opacity', 1);

  } catch (e) {
    console.warn('Force graph error:', e);
    container.innerHTML = '<p style="color:var(--text-dim);text-align:center;padding:2rem">Error loading graph.</p>';
  }
}

function showEntityDetail(d) {
  const desc = d.description || 'Sin descripci\u00F3n';
  let extra = '';
  if (d.attributes && Object.keys(d.attributes).length > 0) {
    extra = ' \u2014 ' + Object.entries(d.attributes).map(([k, v]) => k + ': ' + v).join(' \u00B7 ');
  }
  showToast('\u{1F4CC} ' + d.name + ' (' + d.type.replace(/_/g, ' ') + ')' + extra, 'info', 5000);
}
function addQuickEntity(){document.getElementById('modal-entity').classList.add('active')}
function closeEntityModal(){document.getElementById('modal-entity').classList.remove('active')}
async function saveEntity(){
  const entity_type=document.getElementById('entity-type').value;
  const name=document.getElementById('entity-name').value.trim();
  const description=document.getElementById('entity-desc').value.trim();
  if(!name){showToast('Nombre requerido','error');return}
  try{
    const r=await fetch(API+'/api/industrial/entities',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({entity_type,name,description,session_id:sessionId})});
    if(r.ok){closeEntityModal();document.getElementById('entity-name').value='';document.getElementById('entity-desc').value='';renderForceGraph();showToast('Entity saved','success')}
  }catch(e){showToast('Error: '+e.message,'error')}
}

/* ── UTILITY ── */
function escapeHtml(text){
  const div=document.createElement('div');
  div.appendChild(document.createTextNode(text||''));
  return div.innerHTML;
}

/* ── HISTORY ── */
async function loadHistory(){
  showSpinner('history-list','Cargando historial...');
  try{
    const r=await fetch(API+'/api/sessions');
    if(!r.ok){document.getElementById('history-list').innerHTML='<p style="color:var(--red);font-size:13px;text-align:center;padding:20px">Error al cargar</p>';return}
    const d=await r.json();
    const sessions=(d.sessions||[]).filter(s=>s.message_count>0);
    const list=document.getElementById('history-list');
    if(sessions.length===0){
      list.innerHTML='<p style="color:var(--txt3);font-size:13px;text-align:center;padding:20px">No hay entrevistas todavía</p>';
      return;
    }
    list.innerHTML=sessions.map(s=>{
      const phaseDot=phaseColors[s.current_phase]||'var(--txt3)';
      const statusLabel=s.status==='completed'?'✅ Completada':s.status==='in_progress'?'⏳ En curso':'📝 Pendiente';
      return `
      <div class="history-card" onclick="viewSession('${s.id}')" style="background:var(--bg3);border:1px solid var(--border);border-radius:var(--rs);padding:14px;margin-bottom:10px;cursor:pointer;transition:border-color 0.2s" onmouseover="this.style.borderColor='var(--accent)'" onmouseout="this.style.borderColor='var(--border)'">
        <div style="display:flex;justify-content:space-between;align-items:start;margin-bottom:6px">
          <div>
            <strong style="font-size:15px;color:var(--txt2)">${escapeHtml(s.expert_name||'?')}</strong>
            <span style="font-size:13px;color:var(--txt3);margin-left:8px">${escapeHtml(s.expert_role||'')}</span>
          </div>
          <span style="font-size:11px;padding:2px 10px;border-radius:10px;background:var(--bg4);color:var(--accent2)">${statusLabel}</span>
        </div>
        <div style="font-size:12px;color:var(--txt3);margin-bottom:6px">
          ${s.organization?escapeHtml(s.organization)+' · ':''}${s.domain||''}
        </div>
        <div style="display:flex;gap:16px;font-size:12px;color:var(--txt2)">
          <span>💬 ${s.message_count||0} mensajes</span>
          <span>🧠 ${s.knowledge_count||0} items</span>
          <span>📌 Fase ${s.current_phase||'?'}</span>
        </div>
      </div>`
    }).join('');
  }catch(e){list.innerHTML='<p style="color:var(--red);font-size:13px">Error: '+e.message+'</p>'}
}

async function viewSession(sessionId){
  // Show session detail in a modal
  try{
    const r=await fetch(API+'/api/sessions/'+sessionId+'/export');
    if(!r.ok){showToast('Error al cargar sesión','error');return}
    const d=await r.json();
    const items=d.knowledge_items||[];
    const msgs=d.conversation||[];
    
    const catIcons={fact:'📌',judgment:'🤔',rule:'📋',pattern:'🔄',exception:'⚠️',heuristic:'💡',risk:'🚨',tip:'💪',anti_pattern:'🚫',condition:'🔗',tacit_knowledge:'🤫'};
    
    let html=`<div class="modal" style="max-width:700px;max-height:80vh;overflow-y:auto">
      <h3>📋 ${escapeHtml(d.expert.name)} <span style="font-size:13px;color:var(--txt3)">${escapeHtml(d.expert.role)}</span></h3>
      <p style="color:var(--txt2);font-size:13px">${d.expert.organization?'🏢 '+escapeHtml(d.expert.organization)+' · ':''}${d.expert.domain||''}</p>
      <p style="font-size:12px;color:var(--txt3);margin-bottom:12px">${items.length} items · ${msgs.length} mensajes · ${d.phases_completed} fases</p>`;
    
    if(items.length>0){
      html+=`<h4 style="font-size:14px;margin:12px 0 8px">🧠 Knowledge Items (${items.length})</h4>
      <div style="display:flex;flex-wrap:wrap;gap:4px;margin-bottom:12px">`;
      const cats={};items.forEach(i=>{cats[i.category]=cats[i.category]||0;cats[i.category]++});
      Object.entries(cats).forEach(([k,v])=>{html+=`<span style="font-size:11px;padding:2px 10px;border-radius:10px;background:var(--bg4);color:var(--accent2)">${k}: ${v}</span>`});
      html+=`</div>
      <div style="max-height:300px;overflow-y:auto">`;
      items.forEach((item,i)=>{
        html+=`<div style="padding:8px 10px;margin-bottom:6px;background:var(--bg4);border-radius:6px;border-left:3px solid ${item.weight>0.8?'var(--green)':'var(--accent2)'}">
          <div style="font-size:12px;color:var(--txt3);margin-bottom:2px">${catIcons[item.category]||'📌'} ${item.category} · peso ${item.weight}</div>
          <div style="font-size:13px;color:var(--txt)">${escapeHtml(item.statement)}</div>
          ${item.rationale?`<div style="font-size:11px;color:var(--txt3);margin-top:2px;font-style:italic">${escapeHtml(item.rationale)}</div>`:''}
        </div>`
      });
      html+=`</div>`;
    }
    
    html+=`
      <details style="margin-top:12px">
        <summary style="cursor:pointer;font-size:13px;color:var(--accent2)">📜 Ver conversación (${msgs.length} mensajes)</summary>
        <div style="max-height:300px;overflow-y:auto;margin-top:8px">`;
    msgs.forEach(m=>{
      const roleClass=m.role==='user'?'user':'assistant';
      html+=`<div style="padding:6px 10px;margin-bottom:4px;background:var(--bg3);border-radius:6px;border-left:3px solid ${m.role==='user'?'var(--accent)':'var(--accent2)'}">
        <div style="font-size:11px;color:var(--txt3);margin-bottom:2px">${m.role==='user'?'🧑':'🤖'} ${m.role} · Fase ${m.phase||'?'}</div>
        <div style="font-size:12px;color:var(--txt)">${escapeHtml((m.content||'').substring(0,200))}${(m.content||'').length>200?'...':''}</div>
      </div>`
    });
    html+=`</div></details>
      <div class="modal-actions" style="margin-top:12px">
        <button class="btn-s" onclick="closeViewModal()">Cerrar</button>
        <button class="btn-p btn-p-sm" onclick="downloadSessionData('${sessionId}')">📥 Descargar JSON</button>
      </div>
    </div>`;
    
    // Show in overlay
    let overlay=document.getElementById('modal-view');
    if(!overlay){
      overlay=document.createElement('div');overlay.id='modal-view';
      overlay.className='modal-overlay';overlay.onclick=function(e){if(e.target===this)closeViewModal()};
      document.body.appendChild(overlay);
    }
    overlay.innerHTML=html;
    overlay.classList.add('active');
  }catch(e){showToast('Error: '+e.message,'error')}
}

function closeViewModal(){
  const el=document.getElementById('modal-view');
  if(el)el.classList.remove('active');
}

async function downloadSessionData(sessionId){
  try{
    const r=await fetch(API+'/api/sessions/'+sessionId+'/export');const d=await r.json();
    const b=new Blob([JSON.stringify(d,null,2)],{type:'application/json'});const u=URL.createObjectURL(b);
    const a=document.createElement('a');a.href=u;a.download='numa-capture-'+sessionId.slice(0,8)+'.json';a.click();URL.revokeObjectURL(u);
    showToast('✅ JSON descargado','success');
  }catch(e){showToast('Error: '+e.message,'error')}
}

async function exportAllSessions(){
  try{
    const r=await fetch(API+'/api/sessions');
    if(!r.ok){showToast('Error al obtener sesiones','error');return}
    const d=await r.json();
    const sessions=(d.sessions||[]).filter(s=>s.message_count>0);
    const blob=new Blob([JSON.stringify(sessions,null,2)],{type:'application/json'});
    const u=URL.createObjectURL(blob);const a=document.createElement('a');
    a.href=u;a.download='numa-sessions-export.json';a.click();URL.revokeObjectURL(u);
    showToast('✅ Exportadas '+sessions.length+' sesiones','success');
  }catch(e){showToast('Error: '+e.message,'error')}
}



/* ── RAG SEARCH ── */
async function searchRAG(query){
  const q=query||document.getElementById('rag-query').value.trim();
  if(!q)return;
  const resultsDiv=document.getElementById('rag-results');
  const statusDiv=document.getElementById('rag-status');
  resultsDiv.innerHTML='<p style="color:var(--txt3);padding:20px;text-align:center">🔍 Buscando...</p>';
  statusDiv.textContent='';
  try{
    const r=await fetch(API+'/api/rag/search',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({query:q})});
    const d=await r.json();
    if(d.error){resultsDiv.innerHTML='<p style="color:var(--red)">❌ '+d.error+'</p>';return;}
    if(!d.results||d.results.length===0){
      resultsDiv.innerHTML='<p style="color:var(--txt3);padding:20px;text-align:center">😕 Sin resultados para "'+q+'"</p>';
      statusDiv.textContent='0 resultados en '+d.elapsed+'s';
      return;
    }
    let html='';
    const icons={fact:'📄',judgment:'🧠',tacit_knowledge:'🤫',anti_pattern:'🚫',risk:'⚠️',rule:'📏',exception:'🔀',pattern:'🔁',heuristic:'💡',tip:'💡',default:'📌'};
    d.results.forEach((it,i)=>{
      const icon=icons[it.category]||icons['default'];
      const pct=Math.round(it.score*100);
      html+=`<div style="background:var(--bg3);border:1px solid var(--border);border-radius:var(--rs);margin-bottom:8px;overflow:hidden">
        <div onclick="this.nextElementSibling.classList.toggle('rag-open')" style="cursor:pointer;padding:12px;display:flex;justify-content:space-between;align-items:center;transition:background .2s" onmouseover="this.style.background='var(--bg4)'" onmouseout="this.style.background='transparent'">
          <div style="display:flex;align-items:center;gap:8px">
            <span style="font-size:11px;background:var(--bg4);padding:2px 8px;border-radius:4px;color:var(--txt2)">${icon} ${it.category}</span>
            <span style="font-size:12px;color:var(--txt3)">${pct}%</span>
          </div>
          <span style="font-size:10px;color:var(--txt3)">▸</span>
        </div>
        <div style="padding:0 12px 12px;display:none" class="rag-detail">
          <div style="font-size:14px;color:var(--txt);line-height:1.6;margin-bottom:8px">${it.content}</div>
          <div style="display:flex;gap:12px;font-size:11px;color:var(--txt3);flex-wrap:wrap">
            <span>⚖️ peso=${it.weight}</span>
            <span>📌 fase=${it.phase}</span>
            <span>📊 score=${pct}%</span>
          </div>
        </div>
      </div>`;
    });
    resultsDiv.innerHTML=html;
    statusDiv.textContent=d.results.length+' resultados ('+d.elapsed+'s) para "'+q+'"';
  }catch(e){resultsDiv.innerHTML='<p style="color:var(--red)">❌ Error: '+e.message+'</p>'}
}

async function loadRAG(){
  await loadRAGStats();
  document.getElementById('rag-query').value='';
  document.getElementById('rag-results').innerHTML='<p style="color:var(--txt3);padding:20px;text-align:center">Escribe una consulta para buscar en el índice RAG</p>';
  document.getElementById('rag-status').textContent='';
  setTimeout(()=>document.getElementById('rag-query').focus(),100);
}

async function loadRAGStats(){
  try{
    const r=await fetch(API+'/api/rag/stats');
    const d=await r.json();
    if(d.status==='ready'){
      document.getElementById('rag-count').textContent=d.count;
    }
  }catch(e){}
}



/* ── COMPARATIVA (multi-expert comparison) ── */
async function loadComparativa(){
  showSpinner('comparativa-results','Cargando comparativa...');
  const filter=document.getElementById('comparativa-domain-filter').value;
  try{
    const url=API+'/api/comparativa'+(filter?'?domain='+encodeURIComponent(filter):'');
    const r=await fetch(url);
    if(!r.ok) throw new Error('Error al cargar comparativa');
    const d=await r.json();
    renderComparativa(d);
  }catch(e){
    document.getElementById('comparativa-results').innerHTML='<p style="color:var(--red);font-size:13px;text-align:center;padding:20px">❌ '+e.message+'</p>';
  }
}

function renderComparativa(d){
  if(!d.domains||d.domains.length===0){
    document.getElementById('comparativa-results').innerHTML='<p style="color:var(--txt3);font-size:13px;text-align:center;padding:30px">📭 Sin datos para comparar. Realiza al menos 2 entrevistas en el mismo dominio.</p>';
    return;
  }

  // Update domain filter dropdown
  const select=document.getElementById('comparativa-domain-filter');
  const currentVal=select.value;
  select.innerHTML='<option value="">Todos los dominios</option>'+
    d.all_domains.map(dom=>'<option value="'+escapeHtml(dom)+'" '+(dom===currentVal?'selected':'')+'>'+escapeHtml(dom)+'</option>').join('');

  // Summary stats
  const statsHtml=''+
    '<div style="flex:1;min-width:120px;background:var(--bg3);border:1px solid var(--border);border-radius:var(--rs);padding:14px;text-align:center">'+
      '<div style="font-size:22px;font-weight:800;color:var(--accent2)">'+d.total_sessions+'</div>'+
      '<div style="font-size:11px;color:var(--txt3)">Sesiones totales</div>'+
    '</div>'+
    '<div style="flex:1;min-width:120px;background:var(--bg3);border:1px solid var(--border);border-radius:var(--rs);padding:14px;text-align:center">'+
      '<div style="font-size:22px;font-weight:800;color:var(--green)">'+d.total_consensus+'</div>'+
      '<div style="font-size:11px;color:var(--txt3)">Consensos</div>'+
    '</div>'+
    '<div style="flex:1;min-width:120px;background:var(--bg3);border:1px solid var(--border);border-radius:var(--rs);padding:14px;text-align:center">'+
      '<div style="font-size:22px;font-weight:800;color:var(--red)">'+d.total_contradictions+'</div>'+
      '<div style="font-size:11px;color:var(--txt3)">Contradicciones</div>'+
    '</div>'+
    '<div style="flex:1;min-width:120px;background:var(--bg3);border:1px solid var(--border);border-radius:var(--rs);padding:14px;text-align:center">'+
      '<div style="font-size:22px;font-weight:800;color:var(--amber)">'+d.total_domains+'</div>'+
      '<div style="font-size:11px;color:var(--txt3)">Dominios</div>'+
    '</div>';
  document.getElementById('comparativa-stats').innerHTML=statsHtml;

  // Build domain-by-domain results
  let html='';
  d.domains.forEach(function(dom){
    html+=''+
      '<div style="background:var(--bg3);border:1px solid var(--border);border-radius:var(--r);padding:16px;margin-bottom:16px">'+
        '<h3 style="font-size:16px;margin-bottom:8px;display:flex;align-items:center;gap:8px">'+
          '📁 '+escapeHtml(dom.domain)+
          '<span style="font-size:12px;color:var(--txt3);font-weight:400">'+dom.total_sessions+' sesiones · '+dom.total_items+' items</span>'+
        '</h3>'+

        // Sessions in domain
        '<details style="margin-bottom:12px">'+
          '<summary style="cursor:pointer;font-size:13px;color:var(--accent2);padding:4px 0">👥 Sesiones en este dominio ('+dom.sessions.length+')</summary>'+
          '<div style="display:flex;flex-wrap:wrap;gap:8px;margin-top:8px">';
          dom.sessions.forEach(function(s){
            html+='<div style="background:var(--bg4);border:1px solid var(--border);border-radius:var(--rs);padding:10px;flex:1;min-width:180px">'+
                '<strong style="font-size:13px;color:var(--txt2)">'+escapeHtml(s.expert_name)+'</strong>'+
                '<span style="font-size:11px;color:var(--txt3);display:block">'+escapeHtml(s.expert_role||'')+'</span>'+
                '<span style="font-size:11px;color:var(--txt3);display:block">🏢 '+escapeHtml(s.organization||'')+'</span>'+
                '<span style="font-size:12px;color:var(--accent2);display:block;margin-top:4px">🧠 '+s.total_items+' items</span>'+
              '</div>';
          });
        html+='</div></details>'+

        // Consensus
        renderConsensus(dom)+
        // Contradictions
        renderContradictions(dom)+
        // Unique items
        renderUnique(dom)+
        // Coverage table
        renderCoverage(dom)+
      '</div>';
  });

  document.getElementById('comparativa-results').innerHTML=html;
}

function renderConsensus(dom){
  if(!dom.consensus||dom.consensus.length===0) return '';
  let html='<div style="margin-bottom:12px">'+
    '<h4 style="font-size:14px;margin-bottom:8px;color:var(--green)">✅ Consenso ('+dom.consensus_count+')</h4>';
  dom.consensus.forEach(function(c){
    html+='<div style="background:rgba(34,197,94,0.08);border:1px solid rgba(34,197,94,0.25);border-radius:var(--rs);padding:10px;margin-bottom:6px">'+
      '<div style="font-size:13px;color:var(--txt);margin-bottom:4px">'+escapeHtml(c.canonical_statement)+'</div>'+
      '<div style="display:flex;flex-wrap:wrap;gap:4px;font-size:11px">'+
        '<span style="color:var(--green)">📊 '+c.session_count+'/'+c.total_sessions+' expertos</span>';
    c.items.forEach(function(it){
      html+='<span style="color:var(--txt3);background:var(--bg4);padding:2px 8px;border-radius:10px">'+escapeHtml(it.expert_name)+' · Fase '+it.phase+'</span>';
    });
    html+='</div></div>';
  });
  html+='</div>';
  return html;
}

function renderContradictions(dom){
  if(!dom.contradictions||dom.contradictions.length===0) return '';
  let html='<div style="margin-bottom:12px">'+
    '<h4 style="font-size:14px;margin-bottom:8px;color:var(--red)">⚠️ Contradicciones ('+dom.contradictions_count+')</h4>';
  dom.contradictions.forEach(function(c){
    html+='<div style="background:rgba(239,68,68,0.08);border:1px solid rgba(239,68,68,0.25);border-radius:var(--rs);padding:10px;margin-bottom:6px">'+
      '<div style="display:flex;gap:8px;align-items:flex-start">'+
        '<div style="flex:1;border-right:1px solid var(--border);padding-right:8px">'+
          '<div style="font-size:11px;color:var(--red);margin-bottom:2px">'+escapeHtml(c.session_a)+' · Fase '+c.phase_a+'</div>'+
          '<div style="font-size:13px;color:var(--txt)">'+escapeHtml(c.statement_a)+'</div>'+
        '</div>'+
        '<div style="flex:1">'+
          '<div style="font-size:11px;color:var(--amber);margin-bottom:2px">'+escapeHtml(c.session_b)+' · Fase '+c.phase_b+'</div>'+
          '<div style="font-size:13px;color:var(--txt)">'+escapeHtml(c.statement_b)+'</div>'+
        '</div>'+
      '</div>'+
      '<div style="text-align:center;font-size:18px;margin:2px 0">⚡</div>'+
    '</div>';
  });
  html+='</div>';
  return html;
}

function renderUnique(dom){
  const entries=Object.entries(dom.unique_per_session||{});
  if(entries.length===0) return '';
  let html='<div style="margin-bottom:12px">'+
    '<h4 style="font-size:14px;margin-bottom:8px;color:var(--accent2)">🔑 Items Únicos por Experto</h4>'+
    '<div style="display:flex;flex-wrap:wrap;gap:8px">';
  entries.forEach(function(e){
    const name=e[0],items=e[1];
    html+='<div style="flex:1;min-width:200px;background:var(--bg4);border:1px solid var(--border);border-radius:var(--rs);padding:10px">'+
      '<strong style="font-size:12px;color:var(--txt2);display:block;margin-bottom:4px">'+escapeHtml(name)+' ('+items.length+')</strong>';
    items.slice(0,8).forEach(function(it){
      html+='<div style="font-size:12px;color:var(--txt);padding:4px 0;border-bottom:1px solid var(--border)">'+escapeHtml(it.statement)+'</div>';
    });
    if(items.length>8){
      html+='<div style="font-size:11px;color:var(--txt3);margin-top:4px">+'+(items.length-8)+' más</div>';
    }
    html+='</div>';
  });
  html+='</div></div>';
  return html;
}

function renderCoverage(dom){
  if(!dom.coverage||dom.coverage.length===0) return '';
  const phases=['A','B','C','D','E'];
  let html='<div>'+
    '<h4 style="font-size:14px;margin-bottom:8px;color:var(--amber)">📊 Cobertura por Fase</h4>'+
    '<div style="overflow-x:auto">'+
    '<table style="width:100%;border-collapse:collapse;font-size:12px">'+
      '<thead><tr style="background:var(--bg4)">'+
        '<th style="padding:8px 10px;text-align:left;color:var(--txt2);border-bottom:1px solid var(--border)">Experto</th>';
  phases.forEach(function(p){
    html+='<th style="padding:8px 6px;text-align:center;color:var(--txt2);border-bottom:1px solid var(--border)">Fase '+p+'</th>';
  });
  html+='<th style="padding:8px 10px;text-align:center;color:var(--accent2);border-bottom:1px solid var(--border)">Total</th>'+
      '</tr></thead><tbody>';
  dom.coverage.forEach(function(row){
    html+='<tr style="border-bottom:1px solid var(--border)">'+
      '<td style="padding:8px 10px;color:var(--txt)">'+escapeHtml(row.expert_name)+'</td>';
    phases.forEach(function(p){
      var val=row['phase_'+p]||0;
      html+='<td style="padding:8px 6px;text-align:center;color:'+(val>0?'var(--green)':'var(--txt3)')+'">'+val+'</td>';
    });
    html+='<td style="padding:8px 10px;text-align:center;font-weight:700;color:var(--accent2)">'+(row.total||0)+'</td>'+
      '</tr>';
  });
  html+='</tbody></table></div></div>';
  return html;
}

/* ── INIT ── */
document.addEventListener('DOMContentLoaded', ()=>{
  checkStoredSession();
  loadTheme();
  // Register service worker for PWA
  if('serviceWorker' in navigator){
    navigator.serviceWorker.register('/static/service-worker.js').catch(e=>console.warn('SW registration failed:',e));
  }
  // Keyboard shortcut: / to focus RAG search
  document.addEventListener('keydown', e=>{
    if(e.key==='/' && !['INPUT','TEXTAREA'].includes(document.activeElement.tagName)){
      e.preventDefault();
      const ragInput=document.getElementById('rag-query');
      if(ragInput&&document.getElementById('screen-rag').classList.contains('active')){
        ragInput.focus();
      }
    }
  });
});

/* ── THEME TOGGLE ── */
function toggleTheme(){
  const current=localStorage.getItem('numa_theme')||'dark';
  const next=current==='dark'?'light':'dark';
  localStorage.setItem('numa_theme',next);
  applyTheme(next);
}
function loadTheme(){
  const saved=localStorage.getItem('numa_theme');
  if(saved)applyTheme(saved);
}
function applyTheme(theme){
  document.documentElement.setAttribute('data-theme',theme);
  const btn=document.getElementById('theme-btn');
  if(btn){
    btn.innerHTML=theme==='dark'?'<span class="tt-icon">🌙</span><span class="tt-label">Oscuro</span>':'<span class="tt-icon">☀️</span><span class="tt-label">Claro</span>';
  }
}

/* ── TOAST ── */
function showToast(msg,type='success',duration=3500){
  let container=document.querySelector('.toast-container');
  if(!container){
    container=document.createElement('div');container.className='toast-container';
    document.body.appendChild(container);
  }
  const el=document.createElement('div');el.className='toast toast-'+type;
  el.textContent=msg;container.appendChild(el);
  setTimeout(()=>{el.style.opacity='0';el.style.transition='opacity .3s';setTimeout(()=>el.remove(),300)},duration);
}

/* ── SPINNER HELPER ── */
function showSpinner(containerId,text='Cargando...'){
  const c=document.getElementById(containerId);
  if(c)c.innerHTML=`<div class="spinner"><div class="sp-dot"></div><div class="sp-dot"></div><div class="sp-dot"></div><span class="spinner-text">${text}</span></div>`;
}
