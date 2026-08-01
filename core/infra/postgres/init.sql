-- ---------------------------------------------------------------------------
-- app schema and RLS helper functions
-- Must be defined before any CREATE POLICY statement that references them.
-- ---------------------------------------------------------------------------
CREATE SCHEMA IF NOT EXISTS app;

-- Returns the tenant_id stored in the current session local variable.
-- Set this before any query that should be tenant-scoped:
--   SELECT set_config('app.current_tenant_id', '<id>', true);
CREATE OR REPLACE FUNCTION app.current_tenant_id()
RETURNS varchar
LANGUAGE plpgsql
STABLE SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $$
BEGIN
  RETURN current_setting('app.current_tenant_id', true);
END;
$$;

-- Returns TRUE when the caller is a privileged backend role with BYPASSRLS.
-- This function should only be executable by authorized roles, not by public.
-- Workers and migrations should connect using a role with BYPASSRLS attribute.
CREATE OR REPLACE FUNCTION app.bypass_rls()
RETURNS boolean
LANGUAGE plpgsql
STABLE SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $$
BEGIN
  -- Only permit bypass for roles with BYPASSRLS attribute or superuser
  RETURN pg_has_role(current_user, 'pg_database_owner', 'MEMBER')
         OR (SELECT rolbypassrls FROM pg_roles WHERE rolname = current_user);
END;
$$;

-- Grant EXECUTE to the public role only for current_tenant_id.
-- bypass_rls should NOT be publicly executable - it checks role membership internally.
GRANT EXECUTE ON FUNCTION app.current_tenant_id() TO public;
REVOKE EXECUTE ON FUNCTION app.bypass_rls() FROM public;
