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
CLUSTER_NAME="${ENV_NAME}-cluster"
REGION="${AWS_REGION:-us-east-1}"
DB_INSTANCES=("${ENV_NAME}-global-db" "${ENV_NAME}-edi-shard-db")

log() {
    printf "[%s] %s\n" "$(date -u +'%Y-%m-%dT%H:%M:%SZ')" "$*"
}

log_error() {
    printf "[%s] ERROR: %s\n" "$(date -u +'%Y-%m-%dT%H:%M:%SZ')" "$*" >&2
}

check_dependencies() {
    if ! command -v aws >/dev/null 2>&1; then
        log_error "AWS CLI ('aws') is required but not installed."
        exit 1
    fi
}

get_db_status() {
    local db_id="$1"
    aws rds describe-db-instances \
        --db-instance-identifier "$db_id" \
        --region "$REGION" \
        --query "DBInstances[0].DBInstanceStatus" \
        --output text 2>/dev/null || echo "not-found"
}

get_cluster_services() {
    aws ecs list-services \
        --cluster "$CLUSTER_NAME" \
        --region "$REGION" \
        --query "serviceArns[]" \
        --output text 2>/dev/null || true
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

    log "Step 1: Scaling down all ECS services in cluster '${CLUSTER_NAME}' to 0..."
    services=$(get_cluster_services)
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
        log "  All ECS services scaled down."
    else
        log "  No ECS services to scale down."
    fi

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
            log "  DB '${db}' in state '${current_status}'."
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
    services=$(get_cluster_services)
    if [[ -n "$services" ]]; then
        for svc_arn in $services; do
            svc_name="${svc_arn##*/}"
            # Bastion / debug tasks remain scaled to 0 unless manually requested
            if [[ "$svc_name" =~ bastion ]]; then
                log "  Skipping '${svc_name}' (bastion scales to 0 by default)"
                continue
            fi
            log "  Scaling ${svc_name} -> desired_count=1"
            aws ecs update-service \
                --cluster "$CLUSTER_NAME" \
                --service "$svc_arn" \
                --desired-count 1 \
                --region "$REGION" \
                --output text --query "service.serviceName" >/dev/null
        done
        log "  Application and worker ECS services restored to active status."
    else
        log "  No ECS services found to restore."
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
