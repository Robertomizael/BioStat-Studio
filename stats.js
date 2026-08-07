'use strict';
module.exports = function registerStats(api, datasets, deps){
  const {ss,jStat}=deps;
  const safe=x=>Number.isFinite(x)?x:null;
  const clampP=p=>Math.max(0,Math.min(1,p));
  const mean=a=>a.length?ss.mean(a):null;
  const variance=a=>a.length>1?ss.sampleVariance(a):null;
  const sd=a=>a.length>1?ss.sampleStandardDeviation(a):null;
  const nums=(rows,col)=>rows.map(r=>Number(r[col])).filter(Number.isFinite);
  const paired=(rows,a,b)=>rows.map(r=>[Number(r[a]),Number(r[b])]).filter(x=>Number.isFinite(x[0])&&Number.isFinite(x[1]));
  const uniq=arr=>[...new Set(arr.map(v=>String(v)))];
  const pT=(t,df)=>clampP(2*(1-jStat.studentt.cdf(Math.abs(t),df)));
  const pZ=z=>clampP(2*(1-jStat.normal.cdf(Math.abs(z),0,1)));
  function getData(req){const d=datasets.get(req.body.dataset_id);if(!d)throw new Error('Base de datos no encontrada. Vuelva a sincronizar.');return d;}
  function fail(res,e){res.status(400).json({detail:e.message||String(e)});}

function covariance(a,b){ if(a.length!==b.length || a.length<2) return null; const ma=mean(a),mb=mean(b); return a.reduce((s,x,i)=>s+(x-ma)*(b[i]-mb),0)/(a.length-1); }
function pearson(a,b){ if(a.length!==b.length || a.length<3) return null; const c=covariance(a,b), sa=sd(a), sb=sd(b); return (!sa||!sb)?null:c/(sa*sb); }
function ranks(values){
  const idx=values.map((v,i)=>({v,i})).sort((a,b)=>a.v-b.v), out=Array(values.length); let i=0;
  while(i<idx.length){let j=i+1;while(j<idx.length&&idx[j].v===idx[i].v)j++;const r=(i+1+j)/2;for(let k=i;k<j;k++)out[idx[k].i]=r;i=j;} return out;
}
function rankTieSum(values){const counts={};values.forEach(v=>counts[v]=(counts[v]||0)+1);return Object.values(counts).reduce((s,t)=>s+t**3-t,0)}
function matrixTranspose(A){return A[0].map((_,j)=>A.map(r=>r[j]));}
function matrixMul(A,B){return A.map(r=>B[0].map((_,j)=>r.reduce((s,x,k)=>s+x*B[k][j],0)));}
function matrixVecMul(A,v){return A.map(r=>r.reduce((s,x,i)=>s+x*v[i],0));}
function matrixInverse(A){
  const n=A.length, M=A.map((r,i)=>[...r,...Array.from({length:n},(_,j)=>i===j?1:0)]);
  for(let i=0;i<n;i++){
    let p=i;for(let r=i+1;r<n;r++)if(Math.abs(M[r][i])>Math.abs(M[p][i]))p=r;
    if(Math.abs(M[p][i])<1e-12)throw new Error('La matriz es singular; revise colinealidad o variables constantes.');
    [M[i],M[p]]=[M[p],M[i]]; const d=M[i][i]; for(let j=0;j<2*n;j++)M[i][j]/=d;
    for(let r=0;r<n;r++)if(r!==i){const f=M[r][i];for(let j=0;j<2*n;j++)M[r][j]-=f*M[i][j];}
  }
  return M.map(r=>r.slice(n));
}
function solveLeastSquares(X,y){const Xt=matrixTranspose(X),XtX=matrixMul(Xt,X),inv=matrixInverse(XtX),b=matrixVecMul(inv,matrixVecMul(Xt,y));return {b,inv};}
function logChoose(n,k){let s=0;for(let i=1;i<=k;i++)s+=Math.log(n-k+i)-Math.log(i);return s;}
function hypergeomProb(a,r1,c1,n){return Math.exp(logChoose(c1,a)+logChoose(n-c1,r1-a)-logChoose(n,r1));}
function fisher2x2(a,b,c,d){
  const r1=a+b,c1=a+c,n=a+b+c+d,lo=Math.max(0,r1-(n-c1)),hi=Math.min(r1,c1),pObs=hypergeomProb(a,r1,c1,n);let p=0;
  for(let x=lo;x<=hi;x++){const q=hypergeomProb(x,r1,c1,n);if(q<=pObs+1e-12)p+=q;}return clampP(p);
}
function contingency(rows,row,col){
  const rLevels=uniq(rows.map(x=>x[row]).filter(v=>v!==null&&v!==undefined&&v!==''));
  const cLevels=uniq(rows.map(x=>x[col]).filter(v=>v!==null&&v!==undefined&&v!==''));
  const obs=rLevels.map(()=>cLevels.map(()=>0));
  rows.forEach(x=>{if(x[row]===null||x[col]===null||x[row]===undefined||x[col]===undefined)return;const i=rLevels.indexOf(String(x[row])),j=cLevels.indexOf(String(x[col]));if(i>=0&&j>=0)obs[i][j]++;});
  return {rLevels,cLevels,obs};
}
function linearRegression(rows,outcome,predictors){
  const clean=rows.map(r=>[Number(r[outcome]),...predictors.map(p=>Number(r[p]))]).filter(z=>z.every(Number.isFinite));
  const y=clean.map(z=>z[0]), X=clean.map(z=>[1,...z.slice(1)]), n=y.length,k=predictors.length;
  if(n<=k+1)throw new Error('No hay suficientes casos completos para la regresión.');
  const {b,inv}=solveLeastSquares(X,y), pred=matrixVecMul(X,b), ym=mean(y), sse=y.reduce((s,v,i)=>s+(v-pred[i])**2,0),sst=y.reduce((s,v)=>s+(v-ym)**2,0),mse=sse/(n-k-1),r2=sst?1-sse/sst:0,adj=1-(1-r2)*(n-1)/(n-k-1);
  const names=['Constante',...predictors], coeff=names.map((name,i)=>{const se=Math.sqrt(Math.max(0,mse*inv[i][i])),t=se?b[i]/se:null,p=t===null?null:pT(t,n-k-1);return {Variable:name,B:safe(b[i]),'Error estándar':safe(se),t:safe(t),p:safe(p)};});
  const f=(k&&sse>0)?((sst-sse)/k)/mse:null, fp=f===null?null:1-jStat.centralF.cdf(f,k,n-k-1);
  return {coeff,fit:[{N:n,R2:safe(r2),'R2 ajustada':safe(adj),F:safe(f),p:safe(fp)}]};
}
function logisticRegression(rows,outcome,predictors){
  const clean=rows.map(r=>[Number(r[outcome]),...predictors.map(p=>Number(r[p]))]).filter(z=>z.every(Number.isFinite) && (z[0]===0||z[0]===1));
  const y=clean.map(z=>z[0]),X=clean.map(z=>[1,...z.slice(1)]),n=y.length,k=predictors.length+1;if(n<=k)throw new Error('No hay suficientes casos completos para la regresión logística.');
  let b=Array(k).fill(0), inv;
  for(let it=0;it<50;it++){
    const eta=matrixVecMul(X,b),p=eta.map(e=>1/(1+Math.exp(-Math.max(-35,Math.min(35,e))))),w=p.map(q=>Math.max(1e-6,q*(1-q)));
    const XtWX=Array.from({length:k},()=>Array(k).fill(0)),XtWz=Array(k).fill(0);
    for(let i=0;i<n;i++){const z=eta[i]+(y[i]-p[i])/w[i];for(let a=0;a<k;a++){XtWz[a]+=X[i][a]*w[i]*z;for(let c=0;c<k;c++)XtWX[a][c]+=X[i][a]*w[i]*X[i][c];}}
    inv=matrixInverse(XtWX);const nb=matrixVecMul(inv,XtWz),diff=Math.max(...nb.map((v,i)=>Math.abs(v-b[i])));b=nb;if(diff<1e-7)break;
  }
  const names=['Constante',...predictors],coeff=names.map((name,i)=>{const se=Math.sqrt(Math.max(0,inv[i][i])),z=se?b[i]/se:null,p=z===null?null:pZ(z);return {Variable:name,B:safe(b[i]),'Error estándar':safe(se),Wald:safe(z===null?null:z*z),p:safe(p),OR:safe(Math.exp(b[i]))};});
  const eta=matrixVecMul(X,b),prob=eta.map(e=>1/(1+Math.exp(-Math.max(-35,Math.min(35,e))))),ll=prob.reduce((s,p,i)=>s+y[i]*Math.log(Math.max(p,1e-12))+(1-y[i])*Math.log(Math.max(1-p,1e-12)),0),py=mean(y),ll0=y.reduce((s,v)=>s+v*Math.log(Math.max(py,1e-12))+(1-v)*Math.log(Math.max(1-py,1e-12)),0),chi=2*(ll-ll0),df=predictors.length,pModel=1-jStat.chisquare.cdf(chi,Math.max(1,df));
  return {coeff,fit:[{N:n,'-2 Log likelihood':safe(-2*ll),'Chi-cuadrada modelo':safe(chi),gl:df,p:safe(pModel),'R2 Nagelkerke aprox.':safe((1-Math.exp((2/n)*(ll0-ll)))/(1-Math.exp((2/n)*ll0)))}]};
}

  api.post('/api/ttest-one',(req,res)=>{try{const d=getData(req),a=nums(d.rows,req.body.column),mu=Number(req.body.mu||0),m=mean(a),s=sd(a),se=s/Math.sqrt(a.length),t=(m-mu)/se,df=a.length-1;res.json({analysis:'t para una muestra',rows:[{Variable:req.body.column,N:a.length,Media:m,'Valor de prueba':mu,Diferencia:m-mu,t:safe(t),gl:df,p:safe(pT(t,df))}]});}catch(e){fail(res,e)}});
  api.post('/api/ttest',(req,res)=>{try{const d=getData(req),o=req.body.outcome,g=req.body.group,levels=uniq(d.rows.map(r=>r[g]).filter(v=>v!==null&&v!==undefined&&v!==''));if(levels.length!==2)throw new Error('La variable de agrupación debe tener exactamente dos grupos.');const a=d.rows.filter(r=>String(r[g])===levels[0]).map(r=>Number(r[o])).filter(Number.isFinite),b=d.rows.filter(r=>String(r[g])===levels[1]).map(r=>Number(r[o])).filter(Number.isFinite),m1=mean(a),m2=mean(b),v1=variance(a),v2=variance(b),se=Math.sqrt(v1/a.length+v2/b.length),t=(m1-m2)/se,df=(v1/a.length+v2/b.length)**2/((v1/a.length)**2/(a.length-1)+(v2/b.length)**2/(b.length-1));res.json({analysis:'t independientes / Welch',groups:[{Grupo:levels[0],N:a.length,Media:m1,'Desv. estándar':sd(a)},{Grupo:levels[1],N:b.length,Media:m2,'Desv. estándar':sd(b)}],rows:[{Diferencia:m1-m2,t:safe(t),gl:safe(df),p:safe(pT(t,df))}]});}catch(e){fail(res,e)}});
  api.post('/api/ttest-paired',(req,res)=>{try{const d=getData(req),q=paired(d.rows,req.body.before,req.body.after),dif=q.map(x=>x[0]-x[1]),m=mean(dif),s=sd(dif),t=m/(s/Math.sqrt(dif.length)),df=dif.length-1;res.json({analysis:'t relacionadas',rows:[{Par:`${req.body.before} - ${req.body.after}`,N:dif.length,'Diferencia media':m,'Desv. diferencia':s,t:safe(t),gl:df,p:safe(pT(t,df))}]});}catch(e){fail(res,e)}});
  api.post('/api/anova',(req,res)=>{try{const d=getData(req),o=req.body.outcome,g=req.body.factor,levels=uniq(d.rows.map(r=>r[g]).filter(v=>v!==null&&v!==undefined&&v!=='')),groups=levels.map(L=>d.rows.filter(r=>String(r[g])===L).map(r=>Number(r[o])).filter(Number.isFinite)).filter(a=>a.length),all=groups.flat(),gm=mean(all),ssb=groups.reduce((s,a)=>s+a.length*(mean(a)-gm)**2,0),ssw=groups.reduce((s,a)=>s+a.reduce((q,x)=>q+(x-mean(a))**2,0),0),dfb=groups.length-1,dfw=all.length-groups.length,F=(ssb/dfb)/(ssw/dfw),p=1-jStat.centralF.cdf(F,dfb,dfw);res.json({analysis:'ANOVA de un factor',groups:levels.map((L,i)=>({Grupo:L,N:groups[i]?.length||0,Media:groups[i]?.length?mean(groups[i]):null})),rows:[{Fuente:'Entre grupos',SC:ssb,gl:dfb,CM:ssb/dfb,F:safe(F),p:safe(p)},{Fuente:'Dentro de grupos',SC:ssw,gl:dfw,CM:ssw/dfw,F:null,p:null}]});}catch(e){fail(res,e)}});
  api.post('/api/nonparametric',(req,res)=>{try{const d=getData(req),o=req.body.outcome,g=req.body.factor,levels=uniq(d.rows.map(r=>r[g]).filter(v=>v!==null&&v!==undefined&&v!==''));const vals=[],lab=[];d.rows.forEach(r=>{const x=Number(r[o]);if(Number.isFinite(x)&&r[g]!==null&&r[g]!==undefined&&r[g]!==''){vals.push(x);lab.push(String(r[g]));}});const R=ranks(vals),N=vals.length,tie=rankTieSum(vals),groups=levels.map(L=>R.filter((_,i)=>lab[i]===L));if(levels.length===2){const n1=groups[0].length,n2=groups[1].length,R1=groups[0].reduce((s,x)=>s+x,0),U1=R1-n1*(n1+1)/2,U2=n1*n2-U1,U=Math.min(U1,U2),varU=n1*n2/12*((N+1)-tie/(N*(N-1))),z=(U-n1*n2/2)/Math.sqrt(varU);res.json({analysis:'Mann–Whitney U',groups:levels.map((L,i)=>({Grupo:L,N:groups[i].length,'Rango promedio':mean(groups[i])})),rows:[{U:safe(U),z:safe(z),p:safe(pZ(z))}]});}else{let H=12/(N*(N+1))*groups.reduce((s,a)=>s+(a.reduce((q,x)=>q+x,0)**2/a.length),0)-3*(N+1);H/=1-tie/(N**3-N);const df=groups.length-1,p=1-jStat.chisquare.cdf(H,df);res.json({analysis:'Kruskal–Wallis',groups:levels.map((L,i)=>({Grupo:L,N:groups[i].length,'Rango promedio':mean(groups[i])})),rows:[{'H de Kruskal-Wallis':safe(H),gl:df,p:safe(p)}]});}}catch(e){fail(res,e)}});
  api.post('/api/wilcoxon',(req,res)=>{try{const d=getData(req),q=paired(d.rows,req.body.before,req.body.after),dif=q.map(x=>x[0]-x[1]).filter(x=>x!==0),abs=dif.map(Math.abs),R=ranks(abs);let pos=0,neg=0;dif.forEach((x,i)=>x>0?pos+=R[i]:neg+=R[i]);const W=Math.min(pos,neg),n=dif.length,mu=n*(n+1)/4,sig=Math.sqrt(n*(n+1)*(2*n+1)/24),z=(W-mu)/sig;res.json({analysis:'Wilcoxon',rows:[{N:n,'Rangos positivos':pos,'Rangos negativos':neg,W:safe(W),z:safe(z),p:safe(pZ(z))}]});}catch(e){fail(res,e)}});
  api.post('/api/correlation',(req,res)=>{try{const d=getData(req),cols=req.body.columns||[],method=req.body.method||'pearson',rows=[];for(let i=0;i<cols.length;i++)for(let j=i+1;j<cols.length;j++){const q=paired(d.rows,cols[i],cols[j]),a=q.map(x=>x[0]),b=q.map(x=>x[1]),n=a.length;let r,p;if(method==='spearman'){r=pearson(ranks(a),ranks(b));const t=r*Math.sqrt((n-2)/(1-r*r));p=pT(t,n-2);}else if(method==='kendall'){let c=0,ds=0,tx=0,ty=0;for(let x=0;x<n;x++)for(let y=x+1;y<n;y++){const dx=Math.sign(a[x]-a[y]),dy=Math.sign(b[x]-b[y]);if(dx===0&&dy===0)continue;if(dx===0)tx++;else if(dy===0)ty++;else if(dx===dy)c++;else ds++;}r=(c-ds)/Math.sqrt((c+ds+tx)*(c+ds+ty));const z=r*Math.sqrt(9*n*(n-1)/(2*(2*n+5)));p=pZ(z);}else{r=pearson(a,b);const t=r*Math.sqrt((n-2)/(1-r*r));p=pT(t,n-2);}rows.push({Variable1:cols[i],Variable2:cols[j],N:n,Coeficiente:safe(r),p:safe(p),Método:method});}res.json({analysis:'Correlaciones',rows});}catch(e){fail(res,e)}});
  api.post('/api/chi-square',(req,res)=>{try{const d=getData(req),{rLevels,cLevels,obs}=contingency(d.rows,req.body.row,req.body.column),rt=obs.map(r=>r.reduce((s,x)=>s+x,0)),ct=cLevels.map((_,j)=>obs.reduce((s,r)=>s+r[j],0)),N=rt.reduce((s,x)=>s+x,0);let chi=0;for(let i=0;i<obs.length;i++)for(let j=0;j<cLevels.length;j++){const e=rt[i]*ct[j]/N;if(e>0)chi+=(obs[i][j]-e)**2/e;}const df=(rLevels.length-1)*(cLevels.length-1),p=1-jStat.chisquare.cdf(chi,df),contingencyRows=rLevels.map((L,i)=>Object.assign({Fila:L},Object.fromEntries(cLevels.map((C,j)=>[C,obs[i][j]]))));res.json({analysis:'Chi cuadrada',contingency:contingencyRows,rows:[{'Chi-cuadrada de Pearson':safe(chi),gl:df,p:safe(p),N}]});}catch(e){fail(res,e)}});
  api.post('/api/fisher',(req,res)=>{try{const d=getData(req),{rLevels,cLevels,obs}=contingency(d.rows,req.body.row,req.body.column);if(rLevels.length!==2||cLevels.length!==2)throw new Error('La prueba exacta de Fisher requiere una tabla 2×2.');const p=fisher2x2(obs[0][0],obs[0][1],obs[1][0],obs[1][1]);res.json({analysis:'Exacta de Fisher',contingency:rLevels.map((L,i)=>Object.assign({Fila:L},Object.fromEntries(cLevels.map((C,j)=>[C,obs[i][j]])))),rows:[{'p exacta bilateral':p}]});}catch(e){fail(res,e)}});
  api.post('/api/regression-linear',(req,res)=>{try{const d=getData(req),r=linearRegression(d.rows,req.body.outcome,req.body.predictors||[]);res.json({analysis:'Regresión lineal',rows:r.coeff,fit:r.fit});}catch(e){fail(res,e)}});
  api.post('/api/regression-logistic',(req,res)=>{try{const d=getData(req),r=logisticRegression(d.rows,req.body.outcome,req.body.predictors||[]);res.json({analysis:'Regresión logística',rows:r.coeff,fit:r.fit});}catch(e){fail(res,e)}});
  api.post('/api/reliability',(req,res)=>{try{const d=getData(req),items=req.body.items||[],complete=d.rows.map(r=>items.map(i=>Number(r[i]))).filter(a=>a.every(Number.isFinite));if(items.length<2||complete.length<2)throw new Error('Seleccione al menos dos ítems y asegure casos completos.');const cols=items.map((_,j)=>complete.map(r=>r[j])),total=complete.map(r=>r.reduce((s,x)=>s+x,0)),alpha=items.length/(items.length-1)*(1-cols.reduce((s,a)=>s+variance(a),0)/variance(total)),rows=items.map((it,j)=>{const corr=pearson(cols[j],total.map((t,i)=>t-cols[j][i])),rest=cols.filter((_,k)=>k!==j),totRest=complete.map((r,i)=>r.reduce((s,x,k)=>k===j?s:s+x,0)),aDel=rest.length>1?rest.length/(rest.length-1)*(1-rest.reduce((s,a)=>s+variance(a),0)/variance(totRest)):null;return {Ítem:it,'Correlación ítem-total corregida':safe(corr),'Alfa si se elimina':safe(aDel)};});res.json({analysis:'Alfa de Cronbach y análisis de ítems',fit:[{N:complete.length,Ítems:items.length,'Alfa de Cronbach':safe(alpha)}],rows});}catch(e){fail(res,e)}});
  api.post('/api/epidemiology',(req,res)=>{try{const d=getData(req),{rLevels,cLevels,obs}=contingency(d.rows,req.body.row,req.body.column);if(rLevels.length!==2||cLevels.length!==2)throw new Error('RR, OR, RD y NNT requieren una tabla 2×2.');let [a,b]=obs[0]; let [c,dd]=obs[1];if([a,b,c,dd].some(x=>x===0)){a+=.5;b+=.5;c+=.5;dd+=.5;}const risk1=a/(a+b),risk0=c/(c+dd),rr=risk1/risk0,or=a*dd/(b*c),rd=risk1-risk0,nnt=rd?1/Math.abs(rd):null,seRR=Math.sqrt(1/a-1/(a+b)+1/c-1/(c+dd)),seOR=Math.sqrt(1/a+1/b+1/c+1/dd);res.json({analysis:'Medidas epidemiológicas 2×2',contingency:rLevels.map((L,i)=>Object.assign({Fila:L},Object.fromEntries(cLevels.map((C,j)=>[C,obs[i][j]])))),rows:[{Medida:'Riesgo relativo (RR)',Estimación:rr,'IC95% inferior':Math.exp(Math.log(rr)-1.96*seRR),'IC95% superior':Math.exp(Math.log(rr)+1.96*seRR)},{Medida:'Odds ratio (OR)',Estimación:or,'IC95% inferior':Math.exp(Math.log(or)-1.96*seOR),'IC95% superior':Math.exp(Math.log(or)+1.96*seOR)},{Medida:'Diferencia de riesgos (RD)',Estimación:rd,'IC95% inferior':null,'IC95% superior':null},{Medida:'NNT/NNH',Estimación:nnt,'IC95% inferior':null,'IC95% superior':null}]});}catch(e){fail(res,e)}});
  api.post('/api/roc',(req,res)=>{try{const d=getData(req),o=req.body.outcome,s=req.body.score,q=d.rows.map(r=>[Number(r[o]),Number(r[s])]).filter(x=>Number.isFinite(x[1])&&(x[0]===0||x[0]===1)),scores=q.map(x=>x[1]),y=q.map(x=>x[0]),R=ranks(scores),n1=y.filter(x=>x===1).length,n0=y.length-n1,sumR=R.reduce((z,r,i)=>z+(y[i]===1?r:0),0),auc=(sumR-n1*(n1+1)/2)/(n1*n0),thresholds=uniq(scores).map(Number).sort((a,b)=>a-b);let best=null;for(const t of thresholds){let tp=0,tn=0,fp=0,fn=0;q.forEach(([yy,sc])=>{const pred=sc>=t?1:0;if(yy===1&&pred===1)tp++;else if(yy===0&&pred===0)tn++;else if(yy===0)fp++;else fn++;});const sens=tp/(tp+fn),spec=tn/(tn+fp),J=sens+spec-1;if(!best||J>best.J)best={t,sens,spec,J};}res.json({analysis:'Curva ROC',fit:[{N:q.length,AUC:safe(auc),'Casos positivos':n1,'Casos negativos':n0}],rows:[{'Punto de corte (Youden)':best?.t??null,Sensibilidad:best?.sens??null,Especificidad:best?.spec??null,'Índice de Youden':best?.J??null}]});}catch(e){fail(res,e)}});
  api.post('/api/survival',(req,res)=>{
    try{
      const d=getData(req); const dur=req.body.duration; const ev=req.body.event; const g=req.body.group||null;
      const levels=g?uniq(d.rows.map(r=>r[g]).filter(v=>v!==null&&v!==undefined&&v!=='')):['Total'];
      const out=[]; const summary=[];
      for(const L of levels){
        const arr=d.rows.map(r=>({t:Number(r[dur]),e:Number(r[ev]),grp:g?String(r[g]):'Total'}))
          .filter(x=>Number.isFinite(x.t)&&(x.e===0||x.e===1)&&x.grp===L).sort((a,b)=>a.t-b.t);
        let surv=1; const times=uniq(arr.filter(x=>x.e===1).map(x=>x.t)).map(Number).sort((a,b)=>a-b);
        for(const t of times){
          const risk=arr.filter(x=>x.t>=t).length; const nEvents=arr.filter(x=>x.t===t&&x.e===1).length;
          surv*=1-nEvents/risk; out.push({Grupo:L,Tiempo:t,'En riesgo':risk,Eventos:nEvents,Supervivencia:surv});
        }
        const med=out.filter(r=>r.Grupo===L&&r.Supervivencia<=.5)[0]?.Tiempo??null;
        summary.push({Grupo:L,N:arr.length,Eventos:arr.filter(x=>x.e===1).length,'Mediana supervivencia':med});
      }
      res.json({analysis:'Kaplan–Meier',groups:summary,rows:out});
    }catch(e){fail(res,e)}
  });

};