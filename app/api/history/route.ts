import {db,seed,json,error} from '../../server/store';
export async function GET(){try{await seed();const r=await db().prepare('SELECT id,month,file_name as fileName,sheet_name as sheetName,imported_at as importedAt,count,action FROM import_history ORDER BY imported_at DESC LIMIT 200').all();return json(r.results);}catch(e){return error(e);}}
