import { pgTable, serial, timestamp, uniqueIndex, index, varchar, integer, text, boolean, date, jsonb, unique } from "drizzle-orm/pg-core"
import { sql } from "drizzle-orm"



export const healthCheck = pgTable("health_check", {
	id: serial().notNull(),
	updatedAt: timestamp("updated_at", { withTimezone: true, mode: 'string' }).defaultNow(),
});

export const cardKeysTable = pgTable("card_keys_table", {
	id: serial().primaryKey().notNull(),
	sysPlatform: varchar("sys_platform", { length: 50 }).default('扣子').notNull(),
	uuid: varchar({ length: 100 }),
	bstudioCreateTime: timestamp("bstudio_create_time", { withTimezone: true, mode: 'string' }).defaultNow(),
	keyValue: varchar("key_value", { length: 50 }).notNull(),
	status: integer().default(1).notNull(),
	userNote: varchar("user_note", { length: 200 }),
	feishuUrl: text("feishu_url"),
	feishuPassword: varchar("feishu_password", { length: 100 }),
	expireAt: timestamp("expire_at", { withTimezone: true, mode: 'string' }),
	usedCount: integer("used_count").default(0).notNull(),
	lastUsedAt: timestamp("last_used_at", { withTimezone: true, mode: 'string' }),
	maxUses: integer("max_uses").default(1).notNull(),
	devices: text().default('[]'),
	maxDevices: integer("max_devices").default(5),
	saleStatus: varchar("sale_status", { length: 20 }).default('unsold'),
	orderId: varchar("order_id", { length: 100 }),
	soldAt: timestamp("sold_at", { withTimezone: true, mode: 'string' }),
	salesChannel: varchar("sales_channel", { length: 50 }).default('),
	linkName: varchar("link_name", { length: 100 }).default('),
	expireAfterDays: integer("expire_after_days"),
	cardTypeId: integer("card_type_id"),
	activatedAt: timestamp("activated_at", { withTimezone: true, mode: 'string' }),
}, (table) => [
	uniqueIndex("card_keys_table_key_value_idx").using("btree", table.keyValue.asc().nullsLast().op("text_ops")),
	index("ix_card_keys_card_type_id").using("btree", table.cardTypeId.asc().nullsLast().op("int4_ops")),
]);

export const accessLogs = pgTable("access_logs", {
	id: serial().primaryKey().notNull(),
	cardKeyId: integer("card_key_id"),
	keyValue: varchar("key_value", { length: 50 }).notNull(),
	ipAddress: varchar("ip_address", { length: 50 }),
	userAgent: varchar("user_agent", { length: 500 }),
	success: boolean().default(false).notNull(),
	errorMsg: varchar("error_msg", { length: 200 }),
	accessTime: timestamp("access_time", { withTimezone: true, mode: 'string' }).defaultNow(),
	accessDate: date("access_date"),
	deviceType: varchar("device_type", { length: 20 }),
	contentLoaded: boolean("content_loaded"),
	sessionDuration: integer("session_duration"),
	ipProvince: varchar("ip_province", { length: 50 }),
	accessHour: integer("access_hour"),
	salesChannel: varchar("sales_channel", { length: 100 }),
	isFirstAccess: boolean("is_first_access").default(false),
}, (table) => [
	index("idx_access_logs_access_date").using("btree", table.accessDate.asc().nullsLast().op("date_ops")),
	index("idx_access_logs_access_hour").using("btree", table.accessHour.asc().nullsLast().op("int4_ops")),
	index("idx_access_logs_device_type").using("btree", table.deviceType.asc().nullsLast().op("text_ops")),
	index("idx_access_logs_ip_province").using("btree", table.ipProvince.asc().nullsLast().op("text_ops")),
	index("idx_access_logs_is_first_access").using("btree", table.isFirstAccess.asc().nullsLast().op("bool_ops")),
	index("idx_access_logs_sales_channel").using("btree", table.salesChannel.asc().nullsLast().op("text_ops")),
	index("ix_access_logs_access_time").using("btree", table.accessTime.asc().nullsLast().op("timestamptz_ops")),
	index("ix_access_logs_card_key_id").using("btree", table.cardKeyId.asc().nullsLast().op("int4_ops")),
	index("ix_access_logs_key_value").using("btree", table.keyValue.asc().nullsLast().op("text_ops")),
]);

export const batchOperationLogs = pgTable("batch_operation_logs", {
	id: serial().primaryKey().notNull(),
	operator: varchar({ length: 50 }).default('admin').notNull(),
	operationType: varchar("operation_type", { length: 50 }).notNull(),
	filterConditions: jsonb("filter_conditions"),
	affectedCount: integer("affected_count").default(0).notNull(),
	affectedIds: integer("affected_ids").array(),
	updateFields: jsonb("update_fields"),
	remark: text(),
	createdAt: timestamp("created_at", { withTimezone: true, mode: 'string' }).defaultNow(),
});

export const adminSettings = pgTable("admin_settings", {
	id: serial().primaryKey().notNull(),
	key: varchar({ length: 50 }).notNull(),
	value: text().notNull(),
	createdAt: timestamp("created_at", { withTimezone: true, mode: 'string' }).defaultNow(),
	updatedAt: timestamp("updated_at", { withTimezone: true, mode: 'string' }).defaultNow(),
}, (table) => [
	unique("admin_settings_key_key").on(table.key),
]);

export const cardTypes = pgTable("card_types", {
	id: serial().primaryKey().notNull(),
	name: varchar({ length: 200 }).notNull(),
	previewImage: text("preview_image"),
	previewEnabled: boolean("preview_enabled").default(false),
	status: integer().default(1),
	deletedAt: timestamp("deleted_at", { withTimezone: true, mode: 'string' }),
	createdAt: timestamp("created_at", { withTimezone: true, mode: 'string' }).defaultNow(),
	updatedAt: timestamp("updated_at", { withTimezone: true, mode: 'string' }).defaultNow(),
	previewImageId: integer("preview_image_id"),
	blurLevel: integer("blur_level").default(8),
}, (table) => [
	index("ix_card_types_name").using("btree", table.name.asc().nullsLast().op("text_ops")),
	index("ix_card_types_status").using("btree", table.status.asc().nullsLast().op("int4_ops")),
]);

export const linkHealthTable = pgTable("link_health_table", {
	id: serial().primaryKey().notNull(),
	feishuUrl: text("feishu_url").notNull(),
	linkName: varchar("link_name", { length: 200 }),
	status: varchar({ length: 20 }).default('unknown').notNull(),
	httpCode: integer("http_code"),
	errorMessage: varchar("error_message", { length: 500 }),
	lastCheckTime: timestamp("last_check_time", { withTimezone: true, mode: 'string' }),
	nextCheckTime: timestamp("next_check_time", { withTimezone: true, mode: 'string' }),
	consecutiveFailures: integer("consecutive_failures").default(0),
	totalChecks: integer("total_checks").default(0),
	successfulChecks: integer("successful_checks").default(0),
	createdAt: timestamp("created_at", { withTimezone: true, mode: 'string' }).defaultNow(),
	updatedAt: timestamp("updated_at", { withTimezone: true, mode: 'string' }),
}, (table) => [
	unique("link_health_table_feishu_url_key").on(table.feishuUrl),
]);

export const previewImages = pgTable("preview_images", {
	id: serial().primaryKey().notNull(),
	name: varchar({ length: 100 }).notNull(),
	url: text().notNull(),
	createdAt: timestamp("created_at", { withTimezone: true, mode: 'string' }).default(sql`CURRENT_TIMESTAMP`),
	imageKey: text("image_key"),
}, (table) => [
	index("ix_preview_images_name").using("btree", table.name.asc().nullsLast().op("text_ops")),
]);
