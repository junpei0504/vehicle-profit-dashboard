import { sqliteTable, text, integer } from 'drizzle-orm/sqlite-core';
export const months = sqliteTable('months', {
 month: text('month').primaryKey(), payload: text('payload').notNull(), hash: text('hash').notNull(), updatedAt: text('updated_at').notNull(), fileKey: text('file_key'),
});
export const importHistory = sqliteTable('import_history', {
 id: text('id').primaryKey(), month: text('month').notNull(), fileName: text('file_name').notNull(), sheetName: text('sheet_name').notNull(), hash: text('hash').notNull(), importedAt: text('imported_at').notNull(), actor: text('actor').notNull(), count: integer('count').notNull(), payload: text('payload').notNull(), fileKey: text('file_key'), action: text('action').notNull(),
});
export const settings = sqliteTable('settings', { key: text('key').primaryKey(), value: text('value').notNull() });
