import { pgTable, index, unique, serial, varchar, integer, text, timestamp } from "drizzle-orm/pg-core"
import { sql } from "drizzle-orm"



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

export const healthCheck = pgTable("health_check", {
	id: serial().notNull(),
	updatedAt: timestamp("updated_at", { withTimezone: true, mode: 'string' }).defaultNow(),
});
