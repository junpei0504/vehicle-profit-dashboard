import {env} from 'cloudflare:workers';
import {parseWorkbook,parseSheet} from '../../parse-excel';
import {db,seed,guardWrite,json,error,save} from '../../server/store';
export async function POST(req:Request){try{
 guardWrite(req);await seed();const form=await req.formData(),file=form.get('file'),sheet=String(form.get('sheet')||''),expected=String(form.get('expectedHash')||'')||null;
 if(!(file instanceof File)||!file.name.match(/\.(xlsx|xls)$/i))throw new Error('Excelファイルを選択してください。');
 if(file.size>12*1024*1024)throw new Error('12MB以下のファイルを選択してください。');
 const bytes=await file.arrayBuffer(),hash=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',bytes)),x=>x.toString(16).padStart(2,'0')).join('');
 const {workbook,candidates}=parseWorkbook(bytes,file.name);if(!candidates.includes(sheet))throw new Error('通常シートを選択してください。');
 const data=parseSheet(workbook,sheet,file.name,hash);const current=await db().prepare('SELECT hash FROM months WHERE month=?').bind(data.month).first<{hash:string}>();
 if(current?.hash===hash)return json({skipped:true,month:data.month,message:'同じファイルが登録済みです。'});
 if((current?.hash||null)!==expected) return json({error:'登録済みデータが変わっています。再読み込みして差し替え内容を確認してください。'},409);
 if(!env.BUCKET)throw new Error('元ファイルの保存先に接続できません。');const key=`original/${hash}.${file.name.split('.').pop()}`;await env.BUCKET.put(key,bytes);
 await save(data,expected,key,req.headers.get('oai-authenticated-user-email')||'管理者',current?'差し替え':'追加');return json({month:data.month,count:data.records.length});
 }catch(e){return error(e);}}
