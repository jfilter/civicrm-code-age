// Shared by the releases and people pages: loads data.json and who.json and totals lines per release and author.
const esc=s=>String(s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const long=d=>new Date(d+'T00:00:00Z').toLocaleDateString('en-GB',{day:'numeric',month:'long',year:'numeric',timeZone:'UTC'});
// the first monthly snapshot on or after a date, as the code age page addresses it
const monthAfter=d=>{const [y,m,dd]=d.split('-').map(Number);const t=dd===1?[y,m]:m===12?[y+1,1]:[y,m+1];return t[0]+'-'+String(t[1]).padStart(2,'0')};
const topN=(m,k)=>[...m].sort((a,b)=>b[1]-a[1]).slice(0,k);
const inc=(m,k,n)=>m.set(k,(m.get(k)||0)+n);
const relTitle=r=>r.name==='master'?'master, not yet released':'CiviCRM '+r.name;
const relHref=r=>'releases.html#'+encodeURIComponent(r.name);
const personHref=a=>'people.html#'+encodeURIComponent(a.name);
const ageBar=ys=>`<span class="bar" aria-hidden="true">${binsOf(ys).map((v,j)=>v?`<div style="flex:${v};background:var(${BINS[j].c})"></div>`:'').join('')}</span>`;
const bandLegend=()=>BINS.map((b,i)=>`<span>${swatch(i)}${b.lab}</span>`).join('');
// a short ranked list with bars; label(k) names a row, href(k) optionally links it
function mini(rows,cap,label,href){const m=Math.max(1,...rows.map(r=>r[1]));
  return `<div class="mini"><div class="cap">${cap}</div>`+rows.map(([k,n])=>{const t=esc(label(k));
    return `<div class="r"><span title="${t}">${href?`<a href="${href(k)}">${t}</a>`:t}</span><span class="bar"><div style="flex:${n/m};background:var(--b2)"></div><div style="flex:${1-n/m}"></div></span><span>${fmt(n)}</span></div>`}).join('')+'</div>'}

function loadWho(){
  return Promise.all(['data.json','who.json'].map(u=>fetch(u).then(r=>{if(!r.ok)throw new Error(`${u}: ${r.status}`);return r.json()}))).then(([D,W])=>{
    Y0=D.meta.y0;BINS[BINS.length-1].to=D.meta.y1;const NY=D.meta.y1-Y0+1;
    const R=W.releases.map(([name,at,released])=>({name,at,released})).concat([{name:'master',at:null,released:null}]);
    const A=W.authors.map((name,i)=>({i,name,ys:Array(NY).fill(0),introYs:Array(NY).fill(0),intro:0,areas:new Map(),rels:new Map()}));
    for(const r of R){r.ys=Array(NY).fill(0);r.intro=0;r.authors=new Map();r.authorsAlive=new Map();r.areas=new Map()}
    const areaNames=new Set();
    for(const [p,t] of W.files){
      const area=areaOf(p);areaNames.add(area);
      for(let i=0;i<t.length;i+=4){const r=t[i],a=t[i+1],y=t[i+2],n=t[i+3];
        R[r].ys[y]+=n;A[a].ys[y]+=n;inc(A[a].areas,area,n);inc(R[r].authorsAlive,a,n);inc(R[r].areas,area,n)}}
    for(const [r,a,y,n] of W.introduced){R[r].intro+=n;A[a].intro+=n;A[a].introYs[y]+=n;inc(R[r].authors,a,n);inc(A[a].rels,r,n)}
    for(const x of [...R,...A]){x.alive=sum(x.ys);x.bins=binsOf(x.ys)}
    const first=D.snapshots[0].date,total=sum(A.map(a=>a.alive));
    // releases branched before the first snapshot lost lines nobody counted
    R.forEach((r,i)=>r.partial=i>0?R[i-1].at<first:r.at<first);
    // copies of unknown origin and the project account count in the totals but are no person, so no list shows them
    const hidden=new Set(W.hidden);for(const r of R)for(const a of hidden){r.authors.delete(a);r.authorsAlive.delete(a)}
    const ranked=A.filter(a=>!hidden.has(a.i)).sort((a,b)=>b.alive-a.alive);
    const needed=share=>{let acc=0;for(let k=0;k<ranked.length;k++){acc+=ranked[k].alive;if(acc>=share*total)return k+1}};
    $('#foot').innerHTML=`Data: civicrm-core ${D.meta.ref} as of ${long(D.meta.head[1])} (commit ${D.meta.head[0]}). Code and method: <a href="https://github.com/jfilter/civicrm-code-age">github.com/jfilter/civicrm-code-age</a>.`;
    return {D,W,R,A,NY,first,total,ranked,needed,areaNames,hidden};
  });
}

const METHOD=first=>[
  `Each line is followed month by month as on the <a href="./">code age page</a>. Its author is the author of the commit that blame names for it; a line moved or reformatted keeps its author, a copy of code that is still there keeps the author of the original. Where blame cannot place the original, such as code copied from a side branch and changed on master since, the copy counts in the totals but for no person, and so does the project account "CiviCRM", which made the version bumps and imported APIv4 in 2019. On this page a copy also keeps the year and release of the original, so it counts where its author wrote it; on the code age page it is new code of the year it was made.`,
  `A line's release is the first release, in version order, that ships it: releases from 4.3 on are the tags <span class="mono">X.Y.0</span> and the monthly <span class="mono">4.7.x</span>, a release branch without such a tag is its release candidate, earlier releases are the SVN branches <span class="mono">vX.Y</span>. A release ships master up to the commit it branched from. Fixes made only on a release branch count for the next release that merges them into master.`,
  `Lines brought in are counted from ${first}, the first snapshot. Before that date the counts only hold what was still there on it, so for releases before 1.5 and for 2004 and 2005 they are lower bounds.`,
  `Identities with the same e-mail address or the same full name are one author, and so is an address whose local part spells a full name (<span class="mono">jane.doe@</span>). Names are shown as the author wrote them most often. Other shared accounts such as "mover" stay under their name.`,
  `In SVN times patches by others were usually committed by the core team, so before 2013 code counts for whoever committed it. On GitHub the author of a pull request's commits is the author.`
];
