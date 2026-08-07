'use strict';
const { app, BrowserWindow, shell } = require('electron');
const { execFile } = require('child_process');
const express = require('express');
const multer = require('multer');
const Papa = require('papaparse');
const XLSX = require('xlsx');
const ss = require('simple-statistics');
const { jStat } = require('jstat');
const path = require('path');
const crypto = require('crypto');
const fs = require('fs');
const os = require('os');
const registerStats = require('./stats');

const datasets = new Map();
let server;
const finite = v => v !== null && v !== '' && Number.isFinite(Number(v));
const nums = (rows, col) => rows.map(r => Number(r[col])).filter(Number.isFinite);
const safe = x => Number.isFinite(x) ? x : null;
const mean = a => a.length ? ss.mean(a) : null;
const sd = a => a.length > 1 ? ss.sampleStandardDeviation(a) : null;

function importerPath(){
  const exe=process.platform==='win32'?'biostat-importer.exe':'biostat-importer';
  return app.isPackaged?path.join(process.resourcesPath,'importer',exe):path.join(__dirname,'dist-importer',exe);
}
function importWithReadStat(buffer,originalName){
  return new Promise((resolve,reject)=>{
    const dir=fs.mkdtempSync(path.join(os.tmpdir(),'biostat-'));const input=path.join(dir,path.basename(originalName));fs.writeFileSync(input,buffer);
    execFile(importerPath(),['import',input],{maxBuffer:500*1024*1024,windowsHide:true},(err,stdout,stderr)=>{
      fs.rmSync(dir,{recursive:true,force:true});if(err)return reject(new Error((stderr||err.message||'No fue posible importar el archivo').trim()));
      try{resolve(JSON.parse(stdout));}catch{reject(new Error('El motor de importación devolvió una respuesta inválida.'));}
    });
  });
}
function normalize(rows){return rows.filter(r=>Object.values(r).some(v=>v!==null&&String(v).trim()!=='')).map(r=>Object.fromEntries(Object.entries(r).map(([k,v])=>{if(v===undefined||v===null||String(v).trim()==='')return[String(k).trim(),null];const n=Number(v);return[String(k).trim(),Number.isFinite(n)?n:String(v).trim()];})));}
function variables(rows){return Object.keys(rows[0]||{}).map(name=>{const values=rows.map(r=>r[name]).filter(v=>v!==null&&v!=='');const numeric=values.length&&values.every(finite);return{name,type:numeric?'numeric':'string',decimals:numeric?2:0,label:'',missing:'Ninguno',level:numeric?'Escala':'Nominal',role:'Entrada',values:{}};});}
function getData(req){const d=datasets.get(req.body.dataset_id);if(!d)throw new Error('Base de datos no encontrada. Vuelva a sincronizar.');return d;}
function fail(res,e){res.status(400).json({detail:e.message||String(e)});}

