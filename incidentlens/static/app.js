"use strict";
const $ = (id) => document.getElementById(id);
let state = null, result = null, busy = false;
const fmt = (x) => x == null ? "—" : `${x.toFixed(3)} ms`;
const el = (tag, text, cls) => {const n = document.createElement(tag); if(text != null) n.textContent = text; if(cls) n.className = cls; return n;};
function notice(message, kind = "") { $("notice").textContent = message; $("notice").className = `notice ${kind}`; }
async function api(path, body) {
  const response = await fetch(path, body === undefined ? {} : {method:"POST", headers:{"Content-Type":"application/json"},body:JSON.stringify(body)});
  const data = await response.json();
  if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Request failed. Refresh and try again.");
  return data;
}
function controls() {
  const phase = state?.events?.at(-1)?.action;
  $("baseline").disabled = busy;
  $("incident").disabled = busy || phase !== "baseline";
  $("recover").disabled = busy || phase !== "incident";
  $("investigate").disabled = busy || !state?.experiment_id;
  $("mode").disabled = busy;
  $("download").disabled = busy || !result;
  $("mode").options[1].disabled = !state?.llm_available;
  $("mode").options[1].textContent = state?.llm_available ? "LLM agent · OpenAI" : "LLM agent · key required";
}
function drawChart(points) {
  $("chart").replaceChildren();
  if (!points?.length) {$("chart").append(el("p","Your experiment will appear here.","empty")); return;}
  const ns="http://www.w3.org/2000/svg", svg=document.createElementNS(ns,"svg");
  svg.setAttribute("viewBox","0 0 560 185");svg.setAttribute("role","img");svg.setAttribute("aria-label","Measured query latency by request order, in milliseconds");
  const max=Math.max(...points.map(p=>p.duration_ms),.001)*1.15;
  const node=(tag,attrs,text)=>{const n=document.createElementNS(ns,tag);Object.entries(attrs).forEach(([k,v])=>n.setAttribute(k,v));if(text!=null)n.textContent=text;svg.append(n);return n;};
  [0,.5,1].forEach(f=>{const y=154-f*138;node("line",{x1:48,y1:y,x2:548,y2:y,stroke:"#263142","stroke-dasharray":"3 5"});node("text",{x:0,y:y+4,fill:"#8b9bb0","font-size":10},(max*f).toFixed(2));});
  const colors={baseline:"#8af0c0",incident:"#f5b273",recovery:"#8fbaff"};
  Object.keys(colors).forEach(phase=>{
    const line=points.map((p,i)=>({p,i})).filter(v=>v.p.phase===phase).map(({p,i})=>`${48+i/Math.max(points.length-1,1)*500},${154-p.duration_ms/max*138}`).join(" ");
    if(line)node("polyline",{points:line,fill:"none",stroke:colors[phase],"stroke-width":2});
  });
  points.forEach((p,i)=>{const circle=node("circle",{cx:48+i/Math.max(points.length-1,1)*500,cy:154-p.duration_ms/max*138,r:2.2,fill:colors[p.phase]});const title=document.createElementNS(ns,"title");title.textContent=`${p.phase} · ${p.duration_ms.toFixed(4)} ms · event ${p.event_id}`;circle.append(title);});
  node("text",{x:48,y:179,fill:"#8b9bb0","font-size":9},"Request 1");node("text",{x:485,y:179,fill:"#8b9bb0","font-size":9},`Request ${points.length}`);
  $("chart").append(svg);
}
async function refresh() {
  state = await api("/api/state");const phases=state.metrics?.phases || {};
  ["baseline","incident","recovery"].forEach(p=>$(p+"Metric").textContent=fmt(phases[p]?.p95_ms));
  $("ratioMetric").textContent=phases.baseline&&phases.incident ? `${(phases.incident.p95_ms/Math.max(phases.baseline.p95_ms,.000001)).toFixed(1)}×` : "—";
  drawChart(state.metrics?.points);
  $("timeline").replaceChildren();
  if(!state.events.length)$("timeline").append(el("p","No deployments recorded.","empty"));
  state.events.forEach(event=>{const row=el("div",null,"timelineitem"),text=el("div",event.change);text.append(el("small",new Date(event.timestamp).toLocaleTimeString()+" · event "+event.event_id));row.append(el("span",event.version,"version"),text);$("timeline").append(row);});
  controls();
}
function renderReport(data) {
  result=data;const report=data.report, root=$("report");root.replaceChildren();
  root.append(el("span",report.status.replaceAll("_"," "),"status"),el("h3",report.title,"reporttitle"));
  root.append(el("p",`${data.mode==="rules" ? "Rule-based workflow · no LLM" : "LLM agent · model-generated inference"} · ${(data.duration_ms/1000).toFixed(1)} s · ${data.trace.length} tool calls`,"reportmeta"));
  report.findings.forEach(f=>{const row=el("div",null,"finding");row.append(el("div",f.statement));f.evidence.forEach(id=>{const a=el("a",id,"citation");a.href="#trace-"+id;a.addEventListener("click",()=>{$("trace-"+id).open=true;});row.append(a);});root.append(row);});
  report.next_steps.forEach(step=>root.append(el("p","→ "+step,"next")));
  const limitations=el("details",null,"limitations");limitations.append(el("summary","Limitations & uncertainty"));report.limitations.forEach(l=>limitations.append(el("p",l)));root.append(limitations);
  $("trace").replaceChildren();
  data.trace.forEach(t=>{const d=el("details",null,"traceitem");d.id="trace-"+t.id;const s=el("summary");s.append(el("span",t.id,"traceid"),el("span",t.tool),el("span",t.ok?"SUCCESS":"FAILED","traceok"),el("span",`${t.duration_ms} ms · ${t.attempts} attempt(s)`,"tracetime"));d.append(s,el("pre",JSON.stringify({arguments:t.arguments,result:t.result,error:t.error},null,2)));$("trace").append(d);});
  controls();
}
async function act(action) {
  if(busy)return;busy=true;controls();notice(action==="investigate"?"Investigating through MCP… collecting evidence and assembling the report.":"Running real queries and recording telemetry…","busy");
  try {
    if(action==="investigate")renderReport(await api("/api/investigate",{experiment_id:state.experiment_id,mode:$("mode").value}));
    else {
      await api(`/api/lab/${action}`,action==="baseline"?{}:{experiment_id:state.experiment_id});
      result=null;$("download").disabled=true;
      $("report").replaceChildren(el("p","Telemetry changed. Run a fresh investigation for the current state.","empty"));
      $("trace").replaceChildren(el("p","Run an investigation to collect a fresh tool trace.","empty"));
    }
    await refresh();notice(action==="investigate"?"Investigation complete. Select an evidence reference to inspect its source.":action==="baseline"?"Baseline recorded. Remove the index to reproduce a regression, or investigate now to test insufficient evidence.":action==="incident"?"Index removed and incident samples recorded. Investigate to connect the evidence.":"Index restored and recovery samples recorded. Investigate again to verify the result.");
  } catch(error) {notice(error.message,"error");}
  finally {busy=false;controls();}
}
["baseline","incident","recover","investigate"].forEach(id=>$(id).addEventListener("click",()=>act(id)));
$("download").addEventListener("click",()=>{if(!result)return;const url=URL.createObjectURL(new Blob([JSON.stringify(result,null,2)],{type:"application/json"}));const link=el("a");link.href=url;link.download=`incidentlens-${result.experiment_id}.json`;link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);});
refresh().catch(e=>notice(e.message,"error"));
