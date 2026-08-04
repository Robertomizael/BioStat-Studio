from __future__ import annotations

import io, math, uuid
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from scipy import stats

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / 'static'
DATASETS: dict[str, pd.DataFrame] = {}
app = FastAPI(title='BioStat Studio', version='0.4.0')
app.mount('/static', StaticFiles(directory=STATIC_DIR), name='static')


def clean(v: Any) -> Any:
    if isinstance(v, dict): return {str(k): clean(x) for k,x in v.items()}
    if isinstance(v, (list,tuple,np.ndarray)): return [clean(x) for x in v]
    if isinstance(v, (np.integer,)): return int(v)
    if isinstance(v, (np.floating,float)): return None if not math.isfinite(float(v)) else float(v)
    if isinstance(v, (pd.Timestamp,)): return v.isoformat()
    if v is None: return None
    try:
        if pd.isna(v): return None
    except Exception: pass
    return v


def read_upload(filename: str, content: bytes) -> pd.DataFrame:
    s = Path(filename).suffix.lower()
    try:
        if s in {'.csv','.tsv','.txt'}:
            sep = '\t' if s == '.tsv' else None
            try: df = pd.read_csv(io.BytesIO(content), sep=sep, engine='python')
            except UnicodeDecodeError: df = pd.read_csv(io.BytesIO(content), sep=sep, engine='python', encoding='latin-1')
        elif s in {'.xlsx','.xls','.ods'}: df = pd.read_excel(io.BytesIO(content))
        elif s in {'.sav','.zsav','.por'}:
            import pyreadstat
            tmp = io.BytesIO(content)
            df,_ = pyreadstat.read_por(tmp) if s=='.por' else pyreadstat.read_sav(tmp, apply_value_formats=False)
        elif s=='.dta': df = pd.read_stata(io.BytesIO(content), convert_categoricals=False)
        elif s=='.sas7bdat': df = pd.read_sas(io.BytesIO(content), format='sas7bdat')
        else: raise HTTPException(415,'Formato no compatible.')
    except HTTPException: raise
    except Exception as e: raise HTTPException(400,f'No fue posible abrir el archivo: {e}')
    if df.empty: raise HTTPException(400,'El archivo no contiene registros.')
    df.columns=[str(c).strip() or f'variable_{i+1}' for i,c in enumerate(df.columns)]
    return df


def get_df(i:str)->pd.DataFrame:
    if i not in DATASETS: raise HTTPException(404,'La base ya no está disponible.')
    return DATASETS[i]

def num(df,c): return pd.to_numeric(df[c],errors='coerce')
def schema(df):
    out=[]
    for c in df.columns:
        s=df[c]; numeric=pd.api.types.is_numeric_dtype(s); u=int(s.nunique(dropna=True))
        level='Escala' if numeric and u>10 else ('Ordinal' if numeric and 2<u<=10 else 'Nominal')
        out.append({'name':c,'label':c,'type':'Numérica' if numeric else 'Cadena','level':level,'role':'Entrada','missing':int(s.isna().sum()),'unique':u,'decimals':2 if numeric else 0})
    return out

@app.get('/')
def index(): return FileResponse(STATIC_DIR/'index.html')
@app.get('/api/health')
def health(): return {'status':'ok','version':'0.4.0','credit':'Diseño y desarrollo: Dr. Roberto Joel Tirado Reyes'}
@app.post('/api/import')
async def import_data(file:UploadFile=File(...)):
    df=read_upload(file.filename or 'datos.csv',await file.read()); i=str(uuid.uuid4()); DATASETS[i]=df
    return clean({'dataset_id':i,'name':file.filename,'rows':len(df),'columns':len(df.columns),'variables':schema(df),'preview':df.head(250).to_dict('records')})

