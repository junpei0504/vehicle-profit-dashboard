export const numericKeys = ['runs','loadedKm','totalKm','loadedRate','freight','revenuePerRun','revenuePerKm','highwayRevenue','income','tolls','fuelLiters','fuelUnitPrice','fuel','tires','supplies','inspection','repairs','accident','refrigeration','welfare','labor','fixed','indirect','expense','profit','expenseRate'] as const;
export type Metric = typeof numericKeys[number];
export type Vehicle = Record<Metric,number> & {code:string; plate:string; branch:string; type:string; rawType:string; sourceRow:number};
export type Control = {label:string;row:number;income:number;expense:number;profit:number};
export type MonthData = {month:string;fileName:string;sheetName:string;hash:string;records:Vehicle[];checks:Control[];warnings?:string[];updatedAt?:string};
export type History = {id:string;month:string;fileName:string;sheetName:string;importedAt:string;count:number;action:string};
export const costItems: {key:Metric;label:string;color:string}[] = [
 {key:'labor',label:'人件費',color:'#3478ef'},{key:'fuel',label:'燃料費',color:'#62a5fa'},
 {key:'fixed',label:'固定経費',color:'#8b8ad9'},{key:'indirect',label:'間接経費',color:'#a8b6cb'},
 {key:'tolls',label:'通行費',color:'#29adb5'},{key:'welfare',label:'福利厚生費',color:'#70c9c0'},
 {key:'tires',label:'タイヤ代',color:'#e8ad5a'},{key:'inspection',label:'車検点検整備費',color:'#d28e67'},
 {key:'repairs',label:'一般修理費',color:'#ed8793'},{key:'supplies',label:'消耗費',color:'#c0a77d'},
 {key:'accident',label:'事故修理',color:'#d26478'},{key:'refrigeration',label:'冷凍機修理費',color:'#92bc72'},
];
export function normalizeType(s:string) {return s.normalize('NFKC').replace(/[・･\s　]/g,'').replace(/^そのドライ$/,'その他ドライ') || '未分類';}
export function sum(rows:Vehicle[],key:Metric) {return rows.reduce((a,b)=>a+b[key],0);}
export function aggregate(rows:Vehicle[]) { const a=Object.fromEntries(numericKeys.map(k=>[k,sum(rows,k)])) as Record<Metric,number>;return {...a, count:rows.length, rate:a.income===0?null:a.profit/a.income*100, loadedRate:a.totalKm===0?null:a.loadedKm/a.totalKm*100};}
export function previousMonth(m:string) {const [y,n]=m.split('-').map(Number);return n===1?`${y-1}-12`:`${y}-${String(n-1).padStart(2,'0')}`;}
export function monthLabel(m:string) {const [y,n]=m.split('-');return `${y}年${Number(n)}月`;}
export function shortPlate(v:Vehicle) {return v.plate.match(/\d+$/)?.[0]||v.plate||`コード ${v.code}`;}
export function money(n:number) {return (n/10000).toLocaleString('ja-JP',{minimumFractionDigits:1,maximumFractionDigits:1});}
export function yen(n:number) {return n.toLocaleString('ja-JP',{maximumFractionDigits:2})+'円';}
export function validateMonth(d:MonthData) {
 if(!/^\d{4}-(0[1-9]|1[0-2])$/.test(d.month)) throw new Error('対象年月を判定できません。');
 if(!d.records.length||d.records.length>3000) throw new Error('明細件数が不正です（1〜3,000件）。');
 const ids=new Set<string>();
 for(const r of d.records) {
  if(!/^\d+$/.test(r.code)||!r.branch||!r.type) throw new Error(`行${r.sourceRow}: 車両コード・拠点・車種を確認してください。`);
  if(ids.has(r.code)) throw new Error(`車両コード ${r.code} が重複しています。`);ids.add(r.code);
  for(const k of numericKeys) if(typeof r[k]!=='number'||!Number.isFinite(r[k])) throw new Error(`行${r.sourceRow}: ${k} に数値がありません。空欄をゼロとして登録することはできません。`);
  if(Math.abs(r.income-r.expense-r.profit)>1) throw new Error(`行${r.sourceRow}: 収入−支出と収益が一致しません。`);
 }
 const total=d.checks.find(c=>c.label==='全社計');if(!total) throw new Error('全社計が見つかりません。通常シートを確認してください。');
 for(const k of ['income','expense','profit'] as const) if(Math.abs(sum(d.records,k)-total[k])>1) throw new Error(`全社計の${{income:'収入',expense:'支出',profit:'収益'}[k]}と明細合計が一致しません。`);
 for(const branch of new Set(d.records.map(r=>r.branch))) {
  const c=d.checks.find(c=>c.label.replace(/\(営\)/g,'')===branch+'計');
  if(!c) throw new Error(`${branch}の拠点合計が見つかりません。`);
  for(const k of ['income','expense','profit'] as const) if(Math.abs(sum(d.records.filter(r=>r.branch===branch),k)-c[k])>1) throw new Error(`${branch}の合計と明細が一致しません。`);
 }
 return true;
}
