CREATE TABLE `import_history` (
	`id` text PRIMARY KEY NOT NULL,
	`month` text NOT NULL,
	`file_name` text NOT NULL,
	`sheet_name` text NOT NULL,
	`hash` text NOT NULL,
	`imported_at` text NOT NULL,
	`actor` text NOT NULL,
	`count` integer NOT NULL,
	`payload` text NOT NULL,
	`file_key` text,
	`action` text NOT NULL
);
--> statement-breakpoint
CREATE TABLE `months` (
	`month` text PRIMARY KEY NOT NULL,
	`payload` text NOT NULL,
	`hash` text NOT NULL,
	`updated_at` text NOT NULL,
	`file_key` text
);
--> statement-breakpoint
CREATE TABLE `settings` (
	`key` text PRIMARY KEY NOT NULL,
	`value` text NOT NULL
);
