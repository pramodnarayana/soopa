#!/usr/bin/env bash
# ==============================================================================
# Staging Environment Power Manager
# ==============================================================================
# Enterprise-grade sequencing to power down staging at night / on weekends
# and power up in the morning or on-demand.
#
# Usage:
#   ./infra/scripts/manage_staging_power.sh [status|stop|start] [cluster_name]
# ==============================================================================
set -euo pipefail

ACTION="${1:-status}"
ENV_NAME="${2:-staging}"

log() {
    printf "[%s] %s\n" "$(date -u +'%Y-%m-%dT%H:%M:%SZ')" "$*"
}

log_error() {
    printf "[%s] ERROR: %s\n" "$(date -u +'%Y-%m-%dT%H:%M:%SZ')" "$*" >&2
}

log_warn() {
    printf "[%s] WARN: %s\n" "$(date -u +'%Y-%m-%dT%H:%M:%SZ')" "$*" >&2
}


# Strict guardrail: restrict power management strictly to staging
if [[ "$ENV_NAME" != "staging" ]]; then
    log_error "This power management script is strictly restricted to 'staging'. Refusing to operate on '${ENV_NAME}'."
    exit 1
fi

CLUSTER_NAME="${ENV_NAME}-cluster"
REGION="${AWS_REGION:-us-east-1}"
DB_INSTANCES=("${ENV_NAME}-global-db" "${ENV_NAME}-edi-shard-db")
SSM_PARAM_NAME="/${ENV_NAME}/power/pre_shutdown_desired_counts"

check_dependencies() {
    if ! command -v aws >/dev/null 2>&1; then
        log_error "AWS CLI ('aws') is required but not installed."
        exit 1
    fi
}

get_db_status() {
    local db_id="$1"
    local status
    local err_file
    err_file=$(mktemp)

    if status=$(aws rds describe-db-instances \
        --db-instance-identifier "$db_id" \
        --region "$REGION" \
        --query "DBInstances[0].DBInstanceStatus" \
        --output text 2>"$err_file"); then
        rm -f "$err_file"
        echo "$status"
    else
        local err
        err=$(cat "$err_file" 2>/dev/null || true)
        rm -f "$err_file"
        if echo "$err" | grep -q "DBInstanceNotFound"; then
            echo "not-found"
        else
            log_error "Failed to query RDS instance '${db_id}': ${err}"
            return 1
        fi
    fi
}

get_cluster_services() {
    local services
    local err_file
    err_file=$(mktemp)

    if services=$(aws ecs list-services \
        --cluster "$CLUSTER_NAME" \
        --region "$REGION" \
        --query "serviceArns[]" \
        --output text 2>"$err_file"); then
        rm -f "$err_file"
        echo "$services"
    else
        local err
        err=$(cat "$err_file" 2>/dev/null || true)
        rm -f "$err_file"
        log_error "Failed to list ECS services for cluster '${CLUSTER_NAME}': ${err}"
        return 1
    fi
}

show_status() {
    log "================================================================="
    log "Environment Power Status: ${ENV_NAME} (Region: ${REGION})"
    log "================================================================="

    log "--- RDS Databases ---"
    for db in "${DB_INSTANCES[@]}"; do
        status=$(get_db_status "$db")
        log "  * ${db}: ${status}"
    done

    log "--- ECS Cluster: ${CLUSTER_NAME} ---"
    services=$(get_cluster_services)
    if [[ -z "$services" ]]; then
        log "  No services found or cluster does not exist."
    else
        for svc_arn in $services; do
            svc_name="${svc_arn##*/}"
            info=$(aws ecs describe-services \
                --cluster "$CLUSTER_NAME" \
                --services "$svc_arn" \
                --region "$REGION" \
                --query "services[0].[desiredCount,runningCount]" \
                --output text 2>/dev/null || echo "0 0")
            desired=$(echo "$info" | awk '{print $1}')
            running=$(echo "$info" | awk '{print $2}')
            log "  * ${svc_name}: desired=${desired}, running=${running}"
        done
    fi
    log "================================================================="
}