function createServer(){
  const api=express();const upload=multer({storage:multer.memoryStorage(),limits:{fileSize:100*1024*1024}});api.use(express.json({limit:'10mb'}));api.use(express.static(path.join(__dirname,'public')));
  api.post('/api/import',upload.single('file'),async(req,res)=>{try{
    if(!req.file)throw new Error('Seleccione un archivo.');const ext=path.extname(req.file.originalname).toLowerCase();let rows=[],vars=null,name=path.basename(req.file.originalname,ext);
    if(['.csv','.tsv','.txt'].includes(ext)){const parsed=Papa.parse(req.file.buffer.toString('utf8').replace(/^\uFEFF/,''),{header:true,dynamicTyping:true,skipEmptyLines:true,delimiter:ext==='.tsv'?'\t':''});if(parsed.errors.length&&!parsed.data.length)throw new Error(parsed.errors[0].message);rows=parsed.data;}
    else if(['.xlsx','.xls','.ods'].includes(ext)){const wb=XLSX.read(req.file.buffer,{type:'buffer',cellDates:true});rows=XLSX.utils.sheet_to_json(wb.Sheets[wb.SheetNames[0]],{defval:null});}
    else if(['.sav','.zsav','.por','.dta','.sas7bdat','.xpt'].includes(ext)){const imported=await importWithReadStat(req.file.buffer,req.file.originalname);rows=imported.rows;vars=imported.variables;name=imported.name||name;}
    else throw new Error('Use CSV, TSV, TXT, XLSX, XLS, ODS, SAV, ZSAV, POR, DTA, SAS7BDAT o XPT.');
    rows=normalize(rows);if(!rows.length)throw new Error('El archivo no contiene datos utilizables.');const dataset_id=crypto.randomUUID();vars=vars||variables(rows);datasets.set(dataset_id,{name,rows,variables:vars});res.json({dataset_id,name,rows:rows.length,columns:vars.length,preview:rows.slice(0,5000),variables:vars});
  }catch(e){fail(res,e)}});
  api.get('/api/export/:id.csv',(req,res)=>{const d=datasets.get(req.params.id);if(!d)return res.status(404).send('Base no encontrada');res.type('text/csv').attachment(`${d.name||'datos'}.csv`).send('\uFEFF'+Papa.unparse(d.rows));});
  api.post('/api/descriptives',(req,res)=>{try{const d=getData(req),rows=(req.body.columns||[]).map(c=>{const a=nums(d.rows,c);return{Variable:c,N:a.length,Media:mean(a),Mediana:a.length?ss.median(a):null,'Desv. estándar':sd(a),Varianza:a.length>1?ss.sampleVariance(a):null,Mínimo:a.length?Math.min(...a):null,Máximo:a.length?Math.max(...a):null};});res.json({analysis:'Estadísticos descriptivos',rows});}catch(e){fail(res,e)}});
  api.post('/api/frequencies',(req,res)=>{try{const d=getData(req),c=req.body.column,m=new Map();d.rows.forEach(r=>{const k=String(r[c]??'(Perdido)');m.set(k,(m.get(k)||0)+1)});res.json({analysis:`Frecuencias · ${c}`,rows:[...m].map(([Valor,Frecuencia])=>({Valor,Frecuencia,Porcentaje:100*Frecuencia/d.rows.length}))});}catch(e){fail(res,e)}});
  api.post('/api/normality',(req,res)=>{try{const d=getData(req),rows=(req.body.columns||[]).map(c=>{const a=nums(d.rows,c),n=a.length;if(n<3)return{Variable:c,N:n,'Jarque–Bera':null,p:null,Interpretación:'Muestra insuficiente'};const m=mean(a),s=Math.sqrt(a.reduce((q,x)=>q+(x-m)**2,0)/n);if(!s)return{Variable:c,N:n,'Jarque–Bera':0,p:1,Interpretación:'Variable constante'};const sk=a.reduce((q,x)=>q+((x-m)/s)**3,0)/n,ku=a.reduce((q,x)=>q+((x-m)/s)**4,0)/n,jb=n/6*(sk**2+(ku-3)**2/4),p=1-jStat.chisquare.cdf(jb,2);return{Variable:c,N:n,'Jarque–Bera':safe(jb),p:safe(p),Interpretación:p<.05?'Distribución no normal':'Sin evidencia contra normalidad'};});res.json({analysis:'Pruebas de normalidad',rows});}catch(e){fail(res,e)}});
  api.post('/api/sample-size',(req,res)=>{try{const b=req.body,alpha=1-(b.confidence||.95),z=jStat.normal.inv(1-alpha/2,0,1),power=b.power||.8,zb=jStat.normal.inv(power,0,1),drop=b.dropout||0;let n;if(['proportion','prevalence'].includes(b.kind)){const p=b.kind==='prevalence'?(b.prevalence||.5):(b.proportion||.5),e=b.margin||.05;n=z*z*p*(1-p)/(e*e);if(b.population)n=n/(1+(n-1)/b.population);}else if(b.kind==='mean')n=(z*(b.effect||.5)/(b.margin||.05))**2;else if(b.kind==='two_means')n=2*((z+zb)/(b.effect||.5))**2;else if(b.kind==='two_proportions'){const p1=b.proportion||.5,p2=Math.max(.001,Math.min(.999,p1-(b.effect||.1))),pbar=(p1+p2)/2;n=((z*Math.sqrt(2*pbar*(1-pbar))+zb*Math.sqrt(p1*(1-p1)+p2*(1-p2)))**2)/(p1-p2)**2;}else if(b.kind==='correlation'){const r=b.correlation||.3;n=((z+zb)/(.5*Math.log((1+r)/(1-r))))**2+3;}else if(b.kind==='diagnostic'){const prev=b.prevalence||.5,se=b.sensitivity||.8,sp=b.specificity||.8,e=b.margin||.05;n=Math.max(z*z*se*(1-se)/(e*e*prev),z*z*sp*(1-sp)/(e*e*(1-prev)));}else n=z*z*.25/((b.margin||.05)**2);n=Math.ceil(n/(1-drop));res.json({analysis:'Cálculo de tamaño de muestra',rows:[{Diseño:b.kind,'Tamaño mínimo':n,'Pérdidas previstas (%)':100*drop}]});}catch(e){fail(res,e)}});
  registerStats(api,datasets,{ss,jStat});
  api.use('/api',(req,res)=>res.status(404).json({detail:'Procedimiento no encontrado.'}));
  return new Promise(resolve=>{server=api.listen(0,'127.0.0.1',()=>resolve(server.address().port));});
}
async function createWindow(){const port=await createServer();const win=new BrowserWindow({width:1500,height:920,minWidth:1050,minHeight:700,show:false,backgroundColor:'#e9edf2',webPreferences:{contextIsolation:true,nodeIntegration:false,sandbox:true}});win.removeMenu();win.once('ready-to-show',()=>win.show());win.webContents.setWindowOpenHandler(({url})=>{shell.openExternal(url);return{action:'deny'}});await win.loadURL(`http://127.0.0.1:${port}`);}
app.whenReady().then(createWindow);app.on('window-all-closed',()=>{if(server)server.close();if(process.platform!=='darwin')app.quit();});app.on('activate',()=>{if(BrowserWindow.getAllWindows().length===0)createWindow();});