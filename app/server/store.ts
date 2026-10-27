import { env } from 'cloudflare:workers';
import seedData from '../seed-data.json';
import seedFiles from './seed-files.json';
import type {MonthData} from '../model';
export const ADMIN_EMAIL = env.ADMIN_EMAIL?.toLowerCase() || ''; 
export function isAdmin(req:Request) {const id=req.headers.get('oai-authenticated-user-id');const local=process.env.NODE_ENV==='development';return local&&!id || !!ADMIN_EMAIL&&req.headers.get('oai-authenticated-user-email')?.toLowerCase()===ADMIN_EMAIL;}
export function guardWrite(req:Request) {const origin=req.headers.get('origin');if(origin&&origin!==new URL(req.url).origin)throw new Error('別サイトからの更新は許可されていません。');if(!isAdmin(req))throw new Error('更新は管理者のみ行えます。');}
export function db(){if(!env.DB)throw new Error('共有データの保存先に接続できません。');return env.DB;}
export function json(data:unknown,status=200){return Response.json(data,{status,headers:{'Cache-Control':'no-store'}});}
export function error(e:unknown){return json({error:e instanceof Error?e.message:'処理に失敗しました。'},400);}
export async function seed(){
 const database=db();const flag=await database.prepare("SELECT value FROM settings WHERE key='initialized'").first();if(flag)return;
 const now=new Date().toISOString();
 const commands=[];
 for(const d of seedData as MonthData[]){
  const key=`original/${d.hash}.xls`;if(env.BUCKET)await env.BUCKET.put(key,Uint8Array.from(atob((seedFiles as Record<string,string>)[d.fileName]),c=>c.charCodeAt(0)));
  const payload=JSON.stringify({...d,updatedAt:now});
  commands.push(database.prepare('INSERT OR IGNORE INTO months(month,payload,hash,updated_at,file_key) VALUES(?,?,?,?,?)').bind(d.month,payload,d.hash,now,key));
  commands.push(database.prepare('INSERT OR IGNORE INTO import_history(id,month,file_name,sheet_name,hash,imported_at,actor,count,payload,file_key,action) VALUES(?,?,?,?,?,?,?,?,?,?,?)').bind('initial-'+d.month,d.month,d.fileName,d.sheetName,d.hash,now,ADMIN_EMAIL,d.records.length,payload,key,'初期登録'));
 }
 commands.push(database.prepare("INSERT OR IGNORE INTO settings(key,value) VALUES('initialized','1')"));await database.batch(commands);
}
export async function datasets(){await seed();const result=await db().prepare('SELECT payload FROM months ORDER BY month').all<{payload:string}>();return result.results.map(r=>JSON.parse(r.payload) as MonthData);}
export async function save(d:MonthData,expectedHash:string|null,fileKey:string|null,actor:string,action:string){
 const database=db(),now=new Date().toISOString(),id=crypto.randomUUID(),payload=JSON.stringify({...d,updatedAt:now});
 const history=database.prepare('INSERT INTO import_history(id,month,file_name,sheet_name,hash,imported_at,actor,count,payload,file_key,action) SELECT ?,?,?,?,?,?,?,?,?,?,? WHERE (? IS NULL AND NOT EXISTS(SELECT 1 FROM months WHERE month=?)) OR EXISTS(SELECT 1 FROM months WHERE month=? AND hash=?)').bind(id,d.month,d.fileName,d.sheetName,d.hash,now,actor,d.records.length,payload,fileKey,action,expectedHash,d.month,d.month,expectedHash);
 const update=database.prepare('INSERT INTO months(month,payload,hash,updated_at,file_key) VALUES(?,?,?,?,?) ON CONFLICT(month) DO UPDATE SET payload=excluded.payload,hash=excluded.hash,updated_at=excluded.updated_at,file_key=excluded.file_key WHERE months.hash=?').bind(d.month,payload,d.hash,now,fileKey,expectedHash);
 const results=await database.batch([history,update]);if(!results[0].meta.changes||!results[1].meta.changes)throw new Error('別の更新が先に保存されました。再読み込みしてやり直してください。');return id;
}
