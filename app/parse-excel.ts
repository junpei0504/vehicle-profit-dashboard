import * as XLSX from 'xlsx';
import {normalizeType,numericKeys,validateMonth,type MonthData,type Vehicle,type Control} from './model';
const clean=(v:unknown)=>String(v??'').normalize('NFKC').replace(/[\s　]/g,'');
export function parseWorkbook(bytes:ArrayBuffer|Uint8Array, fileName:string) {
 const workbook=XLSX.read(bytes,{type:'array',cellDates:false});
 const candidates=workbook.SheetNames.filter(n=>!/[除外]|除く|除$/.test(n));
 if(!candidates.length) throw new Error('通常シートが見つかりません。「除外」シートは取り込み対象外です。');
 return {workbook,candidates};
}
export function parseSheet(workbook:XLSX.WorkBook,sheetName:string,fileName:string,hash:string):MonthData {
 if(/[除外]|除く|除$/.test(sheetName))throw new Error('通常シートを選択してください。');
 const rows=XLSX.utils.sheet_to_json<unknown[]>(workbook.Sheets[sheetName],{header:1,defval:'',raw:true});
 let month='',branch='',header=false,pending:Vehicle[]=[];const records:Vehicle[]=[],checks:Control[]=[],warnings:string[]=[];
 for(let i=0;i<rows.length;i++) {
  const v=rows[i],a=clean(v[0]);
  if(a==='対象年月:') {const m=clean(v[2]).match(/(\d{4})\/(\d{2})[~〜～](\d{4})\/(\d{2})/);if(!m)throw new Error('単月の対象年月が読み取れません。');if(m[1]!==m[3]||m[2]!==m[4])throw new Error('1か月ごとの帳票をアップロードしてください。');const next=`${m[1]}-${m[2]}`;if(month&&month!==next)throw new Error('シート内に複数の対象月があります。');month=next;}
  if(a==='営業所:'&&clean(v[2])!=='全営業所') {const next=clean(v[2]).replace(/\(営\)/g,'');if(pending.length&&branch!==next)throw new Error('車種小計がない明細があります。');branch=next;}
  if(a==='車両コード') {
   if(clean(v[1])!=='正式車両番号'||clean(v[11])!=='収入計'||clean(v[26])!=='支出計'||clean(v[27])!=='収益') throw new Error('帳票の列構成が異なります。元の車両別収支実績表を使用してください。');
   header=true;
  }
  if(header&&/^\d+$/.test(a)) {
   if(!branch)throw new Error(`行${i+1}: 営業所が不明です。`);
   const code=a.padStart(5,'0');const data:Record<string,unknown>={code,plate:String(v[1]??'').trim(),branch,sourceRow:i+1};
   numericKeys.forEach((key,k)=>{const val=v[k+3];if(val===''||val==null)throw new Error(`行${i+1}: 数値が空欄です。除外シートではなく通常シートを確認してください。`);const n=typeof val==='number'?val:Number(String(val).replace(/,/g,''));if(!Number.isFinite(n))throw new Error(`行${i+1}: 数値を読み取れません。`);data[key]=n;});
   pending.push(data as Vehicle);
  }
  if(a.endsWith('計')&&a!=='収入計') {
   if(a!==branch+'計'&&a!==branch+'(営)計'&&a!=='全社計'&&pending.length) {const rawType=String(v[0]).replace(/計$/,'').trim()||'未分類';for(const r of pending)records.push({...r,rawType,type:normalizeType(rawType)});pending=[];}
   if(typeof v[11]==='number'&&typeof v[26]==='number'&&typeof v[27]==='number') checks.push({label:String(v[0]),row:i+1,income:v[11],expense:v[26],profit:v[27]});
  }
 }
 if(pending.length)throw new Error('車種小計がない明細が残っています。');
 if(records.some(r=>r.type==='未分類'))warnings.push('車種名がない明細は「未分類」で保存します。データ管理から分類できます。');
 const blanks=records.filter(r=>!r.plate).length;if(blanks)warnings.push(`車番が空欄の明細 ${blanks}件は車両コードで表示します。`);
 if(records.some(r=>r.income===0&&r.expense!==0))warnings.push('収入ゼロで経費がある明細も集計に含めています。');
 const data={month,fileName,sheetName,hash,records,checks,warnings};validateMonth(data);return data;
}