class BaseReq(BaseModel): dataset_id:str
class ColsReq(BaseReq): columns:list[str]
class OneReq(BaseReq): column:str
class GroupReq(BaseReq): outcome:str; group:str
class PairedReq(BaseReq): before:str; after:str
class CorrReq(ColsReq): method:str='pearson'
class OneSampleReq(BaseReq): column:str; mu:float=0
class AnovaReq(BaseReq): outcome:str; factor:str
class ChiReq(BaseReq): row:str; column:str
class RegressionReq(BaseReq): outcome:str; predictors:list[str]
class LogisticReq(BaseReq): outcome:str; predictors:list[str]; positive:Optional[str]=None
class ReliabilityReq(BaseReq): items:list[str]
class RocReq(BaseReq): outcome:str; score:str; positive:Optional[str]=None
class SurvivalReq(BaseReq): duration:str; event:str; group:Optional[str]=None
class SampleReq(BaseModel): kind:str; confidence:float=0.95; power:float=0.80; margin:float=0.05; proportion:float=0.5; population:Optional[int]=None; effect:float=0.5; groups:int=2; ratio:float=1.0; prevalence:float=0.5; sensitivity:float=0.8; specificity:float=0.8; correlation:float=0.3; dropout:float=0.0

@app.post('/api/descriptives')
def descriptives(r:ColsReq):
    df=get_df(r.dataset_id); rows=[]
    for c in r.columns:
        s=num(df,c).dropna(); n=len(s)
        if not n: continue
        se=s.std(ddof=1)/math.sqrt(n) if n>1 else np.nan; t=stats.t.ppf(.975,n-1) if n>1 else np.nan
        rows.append({'Variable':c,'N':n,'Perdidos':int(df[c].isna().sum()),'Media':s.mean(),'EE':se,'IC95% inferior':s.mean()-t*se,'IC95% superior':s.mean()+t*se,'Mediana':s.median(),'Moda':s.mode().iloc[0] if not s.mode().empty else np.nan,'DE':s.std(ddof=1),'Varianza':s.var(ddof=1),'Mínimo':s.min(),'Máximo':s.max(),'Rango':s.max()-s.min(),'Q1':s.quantile(.25),'Q3':s.quantile(.75),'RIC':s.quantile(.75)-s.quantile(.25),'CV %':100*s.std(ddof=1)/s.mean() if s.mean()!=0 else np.nan,'Asimetría':stats.skew(s,bias=False) if n>2 else np.nan,'Curtosis':stats.kurtosis(s,bias=False) if n>3 else np.nan})
    return clean({'analysis':'Estadísticos descriptivos','rows':rows})
@app.post('/api/frequencies')
def frequencies(r:OneReq):
    s=get_df(r.dataset_id)[r.column]; counts=s.fillna('(Perdido)').astype(str).value_counts(dropna=False); valid=s.notna().sum(); cum=0; rows=[]
    for k,v in counts.items():
        cum+=v; rows.append({'Categoría':k,'Frecuencia':int(v),'Porcentaje':100*v/len(s),'Porcentaje válido':100*v/valid if k!='(Perdido)' and valid else np.nan,'Acumulado':100*cum/len(s)})
    return clean({'analysis':f'Frecuencias: {r.column}','rows':rows})
@app.post('/api/normality')
def normality(r:ColsReq):
    df=get_df(r.dataset_id); rows=[]
    for c in r.columns:
        s=num(df,c).dropna(); n=len(s)
        if n<3: continue
        if n<=5000: stat,p=stats.shapiro(s)
        else: stat,p=stats.normaltest(s)
        rows.append({'Variable':c,'N':n,'Estadístico':stat,'p':p,'Conclusión':'Compatible con normalidad' if p>=.05 else 'Evidencia contra normalidad'})
    return clean({'analysis':'Pruebas de normalidad','rows':rows})
