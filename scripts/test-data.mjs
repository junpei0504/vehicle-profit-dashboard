import fs from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';
import ts from 'typescript';
import * as XLSX from 'xlsx';
const temp=path.resolve('.sites-runtime/tests');fs.mkdirSync(temp,{recursive:true});
for(const name of ['model','parse-excel']){let code=ts.transpileModule(fs.readFileSync(`app/${name}.ts`,'utf8'),{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.ES2022}}).outputText;code=code.replaceAll("'./model'","'./model.mjs'").replaceAll('"./model"','"./model.mjs"');fs.writeFileSync(`${temp}/${name}.mjs`,code);}
const {parseWorkbook,parseSheet}=await import(`${temp}/parse-excel.mjs`);
const {normalizeType,validateMonth,aggregate,previousMonth,numericKeys}=await import(`${temp}/model.mjs`);
// 架空のテストデータのみ。実際の車番・収支は使用しない。
const row=(code,plate,income,expense)=>{const values=Array(29).fill(0);values[0]=code;values[1]=plate;values[2]='';values[3]=10;values[4]=800;values[5]=1000;values[7]=income;values[8]=income/10;values[9]=income/1000;values[11]=income;values[26]=expense;values[27]=income-expense;return values;};
const total=(label,income,expense)=>{const values=Array(29).fill('');values[0]=label;values[11]=income;values[26]=expense;values[27]=income-expense;return values;};
const h=Array(29).fill('');h[0]='車両\nコード';h[1]='正式車両番号';h[11]='収入計';h[26]='支出計';h[27]='収益';
const sheet=XLSX.utils.aoa_to_sheet([['対象年月：','','2026/09～2026/09'],['営業所：','','テスト(営)'],h,[],row('00001','テスト100あ0001',100000,80000),total('3t・冷蔵計',100000,80000),h,[],row('00002','テスト100あ0002',200000,210000),total('3t冷蔵計',200000,210000),total('テスト(営)計',300000,290000),total('全社計',300000,290000)]);
const workbook=XLSX.utils.book_new();XLSX.utils.book_append_sheet(workbook,sheet,'2026.9');XLSX.utils.book_append_sheet(workbook,sheet,'97・197除く');
const bytes=XLSX.write(workbook,{bookType:'xlsx',type:'buffer'});const parsed=parseWorkbook(new Uint8Array(bytes),'sample.xlsx');assert.deepEqual(parsed.candidates,['2026.9']);const data=parseSheet(parsed.workbook,'2026.9','sample.xlsx','sample-hash');
assert.equal(data.records.length,2);assert.equal(data.records[0].type,data.records[1].type);assert.equal(data.records[0].code,'00001');assert.equal(aggregate(data.records).income,300000);assert.equal(aggregate(data.records).profit,10000);assert.equal(aggregate(data.records).rate,10000/300000*100);
assert.throws(()=>parseSheet(parsed.workbook,'97・197除く','sample.xlsx','x'),/通常シート/);
const missing=structuredClone(data);missing.records[0].income=null;assert.throws(()=>validateMonth(missing),/数値がありません/);
const duplicate=structuredClone(data);duplicate.records.push(duplicate.records[0]);assert.throws(()=>validateMonth(duplicate),/重複/);
const wrong=structuredClone(data);wrong.checks.find(x=>x.label==='全社計').income+=100;assert.throws(()=>validateMonth(wrong),/一致しません/);
assert.equal(normalizeType('3t・冷蔵'),normalizeType('3t冷蔵'));assert.equal(normalizeType('10tﾄﾞﾗｲ'),normalizeType('10tドライ'));assert.equal(previousMonth('2026-01'),'2025-12');assert.equal(aggregate([]).rate,null);
const zero={...data.records[0],income:0,profit:-10};assert.equal(aggregate([zero]).rate,null);assert.equal(aggregate([{...zero,income:100,profit:50},{...zero,income:900,profit:0}]).rate,5);
assert.deepEqual(JSON.parse(fs.readFileSync('app/seed-data.json','utf8')),[]);assert.deepEqual(JSON.parse(fs.readFileSync('app/server/seed-files.json','utf8')),{});
console.log('PASS Excel取り込み・表記統一・合計照合・重複拒否・欠損拒否・収益率・実データの除外');