stop_environment() {
    log ">>> Initiating SHUTDOWN sequence for '${ENV_NAME}'..."

    services=$(get_cluster_services)

    # Step 1a: Persist current ECS desired counts to SSM Parameter Store
    if [[ -n "$services" ]]; then
        log "Step 1a: Checking pre-shutdown desired counts in SSM..."

        has_existing_snapshot=false
        ssm_check_err=$(mktemp)
        if existing_snapshot=$(aws ssm get-parameter \
            --name "$SSM_PARAM_NAME" \
            --query "Parameter.Value" \
            --output text \
            --region "$REGION" 2>"$ssm_check_err"); then
            rm -f "$ssm_check_err"
            has_existing_snapshot=true
            log "  Existing snapshot found in SSM (${existing_snapshot}); preserving it to prevent overwrite during partial-shutdown retry."
        else
            check_err=$(cat "$ssm_check_err" 2>/dev/null || true)
            rm -f "$ssm_check_err"
            if echo "$check_err" | grep -q "ParameterNotFound"; then
                log "  No existing SSM snapshot found. Capturing current desired counts..."
            else
                log_error "Failed to check existing SSM snapshot (${SSM_PARAM_NAME}): ${check_err}"
                exit 1
            fi
        fi

        if [ "$has_existing_snapshot" = false ]; then
            counts_json="{"
            first=true
            all_zeros=true
            for svc_arn in $services; do
                svc_name="${svc_arn##*/}"
                info=$(aws ecs describe-services \
                    --cluster "$CLUSTER_NAME" \
                    --services "$svc_arn" \
                    --region "$REGION" \
                    --query "services[0].desiredCount" \
                    --output text 2>/dev/null || echo "1")

                if ! [[ "$info" =~ ^[0-9]+$ ]]; then
                    info="1"
                fi

                if [[ "$info" -gt 0 ]]; then
                    all_zeros=false
                fi

                if [ "$first" = true ]; then
                    first=false
                else
                    counts_json="${counts_json},"
                fi
                counts_json="${counts_json}\"${svc_name}\":${info}"
            done
            counts_json="${counts_json}}"

            if [ "$all_zeros" = true ]; then
                log "  All ECS services are already at desiredCount=0; skipping SSM persistence to preserve pre-shutdown state."
            else
                put_err_file=$(mktemp)
                if aws ssm put-parameter \
                    --name "$SSM_PARAM_NAME" \
                    --value "$counts_json" \
                    --type "String" \
                    --overwrite \
                    --region "$REGION" >/dev/null 2>"$put_err_file"; then
                    rm -f "$put_err_file"
                    log "  Successfully persisted pre-shutdown desired counts to SSM: ${counts_json}"
                else
                    put_err=$(cat "$put_err_file" 2>/dev/null || true)
                    rm -f "$put_err_file"
                    log_error "Failed to persist pre-shutdown desired counts to SSM (${SSM_PARAM_NAME}): ${put_err}. Aborting scale-down to prevent unrecoverable state loss."
                    exit 1
                fi
            fi
        fi
    fi

    # Step 1b: Scale down all ECS services in cluster to 0
    log "Step 1b: Scaling down all ECS services in cluster '${CLUSTER_NAME}' to 0..."
    if [[ -n "$services" ]]; then
        for svc_arn in $services; do
            svc_name="${svc_arn##*/}"
            log "  Scaling ${svc_name} -> desired_count=0"
            aws ecs update-service \
                --cluster "$CLUSTER_NAME" \
                --service "$svc_arn" \
                --desired-count 0 \
                --region "$REGION" \
                --output text --query "service.serviceName" >/dev/null
        done
        log "  All ECS services scale-down requested."
    else
        log "  No ECS services to scale down."
    fi

    # Step 1c: Wait for running ECS tasks to drain to 0 before stopping databases
    if [[ -n "$services" ]]; then
        log "Step 1c: Waiting for all ECS tasks to drain and reach 0 running tasks..."
        max_wait=300
        waited=0
        poll_interval=5

        while [[ $waited -lt $max_wait ]]; do
            total_running=0
            poll_failed=false
            for svc_arn in $services; do
                svc_name="${svc_arn##*/}"
                running_out=$(aws ecs describe-services \
                    --cluster "$CLUSTER_NAME" \
                    --services "$svc_arn" \
                    --region "$REGION" \
                    --query "services[0].runningCount" \
                    --output text 2>/dev/null)
                exit_code=$?

                if [[ $exit_code -ne 0 ]] || ! [[ "$running_out" =~ ^[0-9]+$ ]]; then
                    log "  Warning: Failed to query running count for ${svc_name} (exit code ${exit_code}, output: '${running_out}'). Treating as not drained."
                    total_running=$((total_running + 1))
                    poll_failed=true
                else
                    total_running=$((total_running + running_out))
                fi
            done

            if [[ $total_running -eq 0 && "$poll_failed" = false ]]; then
                log "  All ECS tasks successfully drained (0 running tasks across cluster)."
                break
            fi

            log "  Waiting for ${total_running} running task(s) to stop (waited ${waited}s / max ${max_wait}s)..."
            sleep "$poll_interval"
            waited=$((waited + poll_interval))
        done

        if [[ $waited -ge $max_wait ]]; then
            log_error "Timeout (${max_wait}s) waiting for ECS tasks to drain to 0 running tasks."
            exit 1
        fi
    fi

    # Step 2: Stopping RDS PostgreSQL instances after services are fully drained
    log "Step 2: Stopping RDS PostgreSQL instances..."
    for db in "${DB_INSTANCES[@]}"; do
        current_status=$(get_db_status "$db")
        log "  DB '${db}' is currently '${current_status}'"
        if [[ "$current_status" == "available" ]]; then
            log "  Requesting stop for DB '${db}'..."
            aws rds stop-db-instance \
                --db-instance-identifier "$db" \
                --region "$REGION" \
                --output text --query "DBInstance.DBInstanceStatus" >/dev/null
            log "  DB '${db}' stop requested successfully."
        elif [[ "$current_status" == "stopped" || "$current_status" == "stopping" ]]; then
            log "  DB '${db}' is already ${current_status}, skipping."
        else
            log "  DB '${db}' in state '${current_status}', cannot stop right now."
        fi
    done

    log ">>> SHUTDOWN sequence completed for '${ENV_NAME}'."
    show_status
}