@app.post('/api/correlation')
def correlation(r:CorrReq):
    df=get_df(r.dataset_id); cols=[c for c in r.columns if c in df]; method=r.method if r.method in {'pearson','spearman','kendall'} else 'pearson'; rows=[]
    for i,a in enumerate(cols):
        for b in cols[i+1:]:
            z=df[[a,b]].apply(pd.to_numeric,errors='coerce').dropna()
            if len(z)<3: continue
            if method=='pearson': coef,p=stats.pearsonr(z[a],z[b])
            elif method=='spearman': coef,p=stats.spearmanr(z[a],z[b])
            else: coef,p=stats.kendalltau(z[a],z[b])
            rows.append({'Variable 1':a,'Variable 2':b,'N':len(z),'Coeficiente':coef,'p':p})
    return clean({'analysis':f'Correlaciones {method.title()}','rows':rows})
@app.post('/api/ttest-one')
def ttest_one(r:OneSampleReq):
    s=num(get_df(r.dataset_id),r.column).dropna(); t,p=stats.ttest_1samp(s,r.mu); d=(s.mean()-r.mu)/s.std(ddof=1)
    return clean({'analysis':'Prueba t para una muestra','rows':[{'Variable':r.column,'N':len(s),'Media':s.mean(),'Valor de prueba':r.mu,'t':t,'gl':len(s)-1,'p':p,'d de Cohen':d}]})
@app.post('/api/ttest')
def ttest(r:GroupReq):
    df=get_df(r.dataset_id); gs=df[r.group].dropna().unique().tolist()
    if len(gs)!=2: raise HTTPException(400,'La variable de grupo debe tener dos categorías.')
    a=num(df[df[r.group]==gs[0]],r.outcome).dropna(); b=num(df[df[r.group]==gs[1]],r.outcome).dropna(); lev,lp=stats.levene(a,b,center='median'); eq=lp>=.05; t,p=stats.ttest_ind(a,b,equal_var=eq); pooled=np.sqrt(((len(a)-1)*a.var(ddof=1)+(len(b)-1)*b.var(ddof=1))/(len(a)+len(b)-2)); d=(a.mean()-b.mean())/pooled
    return clean({'analysis':'Prueba t para muestras independientes','rows':[{'Grupo 1':gs[0],'n1':len(a),'Media 1':a.mean(),'DE 1':a.std(ddof=1),'Grupo 2':gs[1],'n2':len(b),'Media 2':b.mean(),'DE 2':b.std(ddof=1),'Levene':lev,'Levene p':lp,'Método':'Student' if eq else 'Welch','t':t,'p':p,'d de Cohen':d}]})
@app.post('/api/ttest-paired')
def ttest_paired(r:PairedReq):
    z=get_df(r.dataset_id)[[r.before,r.after]].apply(pd.to_numeric,errors='coerce').dropna(); t,p=stats.ttest_rel(z[r.before],z[r.after]); diff=z[r.after]-z[r.before]; d=diff.mean()/diff.std(ddof=1)
    return clean({'analysis':'Prueba t para muestras relacionadas','rows':[{'N':len(z),'Media antes':z[r.before].mean(),'Media después':z[r.after].mean(),'Diferencia media':diff.mean(),'t':t,'gl':len(z)-1,'p':p,'d pareada':d}]})
@app.post('/api/anova')
def anova(r:AnovaReq):
    df=get_df(r.dataset_id); groups=[]; labels=[]
    for k,g in df.groupby(r.factor,dropna=True):
        s=num(g,r.outcome).dropna()
        if len(s)>1: groups.append(s); labels.append(k)
    if len(groups)<2: raise HTTPException(400,'Se requieren al menos dos grupos.')
    f,p=stats.f_oneway(*groups); grand=pd.concat(groups).mean(); ssb=sum(len(g)*(g.mean()-grand)**2 for g in groups); sst=sum(((g-grand)**2).sum() for g in groups); eta=ssb/sst if sst else np.nan
    return clean({'analysis':'ANOVA de un factor','rows':[{'Fuente':'Entre grupos','F':f,'p':p,'Eta cuadrada':eta,'Grupos':len(groups),'N total':sum(map(len,groups))}],'groups':[{'Grupo':str(k),'N':len(g),'Media':g.mean(),'DE':g.std(ddof=1)} for k,g in zip(labels,groups)]})
