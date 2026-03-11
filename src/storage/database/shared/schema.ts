import { pgTable, index, unique, serial, varchar, integer, text, timestamp } from "drizzle-orm/pg-core"
import { sql } from "drizzle-orm"

// 卡密数据表（资源库数据库）
export const cardKeysTable = pgTable("card_keys_table", {
	id: serial().notNull(),
	sysPlatform: varchar("sys_platform", { length: 50 }).notNull().default('扣子'),
	uuid: varchar("uuid", { length: 100 }),
	bstudioCreateTime: timestamp("bstudio_create_time", { withTimezone: true, mode: 'string' }).defaultNow(),
	keyValue: varchar("key_value", { length: 50 }).notNull(),
	status: integer().notNull().default(1),
	userNote: varchar("user_note", { length: 200 }),
	feishuUrl: text("feishu_url"),
	feishuPassword: varchar("feishu_password", { length: 100 }),
}, (table) => [
	unique("card_keys_table_key_value_idx").on(table.keyValue),
]);

// 健康检查表
export const healthCheck = pgTable("health_check", {
	id: serial().notNull(),
	updatedAt: timestamp("updated_at", { withTimezone: true, mode: 'string' }).defaultNow(),
});

// 旧表（保留兼容）
export const cardKeys = pgTable("card_keys", {
	id: serial().notNull(),
	keyValue: varchar("key_value", { length: 50 }).notNull(),
	status: integer().default(1).notNull(),
	orderId: varchar("order_id", { length: 100 }),
	productName: varchar("product_name", { length: 200 }),
	feishuUrl: text("feishu_url").notNull(),
	feishuPassword: varchar("feishu_password", { length: 100 }),
	createdAt: timestamp("created_at", { withTimezone: true, mode: 'string' }).defaultNow().notNull(),
	updatedAt: timestamp("updated_at", { withTimezone: true, mode: 'string' }).defaultNow(),
}, (table) => [
	index("card_keys_key_value_idx").using("btree", table.keyValue.asc().nullsLast().op("text_ops")),
	index("card_keys_status_idx").using("btree", table.status.asc().nullsLast().op("int4_ops")),
	unique("card_keys_key_value_unique").on(table.keyValue),
]);
