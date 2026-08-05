CREATE SCHEMA "ucp";
--> statement-breakpoint
CREATE TABLE "ucp"."api_tokens" (
	"id" varchar(128) PRIMARY KEY NOT NULL,
	"tenant_id" varchar(128) NOT NULL,
	"name" varchar(255) NOT NULL,
	"client_id" varchar(64) NOT NULL,
	"secret_hash" varchar(64) NOT NULL,
	"last_used_at" timestamp with time zone,
	"expires_at" timestamp with time zone,
	"active" boolean DEFAULT true NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL,
	CONSTRAINT "api_tokens_client_id_unique" UNIQUE("client_id")
);
--> statement-breakpoint
ALTER TABLE "ucp"."api_tokens" ENABLE ROW LEVEL SECURITY;--> statement-breakpoint
CREATE TABLE "ucp"."api_keys" (
	"id" varchar(128) PRIMARY KEY NOT NULL,
	"tenant_id" varchar(128) NOT NULL,
	"key_hash" text NOT NULL,
	"name" text NOT NULL,
	"scopes" text[] DEFAULT '{}' NOT NULL,
	"created_at" timestamp DEFAULT now() NOT NULL,
	CONSTRAINT "api_keys_key_hash_unique" UNIQUE("key_hash")
);
--> statement-breakpoint
ALTER TABLE "ucp"."api_keys" ENABLE ROW LEVEL SECURITY;--> statement-breakpoint
CREATE TABLE "ucp"."shard_registry" (
	"tenant_id" varchar(128) NOT NULL,
	"app_id" varchar(128) NOT NULL,
	"shard_id" varchar(128) NOT NULL,
	"status" varchar(50) DEFAULT 'active' NOT NULL,
	"created_at" timestamp DEFAULT now() NOT NULL,
	CONSTRAINT "shard_registry_tenant_id_app_id_pk" PRIMARY KEY("tenant_id","app_id")
);
--> statement-breakpoint
ALTER TABLE "ucp"."shard_registry" ENABLE ROW LEVEL SECURITY;--> statement-breakpoint
CREATE TABLE "ucp"."tenant_users" (
	"tenant_id" varchar(128) NOT NULL,
	"user_id" varchar(128) NOT NULL,
	"role" varchar(50) NOT NULL,
	"metadata" jsonb,
	"created_at" timestamp DEFAULT now() NOT NULL,
	CONSTRAINT "tenant_users_tenant_id_user_id_pk" PRIMARY KEY("tenant_id","user_id")
);
--> statement-breakpoint
ALTER TABLE "ucp"."tenant_users" ENABLE ROW LEVEL SECURITY;--> statement-breakpoint
CREATE TABLE "ucp"."tenants" (
	"id" varchar(128) PRIMARY KEY NOT NULL,
	"name" text NOT NULL,
	"idp_tenant_id" varchar(255),
	"status" varchar(50) DEFAULT 'active' NOT NULL,
	"created_at" timestamp DEFAULT now() NOT NULL,
	"updated_at" timestamp DEFAULT now() NOT NULL,
	CONSTRAINT "tenants_idp_tenant_id_unique" UNIQUE("idp_tenant_id")
);
--> statement-breakpoint
CREATE TABLE "ucp"."users" (
	"id" varchar(128) PRIMARY KEY NOT NULL,
	"idp_user_id" varchar(255),
	"email" varchar(255) NOT NULL,
	"name" text NOT NULL,
	"status" varchar(50) DEFAULT 'active' NOT NULL,
	"created_at" timestamp DEFAULT now() NOT NULL,
	"updated_at" timestamp DEFAULT now() NOT NULL,
	CONSTRAINT "users_idp_user_id_unique" UNIQUE("idp_user_id"),
	CONSTRAINT "users_email_unique" UNIQUE("email")
);
--> statement-breakpoint
CREATE TABLE "ucp"."notification_templates" (
	"id" serial PRIMARY KEY NOT NULL,
	"tenant_id" varchar(255) NOT NULL,
	"event_type" varchar(255) NOT NULL,
	"channel" varchar(50) NOT NULL,
	"subject_template" text NOT NULL,
	"body_template" text NOT NULL,
	"is_active" boolean DEFAULT true NOT NULL
);
--> statement-breakpoint
ALTER TABLE "ucp"."notification_templates" ENABLE ROW LEVEL SECURITY;--> statement-breakpoint
CREATE TABLE "ucp"."outbox" (
	"id" varchar(128) PRIMARY KEY NOT NULL,
	"idempotency_key" varchar(255) NOT NULL,
	"tenant_id" varchar(128),
	"event_type" varchar(100) NOT NULL,
	"payload" jsonb NOT NULL,
	"status" varchar(50) DEFAULT 'PENDING' NOT NULL,
	"error_reason" text,
	"created_at" timestamp DEFAULT now() NOT NULL,
	"updated_at" timestamp DEFAULT now() NOT NULL,
	CONSTRAINT "outbox_idempotency_key_unique" UNIQUE("idempotency_key")
);
--> statement-breakpoint
ALTER TABLE "ucp"."outbox" ENABLE ROW LEVEL SECURITY;--> statement-breakpoint
CREATE TABLE "ucp"."database_shards" (
	"id" varchar(128) PRIMARY KEY NOT NULL,
	"name" varchar(255) NOT NULL,
	"dsn" varchar(1024) NOT NULL,
	"created_at" timestamp DEFAULT now() NOT NULL,
	CONSTRAINT "database_shards_name_unique" UNIQUE("name")
);
--> statement-breakpoint
CREATE TABLE "ucp"."platform_settings" (
	"key" varchar PRIMARY KEY NOT NULL,
	"value" jsonb,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "ucp"."system_audit_log" (
	"id" varchar(128) PRIMARY KEY NOT NULL,
	"trace_id" varchar(128) NOT NULL,
	"tenant_id" varchar(128) NOT NULL,
	"event" varchar(100) NOT NULL,
	"status" varchar(50) NOT NULL,
	"created_at" timestamp DEFAULT now() NOT NULL
);
--> statement-breakpoint
ALTER TABLE "ucp"."system_audit_log" ENABLE ROW LEVEL SECURITY;--> statement-breakpoint
CREATE TABLE "ucp"."scheduled_jobs" (
	"id" varchar(128) PRIMARY KEY NOT NULL,
	"name" varchar(255) NOT NULL,
	"payload" jsonb DEFAULT '{}'::jsonb NOT NULL,
	"status" varchar(50) DEFAULT 'PENDING' NOT NULL,
	"next_run_at" timestamp,
	"interval_seconds" integer,
	"min_interval_seconds" integer,
	"max_interval_seconds" integer,
	"cron_expression" varchar(100),
	"timezone" varchar(50),
	"target_queue" varchar(255),
	"app_namespace" varchar(255),
	"retry_count" integer DEFAULT 0 NOT NULL,
	"max_retries" integer DEFAULT 3 NOT NULL,
	"error_message" text,
	"locked_at" timestamp,
	"locked_by" varchar(255),
	"created_at" timestamp DEFAULT now() NOT NULL,
	"updated_at" timestamp DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "ucp"."app_subscriptions" (
	"tenant_id" varchar(128) NOT NULL,
	"app_id" varchar(128) NOT NULL,
	"tier" varchar(50) DEFAULT 'standard' NOT NULL,
	"status" varchar(50) DEFAULT 'active' NOT NULL,
	"expires_at" timestamp,
	"created_at" timestamp DEFAULT now() NOT NULL,
	"updated_at" timestamp DEFAULT now() NOT NULL,
	CONSTRAINT "app_subscriptions_tenant_id_app_id_pk" PRIMARY KEY("tenant_id","app_id")
);
--> statement-breakpoint
ALTER TABLE "ucp"."app_subscriptions" ENABLE ROW LEVEL SECURITY;--> statement-breakpoint
CREATE TABLE "ucp"."apps" (
	"id" varchar(128) PRIMARY KEY NOT NULL,
	"name" text NOT NULL,
	"slug" varchar(255) NOT NULL,
	"description" text,
	"created_at" timestamp DEFAULT now() NOT NULL,
	CONSTRAINT "apps_slug_unique" UNIQUE("slug")
);
--> statement-breakpoint
ALTER TABLE "ucp"."apps" ENABLE ROW LEVEL SECURITY;--> statement-breakpoint
CREATE TABLE "ucp"."webhooks" (
	"id" varchar(128) PRIMARY KEY NOT NULL,
	"tenant_id" varchar(128) NOT NULL,
	"name" varchar(255) NOT NULL,
	"url" varchar(1024) NOT NULL,
	"auth_header_vault_ref" varchar(255),
	"active" boolean DEFAULT true NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
ALTER TABLE "ucp"."webhooks" ENABLE ROW LEVEL SECURITY;--> statement-breakpoint
ALTER TABLE "ucp"."api_tokens" ADD CONSTRAINT "api_tokens_tenant_id_tenants_id_fk" FOREIGN KEY ("tenant_id") REFERENCES "ucp"."tenants"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "ucp"."api_keys" ADD CONSTRAINT "api_keys_tenant_id_tenants_id_fk" FOREIGN KEY ("tenant_id") REFERENCES "ucp"."tenants"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "ucp"."shard_registry" ADD CONSTRAINT "shard_registry_tenant_id_tenants_id_fk" FOREIGN KEY ("tenant_id") REFERENCES "ucp"."tenants"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "ucp"."tenant_users" ADD CONSTRAINT "tenant_users_tenant_id_tenants_id_fk" FOREIGN KEY ("tenant_id") REFERENCES "ucp"."tenants"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "ucp"."tenant_users" ADD CONSTRAINT "tenant_users_user_id_users_id_fk" FOREIGN KEY ("user_id") REFERENCES "ucp"."users"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "ucp"."outbox" ADD CONSTRAINT "outbox_tenant_id_tenants_id_fk" FOREIGN KEY ("tenant_id") REFERENCES "ucp"."tenants"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "ucp"."app_subscriptions" ADD CONSTRAINT "app_subscriptions_tenant_id_tenants_id_fk" FOREIGN KEY ("tenant_id") REFERENCES "ucp"."tenants"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "ucp"."app_subscriptions" ADD CONSTRAINT "app_subscriptions_app_id_apps_id_fk" FOREIGN KEY ("app_id") REFERENCES "ucp"."apps"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "ucp"."webhooks" ADD CONSTRAINT "webhooks_tenant_id_tenants_id_fk" FOREIGN KEY ("tenant_id") REFERENCES "ucp"."tenants"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
CREATE INDEX "api_tokens_tenant_idx" ON "ucp"."api_tokens" USING btree ("tenant_id");--> statement-breakpoint
CREATE INDEX "api_keys_tenant_idx" ON "ucp"."api_keys" USING btree ("tenant_id");--> statement-breakpoint
CREATE INDEX "tenant_users_user_id_idx" ON "ucp"."tenant_users" USING btree ("user_id");--> statement-breakpoint
CREATE UNIQUE INDEX "uq_users_email_lower" ON "ucp"."users" (lower(email));--> statement-breakpoint
CREATE INDEX "ix_global_outbox_pending" ON "ucp"."outbox" USING btree ("status","created_at") WHERE status = 'PENDING';--> statement-breakpoint
CREATE UNIQUE INDEX "notification_template_idx" ON "ucp"."notification_templates" USING btree ("tenant_id","event_type","channel");--> statement-breakpoint
CREATE INDEX "ix_system_audit_log_tenant_time" ON "ucp"."system_audit_log" USING btree ("tenant_id","created_at");--> statement-breakpoint
CREATE INDEX "ix_ucp_system_audit_log_trace_id" ON "ucp"."system_audit_log" USING btree ("trace_id");--> statement-breakpoint
CREATE INDEX "job_status_next_run_idx" ON "ucp"."scheduled_jobs" USING btree ("status","next_run_at");--> statement-breakpoint
CREATE INDEX "webhooks_tenant_idx" ON "ucp"."webhooks" USING btree ("tenant_id");--> statement-breakpoint
CREATE POLICY "api_tokens_isolation" ON "ucp"."api_tokens" AS PERMISSIVE FOR ALL TO public USING ("ucp"."api_tokens"."tenant_id" = app.current_tenant_id() OR app.bypass_rls());--> statement-breakpoint
CREATE POLICY "api_keys_isolation" ON "ucp"."api_keys" AS PERMISSIVE FOR ALL TO public USING ("ucp"."api_keys"."tenant_id" = app.current_tenant_id() OR app.bypass_rls());--> statement-breakpoint
CREATE POLICY "shard_registry_isolation" ON "ucp"."shard_registry" AS PERMISSIVE FOR ALL TO public USING ("ucp"."shard_registry"."tenant_id" = app.current_tenant_id() OR app.bypass_rls());--> statement-breakpoint
CREATE POLICY "tenant_users_isolation" ON "ucp"."tenant_users" AS PERMISSIVE FOR ALL TO public USING ("ucp"."tenant_users"."tenant_id" = app.current_tenant_id() OR app.bypass_rls());--> statement-breakpoint
CREATE POLICY "notification_templates_isolation" ON "ucp"."notification_templates" AS PERMISSIVE FOR ALL TO public USING ("ucp"."notification_templates"."tenant_id" = app.current_tenant_id() OR app.bypass_rls());--> statement-breakpoint
CREATE POLICY "outbox_isolation" ON "ucp"."outbox" AS PERMISSIVE FOR ALL TO public USING ("ucp"."outbox"."tenant_id" IS NULL OR "ucp"."outbox"."tenant_id" = app.current_tenant_id() OR app.bypass_rls()) WITH CHECK ("ucp"."outbox"."tenant_id" IS NULL OR "ucp"."outbox"."tenant_id" = app.current_tenant_id() OR app.bypass_rls());--> statement-breakpoint
CREATE POLICY "system_audit_log_isolation" ON "ucp"."system_audit_log" AS PERMISSIVE FOR ALL TO public USING ("ucp"."system_audit_log"."tenant_id" = app.current_tenant_id() OR app.bypass_rls());--> statement-breakpoint
CREATE POLICY "app_subscriptions_isolation" ON "ucp"."app_subscriptions" AS PERMISSIVE FOR ALL TO public USING ("ucp"."app_subscriptions"."tenant_id" = app.current_tenant_id() OR app.bypass_rls()) WITH CHECK ("ucp"."app_subscriptions"."tenant_id" = app.current_tenant_id() OR app.bypass_rls());--> statement-breakpoint
CREATE POLICY "apps_isolation" ON "ucp"."apps" AS PERMISSIVE FOR ALL TO public USING (app.bypass_rls());--> statement-breakpoint
CREATE POLICY "apps_read" ON "ucp"."apps" AS PERMISSIVE FOR SELECT TO public USING (true);--> statement-breakpoint
CREATE POLICY "webhooks_isolation" ON "ucp"."webhooks" AS PERMISSIVE FOR ALL TO public USING ("ucp"."webhooks"."tenant_id" = app.current_tenant_id() OR app.bypass_rls());