@app.post('/api/nonparametric')
def nonparametric(r:AnovaReq):
    df=get_df(r.dataset_id); groups=[]
    for _,g in df.groupby(r.factor,dropna=True):
        s=num(g,r.outcome).dropna()
        if len(s): groups.append(s)
    if len(groups)==2: stat,p=stats.mannwhitneyu(groups[0],groups[1],alternative='two-sided'); name='Mann–Whitney U'
    else: stat,p=stats.kruskal(*groups); name='Kruskal–Wallis'
    return clean({'analysis':name,'rows':[{'Estadístico':stat,'p':p,'Grupos':len(groups),'N total':sum(map(len,groups))}]})
@app.post('/api/wilcoxon')
def wilcoxon(r:PairedReq):
    z=get_df(r.dataset_id)[[r.before,r.after]].apply(pd.to_numeric,errors='coerce').dropna(); stat,p=stats.wilcoxon(z[r.before],z[r.after]); return clean({'analysis':'Prueba de Wilcoxon','rows':[{'N':len(z),'W':stat,'p':p}]})
@app.post('/api/chi-square')
def chi_square(r:ChiReq):
    df=get_df(r.dataset_id); tab=pd.crosstab(df[r.row],df[r.column]); chi,p,dof,exp=stats.chi2_contingency(tab); n=tab.values.sum(); k=min(tab.shape); cram=math.sqrt(chi/(n*(k-1))) if k>1 else np.nan
    rows=[]
    for i in tab.index:
        for j in tab.columns: rows.append({r.row:str(i),r.column:str(j),'Observado':int(tab.loc[i,j]),'Esperado':float(exp[list(tab.index).index(i),list(tab.columns).index(j)])})
    return clean({'analysis':'Chi cuadrada de independencia','rows':[{'Chi cuadrada':chi,'gl':dof,'p':p,'V de Cramer':cram,'N':n}],'contingency':rows})
@app.post('/api/fisher')
def fisher(r:ChiReq):
    tab=pd.crosstab(get_df(r.dataset_id)[r.row],get_df(r.dataset_id)[r.column])
    if tab.shape!=(2,2): raise HTTPException(400,'Fisher requiere una tabla 2×2.')
    odds,p=stats.fisher_exact(tab.values); return clean({'analysis':'Prueba exacta de Fisher','rows':[{'Odds ratio':odds,'p bilateral':p}]})
@app.post('/api/regression-linear')
def regression_linear(r:RegressionReq):
    import statsmodels.api as sm
    df=get_df(r.dataset_id)[[r.outcome]+r.predictors].apply(pd.to_numeric,errors='coerce').dropna(); X=sm.add_constant(df[r.predictors]); m=sm.OLS(df[r.outcome],X).fit(); rows=[]
    for c in m.params.index: rows.append({'Variable':c,'B':m.params[c],'EE':m.bse[c],'t':m.tvalues[c],'p':m.pvalues[c],'IC95% inferior':m.conf_int().loc[c,0],'IC95% superior':m.conf_int().loc[c,1]})
    return clean({'analysis':'Regresión lineal múltiple','rows':rows,'fit':[{'N':int(m.nobs),'R cuadrada':m.rsquared,'R cuadrada ajustada':m.rsquared_adj,'F':m.fvalue,'p del modelo':m.f_pvalue,'AIC':m.aic,'BIC':m.bic}]})
