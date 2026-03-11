import { relations } from "drizzle-orm/relations";
import { cardKeysTable, accessLogs } from "./schema";

export const accessLogsRelations = relations(accessLogs, ({one}) => ({
	cardKeysTable: one(cardKeysTable, {
		fields: [accessLogs.cardKeyId],
		references: [cardKeysTable.id]
	}),
}));

export const cardKeysTableRelations = relations(cardKeysTable, ({many}) => ({
	accessLogs: many(accessLogs),
}));