start_environment() {
    log ">>> Initiating STARTUP sequence for '${ENV_NAME}'..."

    log "Step 1: Starting RDS PostgreSQL instances..."
    dbs_to_wait=()
    for db in "${DB_INSTANCES[@]}"; do
        current_status=$(get_db_status "$db")
        log "  DB '${db}' is currently '${current_status}'"

        # If DB is in 'stopping' state, wait for it to reach 'stopped' before requesting start.
        # Note: AWS CLI does not support a 'db-instance-stopped' waiter subcommand, so we poll get_db_status.
        if [[ "$current_status" == "stopping" ]]; then
            log "  DB '${db}' is currently 'stopping'. Waiting for it to reach 'stopped' (timeout: 15m)..."
            waited=0
            max_wait=900
            poll_interval=15
            while [[ $waited -lt $max_wait ]]; do
                current_status=$(get_db_status "$db")
                if [[ "$current_status" == "stopped" ]]; then
                    break
                fi
                log "  Waiting for DB '${db}' to finish stopping (current: '${current_status}', waited ${waited}s)..."
                sleep "$poll_interval"
                waited=$((waited + poll_interval))
            done
            if [[ "$current_status" != "stopped" ]]; then
                log_error "Timeout waiting for DB '${db}' to transition from 'stopping' to 'stopped'."
                exit 1
            fi
            log "  DB '${db}' has transitioned to state '${current_status}'"
        fi

        if [[ "$current_status" == "stopped" ]]; then
            log "  Starting DB '${db}'..."
            aws rds start-db-instance \
                --db-instance-identifier "$db" \
                --region "$REGION" \
                --output text --query "DBInstance.DBInstanceStatus" >/dev/null
            dbs_to_wait+=("$db")
        elif [[ "$current_status" == "starting" ]]; then
            dbs_to_wait+=("$db")
        elif [[ "$current_status" == "available" ]]; then
            log "  DB '${db}' is already available."
        else
            log_error "DB '${db}' is in unexpected state '${current_status}'. Cannot proceed with safe startup."
            exit 1
        fi
    done

    if [[ ${#dbs_to_wait[@]} -gt 0 ]]; then
        log "Step 2: Waiting for databases to become healthy and available..."
        for db in "${dbs_to_wait[@]}"; do
            log "  Waiting for DB '${db}' to reach 'available' (timeout: 10m)..."
            aws rds wait db-instance-available \
                --db-instance-identifier "$db" \
                --region "$REGION"
            log "  DB '${db}' is now available!"
        done
    fi

    log "Step 3: Scaling up ECS services in cluster '${CLUSTER_NAME}'..."
    # Attempt to load saved desired counts from SSM Parameter Store
    saved_counts=""
    has_saved_snapshot=false
    ssm_get_err=$(mktemp)
    if saved_raw=$(aws ssm get-parameter \
        --name "$SSM_PARAM_NAME" \
        --query "Parameter.Value" \
        --output text \
        --region "$REGION" 2>"$ssm_get_err"); then
        rm -f "$ssm_get_err"
        saved_counts="$saved_raw"
        has_saved_snapshot=true
        log "  Loaded pre-shutdown desired counts from SSM: ${saved_counts}"
    else
        get_err=$(cat "$ssm_get_err" 2>/dev/null || true)
        rm -f "$ssm_get_err"
        if echo "$get_err" | grep -q "ParameterNotFound"; then
            log "  No pre-shutdown desired counts found in SSM. Falling back to default configuration."
        else
            log_error "Failed to query SSM parameter '${SSM_PARAM_NAME}': ${get_err}"
            exit 1
        fi
    fi

    services=$(get_cluster_services)
    if [[ -z "$services" ]]; then
        log "  No ECS services found to restore."
        if [ "$has_saved_snapshot" = true ]; then
            log_error "Snapshot exists in SSM but no cluster services were found. Preserving snapshot."
            exit 1
        fi
    else
        all_restored=true
        restored_services=()
        for svc_arn in $services; do
            svc_name="${svc_arn##*/}"
            # Bastion / debug tasks remain scaled to 0 unless manually requested
            if [[ "$svc_name" =~ bastion ]]; then
                log "  Skipping '${svc_name}' (bastion scales to 0 by default)"
                continue
            fi

            # Determine desired count: from saved counts if available, otherwise default to 1
            target_count=1
            if [[ -n "$saved_counts" ]]; then
                # Extract integer value for this service: "svc_name":N
                matched_count=$(echo "$saved_counts" | grep -o "\"${svc_name}\":[0-9]*" | cut -d':' -f2 || true)
                if [[ -n "$matched_count" ]]; then
                    target_count="$matched_count"
                fi
            fi

            log "  Scaling ${svc_name} -> desired_count=${target_count}"
            svc_err_file=$(mktemp)
            if aws ecs update-service \
                --cluster "$CLUSTER_NAME" \
                --service "$svc_arn" \
                --desired-count "$target_count" \
                --region "$REGION" \
                --output text --query "service.serviceName" >/dev/null 2>"$svc_err_file"; then
                rm -f "$svc_err_file"
                restored_services+=("$svc_name")
            else
                svc_err=$(cat "$svc_err_file" 2>/dev/null || true)
                rm -f "$svc_err_file"
                log_error "Failed to scale service '${svc_name}' to desired_count=${target_count}: ${svc_err}"
                all_restored=false
            fi
        done

        if [ "$all_restored" = false ]; then
            log_error "One or more ECS services failed to scale up. Preserving SSM snapshot for retry."
            exit 1
        fi

        log "  Application and worker ECS services restored to active status."

        # Delete the saved snapshot only after all active services have been restored successfully
        if [ "$has_saved_snapshot" = true ]; then
            saved_service_names=$(echo "$saved_counts" | grep -o '"[^"]*":[0-9]*' | cut -d'"' -f2 || true)
            for saved_svc in $saved_service_names; do
                if [[ "$saved_svc" =~ bastion ]]; then
                    continue
                fi
                svc_found=false
                for r_svc in "${restored_services[@]}"; do
                    if [[ "$r_svc" == "$saved_svc" ]]; then
                        svc_found=true
                        break
                    fi
                done
                if [ "$svc_found" = false ]; then
                    log_warn "Saved service '${saved_svc}' from SSM snapshot was not found in cluster services (service may have been retired)."
                fi
            done

            log "  All active services restored successfully. Deleting snapshot from SSM (${SSM_PARAM_NAME})..."
            del_err_file=$(mktemp)
            if aws ssm delete-parameter \
                --name "$SSM_PARAM_NAME" \
                --region "$REGION" >/dev/null 2>"$del_err_file"; then
                rm -f "$del_err_file"
                log "  Successfully removed pre-shutdown snapshot from SSM."
            else
                del_err=$(cat "$del_err_file" 2>/dev/null || true)
                rm -f "$del_err_file"
                log_error "Failed to delete SSM parameter '${SSM_PARAM_NAME}' after restore: ${del_err}"
                exit 1
            fi
        fi
    fi

    log ">>> STARTUP sequence completed for '${ENV_NAME}'."
    show_status
}

main() {
    check_dependencies

    case "$ACTION" in
        status)
            show_status
            ;;
        stop)
            stop_environment
            ;;
        start)
            start_environment
            ;;
        *)
            log_error "Unknown action: '$ACTION'. Use 'status', 'start', or 'stop'."
            exit 1
            ;;
    esac
}

main "$@"