@app.post('/api/regression-logistic')
def regression_logistic(r:LogisticReq):
    import statsmodels.api as sm
    raw=get_df(r.dataset_id)[[r.outcome]+r.predictors].dropna(); cats=raw[r.outcome].unique().tolist()
    if len(cats)!=2: raise HTTPException(400,'La variable dependiente debe ser dicotómica.')
    pos=r.positive if r.positive is not None else cats[-1]; y=(raw[r.outcome].astype(str)==str(pos)).astype(int); X=raw[r.predictors].apply(pd.to_numeric,errors='coerce'); z=pd.concat([y.rename('y'),X],axis=1).dropna(); X=sm.add_constant(z[r.predictors]); m=sm.Logit(z.y,X).fit(disp=False); rows=[]; ci=m.conf_int()
    for c in m.params.index: rows.append({'Variable':c,'B':m.params[c],'EE':m.bse[c],'Wald z':m.tvalues[c],'p':m.pvalues[c],'OR':math.exp(m.params[c]),'IC95% OR inferior':math.exp(ci.loc[c,0]),'IC95% OR superior':math.exp(ci.loc[c,1])})
    return clean({'analysis':'Regresión logística binaria','rows':rows,'fit':[{'N':int(m.nobs),'Log-verosimilitud':m.llf,'AIC':m.aic,'BIC':m.bic,'Pseudo R² McFadden':m.prsquared,'Categoría positiva':str(pos)}]})
@app.post('/api/reliability')
def reliability(r:ReliabilityReq):
    x=get_df(r.dataset_id)[r.items].apply(pd.to_numeric,errors='coerce').dropna(); k=x.shape[1]; total=x.sum(axis=1); alpha=k/(k-1)*(1-x.var(ddof=1).sum()/total.var(ddof=1)) if k>1 else np.nan; rows=[]
    for c in x.columns:
        rest=x.drop(columns=c); kt=rest.shape[1]; a=kt/(kt-1)*(1-rest.var(ddof=1).sum()/rest.sum(axis=1).var(ddof=1)) if kt>1 else np.nan; rows.append({'Ítem':c,'Media':x[c].mean(),'DE':x[c].std(ddof=1),'Correlación ítem-total corregida':x[c].corr(total-x[c]),'Alfa si se elimina':a})
    return clean({'analysis':'Análisis de confiabilidad','rows':rows,'fit':[{'N':len(x),'Ítems':k,'Alfa de Cronbach':alpha}]})
@app.post('/api/roc')
def roc(r:RocReq):
    from sklearn.metrics import roc_auc_score, roc_curve
    df=get_df(r.dataset_id)[[r.outcome,r.score]].dropna(); cats=df[r.outcome].unique().tolist()
    if len(cats)!=2: raise HTTPException(400,'El estado debe tener dos categorías.')
    pos=r.positive if r.positive is not None else cats[-1]; y=(df[r.outcome].astype(str)==str(pos)).astype(int); score=pd.to_numeric(df[r.score],errors='coerce'); z=pd.DataFrame({'y':y,'score':score}).dropna(); auc=roc_auc_score(z.y,z.score); fpr,tpr,thr=roc_curve(z.y,z.score); j=tpr-fpr; ix=int(np.argmax(j))
    return clean({'analysis':'Curva ROC','rows':[{'N':len(z),'AUC':auc,'Punto de corte óptimo':thr[ix],'Sensibilidad':tpr[ix],'Especificidad':1-fpr[ix],'Youden J':j[ix]}],'curve':[{'fpr':a,'tpr':b,'threshold':c} for a,b,c in zip(fpr,tpr,thr)]})
@app.post('/api/epidemiology')
def epidemiology(r:ChiReq):
    tab=pd.crosstab(get_df(r.dataset_id)[r.row],get_df(r.dataset_id)[r.column])
    if tab.shape!=(2,2): raise HTTPException(400,'Se requiere una tabla 2×2.')
    a,b,c,d=tab.values.flatten(); rr=(a/(a+b))/(c/(c+d)); orr=(a*d)/(b*c) if b*c else np.nan; rd=a/(a+b)-c/(c+d); se_logrr=math.sqrt(1/a-1/(a+b)+1/c-1/(c+d)); se_logor=math.sqrt(1/a+1/b+1/c+1/d)
    return clean({'analysis':'Medidas epidemiológicas 2×2','rows':[{'Riesgo grupo 1':a/(a+b),'Riesgo grupo 2':c/(c+d),'Riesgo relativo':rr,'IC95% RR inferior':math.exp(math.log(rr)-1.96*se_logrr),'IC95% RR superior':math.exp(math.log(rr)+1.96*se_logrr),'Odds ratio':orr,'IC95% OR inferior':math.exp(math.log(orr)-1.96*se_logor) if orr>0 else np.nan,'IC95% OR superior':math.exp(math.log(orr)+1.96*se_logor) if orr>0 else np.nan,'Diferencia de riesgos':rd,'NNT/NNH':1/abs(rd) if rd else np.nan}]})
