ALTER TABLE "ucp"."outbox" ADD COLUMN "attempts" integer DEFAULT 0 NOT NULL;--> statement-breakpoint
ALTER TABLE "ucp"."outbox" ADD COLUMN "published_at" timestamp with time zone;--> statement-breakpoint
ALTER TABLE "ucp"."outbox" ADD COLUMN "owner_token" varchar(128);--> statement-breakpoint
ALTER TABLE "ucp"."outbox" ADD COLUMN "lease_expires_at" timestamp with time zone;
