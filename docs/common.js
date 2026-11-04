// Shared by both pages: age bands, number formats, area grouping, SVG and tooltip helpers.
const BINS=[
  {lab:'≤ 2008',from:2004,to:2008,c:'--b0',note:'CiviCRM 1.x–2.1'},
  {lab:'2009–2012',from:2009,to:2012,c:'--b1',note:'2.2–4.2'},
  {lab:'2013–2017',from:2013,to:2017,c:'--b2',note:'4.3–4.7'},
  {lab:'2018–2021',from:2018,to:2021,c:'--b3',note:'5.0–5.45'},
  {lab:'2022 on',from:2022,to:2026,c:'--b4',note:'5.46 and later'}];
const fmt=n=>n.toLocaleString('en-US');
const pct=(a,b,digits=a/b<.1?1:0)=>b?(100*a/b).toLocaleString('en-US',{maximumFractionDigits:digits})+'%':'–';
const $=s=>document.querySelector(s);
const NS='http://www.w3.org/2000/svg';
const tip=$('#tip');
let Y0;

const sum=a=>a.reduce((x,y)=>x+y,0);
function binsOf(ys){return BINS.map(b=>{let s=0;for(let y=b.from;y<=b.to;y++)s+=ys[y-Y0]||0;return s})}
function median(ys){const t=sum(ys);let acc=0;for(let i=0;i<ys.length;i++){acc+=ys[i];if(acc>=t/2)return Y0+i}return null}
function areaOf(p){
  const s=p.split('/');
  if(s[0]==='tests'){const r=s[1]==='phpunit'?s.slice(2):s.slice(1);return 'tests/'+(r.length>2?r.slice(0,2):r.slice(0,1)).join('/')}
  if(s[0]==='templates'&&s[1]==='CRM'&&s.length>3)return s.slice(0,3).join('/');
  if(s.length>2&&['CRM','Civi','ext','ang','js','api','css','xml','install','setup'].includes(s[0]))return s.slice(0,2).join('/');
  return s.length>1?s[0]:'(root)';
}
function groupOf(a){const g=a.split('/')[0];return ['CRM','Civi','ext','templates','api','tests'].includes(g)?g:'Other'}
function barHTML(bins,label){
  return '<div class="bar" aria-hidden="true">'+bins.map((v,i)=>v?`<div data-tip="${i}" data-label="${label}" style="flex:${v};background:var(${BINS[i].c})"></div>`:'').join('')+'</div>';
}
function el(tag,attrs,parent){const e=document.createElementNS(NS,tag);for(const k in attrs)e.setAttribute(k,attrs[k]);parent&&parent.appendChild(e);return e}
function showTip(html,x,y){tip.innerHTML=html;tip.hidden=false;const r=tip.getBoundingClientRect();
  tip.style.left=Math.max(8,Math.min(x+14,innerWidth-r.width-8))+'px';tip.style.top=(y+r.height+20>innerHeight?y-r.height-12:y+14)+'px'}
// tooltips opened from the keyboard are read out through a polite live region
const say=(()=>{const d=document.createElement('div');d.className='sr-only';d.setAttribute('aria-live','polite');document.body.append(d);return t=>{d.textContent=t}})();
const swatch=i=>`<i style="background:var(${BINS[i].c})"></i>`;
const niceStep=(max,n)=>{const raw=max/n,p=10**Math.floor(Math.log10(raw));return [1,2,2.5,5,10].map(m=>m*p).find(s=>s>=raw)};