@app.post('/api/survival')
def survival(r:SurvivalReq):
    from lifelines import KaplanMeierFitter
    df=get_df(r.dataset_id); rows=[]; curves=[]; groups=[('Total',df)] if not r.group else [(str(k),g) for k,g in df.groupby(r.group,dropna=True)]
    for name,g in groups:
        d=pd.to_numeric(g[r.duration],errors='coerce'); e=pd.to_numeric(g[r.event],errors='coerce'); z=pd.DataFrame({'d':d,'e':e}).dropna(); km=KaplanMeierFitter().fit(z.d,event_observed=z.e,label=name); rows.append({'Grupo':name,'N':len(z),'Eventos':int(z.e.sum()),'Mediana de supervivencia':km.median_survival_time_}); curves.extend([{'Grupo':name,'Tiempo':float(t),'Supervivencia':float(s)} for t,s in km.survival_function_[name].items()])
    return clean({'analysis':'Supervivencia Kaplan–Meier','rows':rows,'curve':curves})
@app.post('/api/sample-size')
def sample_size(r:SampleReq):
    from statsmodels.stats.power import TTestIndPower, NormalIndPower
    z=stats.norm.ppf(1-(1-r.confidence)/2); n=np.nan; note=''
    if r.kind=='proportion':
        n0=z*z*r.proportion*(1-r.proportion)/(r.margin*r.margin); n=n0 if not r.population else n0/(1+(n0-1)/r.population); note='Estimación de una proporción.'
    elif r.kind=='mean': n=(z*r.effect/r.margin)**2; note='Estimación de una media; efecto se interpreta como DE esperada.'
    elif r.kind=='two_means': n=TTestIndPower().solve_power(effect_size=r.effect,alpha=1-r.confidence,power=r.power,ratio=r.ratio,alternative='two-sided'); note='Por grupo en comparación de dos medias independientes.'
    elif r.kind=='two_proportions': n=NormalIndPower().solve_power(effect_size=r.effect,alpha=1-r.confidence,power=r.power,ratio=r.ratio,alternative='two-sided'); note='Por grupo; effect debe ser h de Cohen.'
    elif r.kind=='correlation':
        za=stats.norm.ppf(1-(1-r.confidence)/2); zb=stats.norm.ppf(r.power); n=((za+zb)/np.arctanh(abs(r.correlation)))**2+3; note='Detección de una correlación distinta de cero.'
    elif r.kind=='prevalence':
        n0=z*z*r.prevalence*(1-r.prevalence)/(r.margin*r.margin); n=n0 if not r.population else n0/(1+(n0-1)/r.population); note='Estudio de prevalencia.'
    elif r.kind=='diagnostic':
        p=min(r.sensitivity,r.specificity); n=z*z*p*(1-p)/(r.margin*r.margin); note='Casos positivos o negativos requeridos para precisión diagnóstica.'
    else: raise HTTPException(400,'Tipo de cálculo no reconocido.')
    adjusted=math.ceil(n/(1-r.dropout)) if r.dropout<1 else np.nan
    return clean({'analysis':'Cálculo de tamaño de muestra','rows':[{'Tamaño calculado':math.ceil(n),'Ajustado por pérdidas':adjusted,'Confianza':r.confidence,'Potencia':r.power,'Pérdidas previstas':r.dropout,'Método':note}]})

@app.get('/api/export/{dataset_id}.csv')
def export_csv(dataset_id:str):
    data=get_df(dataset_id).to_csv(index=False).encode('utf-8-sig'); return StreamingResponse(io.BytesIO(data),media_type='text/csv',headers={'Content-Disposition':'attachment; filename=BioStat_datos.csv'})
