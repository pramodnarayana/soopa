import {
  type ApiProblem,
  Badge,
  Button,
  Card,
  CardContent,
  CardHeader,
  CopyableIdPill,
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  Input,
  Label,
  MonacoCodeViewer,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  StatusBadge,
  StatusTone,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from '@soopa/ui';
import { ArrowLeft, CheckCircle2, Code2, GitFork, Sparkles, Workflow, Zap } from 'lucide-react';
import React, { useMemo, useState } from 'react';
import { toast } from 'sonner';
import {
  useAddConnectionEntityMutation,
  useConnectionEntitiesQuery,
} from '../../application/use-connection-entity-queries';
import {
  useConnectionsQuery,
  useDiscoveredStreamsQuery,
} from '../../application/use-connection-queries';
import { useSaveMappingSpecMutation } from '../../application/use-mapping-spec-queries';
import {
  useRegisterStitchMutation,
  useStitchDefinitionsQuery,
} from '../../application/use-stitch-queries';
import { useConnectionTransformationsQuery } from '../../application/use-transformation-queries';
import {
  applyFieldMappings,
  autoMapFields,
  type CanonicalModelDef,
  type FieldMappingRule,
  inferSchemaFromSampleJson,
  MappingRuleType,
  type MappingRuleTypeValue,
  type TargetSchemaField,
} from '../../domain/field-mapping';
import type { MappingSpecRule } from '../../domain/mapping-spec';
import { useIpWorkspace } from '../../provider/IpRepositoriesContext';
import { ApiProblemBanner } from '../shared/ApiProblemBanner';
import { IpPageHeader } from '../shared/IpPageHeader';
import { stringifyJsonPretty } from '../shared/status-mapping';
import { DestinationSchemaMonacoEditor } from './DestinationSchemaMonacoEditor';

export interface IpStitchFieldMapperPageProps {
  readonly initialSourceConnectionId?: string;
  readonly initialStreamName?: string;
  readonly initialTargetConnectionId?: string;
  readonly initialTargetTopic?: string;
}

export function IpStitchFieldMapperPage({
  initialSourceConnectionId,
  initialStreamName,
  initialTargetConnectionId,
  initialTargetTopic,
}: IpStitchFieldMapperPageProps) {
  const { navigation } = useIpWorkspace();
  const [problem, setProblem] = useState<ApiProblem | null>(null);

  // Queries
  const connectionsView = useConnectionsQuery();
  const stitchDefinitionsView = useStitchDefinitionsQuery();
  const registerStitchMutation = useRegisterStitchMutation();
  const saveMappingSpecMutation = useSaveMappingSpecMutation();

  // Source Connection & Entity (No forced auto-selection)
  const [sourceConnectionId, setSourceConnectionId] = useState<string>(
    initialSourceConnectionId ?? '',
  );
  const [streamName, setStreamName] = useState<string>(initialStreamName ?? '');

  // Target Connection & Topic/Contract (No forced auto-selection)
  const [targetConnectionId, setTargetConnectionId] = useState<string>(
    initialTargetConnectionId ?? '',
  );
  const addConnectionEntityMutation = useAddConnectionEntityMutation(targetConnectionId);
  const [targetTopic, setTargetTopic] = useState<string>(initialTargetTopic ?? '');
  const [customContractJson, setCustomContractJson] = useState<string>('');
  const [customTargetFields, setCustomTargetFields] = useState<readonly TargetSchemaField[] | null>(
    null,
  );
  const [schemaModalOpen, setSchemaModalOpen] = useState<boolean>(false);
  const [pendingCustomTopic, setPendingCustomTopic] = useState<string>('');

  // Stitch Pipeline Identification
  const [stitchName, setStitchName] = useState<string>('');
  const [isNameManuallyEdited, setIsNameManuallyEdited] = useState<boolean>(false);

  // Field Mapping Rules
  const [mappingRules, setMappingRules] = useState<readonly FieldMappingRule[]>([]);

  // Deployment confirmation
  const [deployedStitchId, setDeployedStitchId] = useState<string | null>(null);
  const [deployedMappingSpecId, setDeployedMappingSpecId] = useState<string | null>(null);

  // Auto-generate a sensible Stitch Name if user hasn't explicitly customized it
  React.useEffect(() => {
    if (!isNameManuallyEdited && streamName && targetTopic) {
      const cleanStream = streamName
        .replace(/[._-]+/g, ' ')
        .replace(/\b\w/g, (c) => c.toUpperCase());
      const cleanTopic = targetTopic === '__custom_schema__' ? 'Custom Target' : targetTopic;
      setStitchName(`${cleanStream} ➔ ${cleanTopic} Wire Stitch`);
    }
  }, [streamName, targetTopic, isNameManuallyEdited]);

  const handleStitchNameChange = (val: string) => {
    setStitchName(val);
    setIsNameManuallyEdited(true);
  };

  // Query entities & discovered streams of selected source connection
  const sourceEntitiesView = useConnectionEntitiesQuery(sourceConnectionId);
  const sourceDiscoveredView = useDiscoveredStreamsQuery(sourceConnectionId);
  const sourceTransformationsView = useConnectionTransformationsQuery(sourceConnectionId);

  // Query entities & discovered streams of selected target connection
  const targetEntitiesView = useConnectionEntitiesQuery(targetConnectionId);
  const targetDiscoveredView = useDiscoveredStreamsQuery(targetConnectionId);

  // Available entities / streams for the selected source connection
  const availableEntities = useMemo<
    readonly { streamName: string; label: string; canonicalName: string }[]
  >(() => {
    if (!sourceConnectionId) return [];

    const list = new Map<string, { streamName: string; label: string; canonicalName: string }>();

    for (const e of sourceEntitiesView.data ?? []) {
      const binding = sourceTransformationsView.data?.find((t) => t.stream === e.streamName);
      const canonicalName = binding ? binding.transformationId : e.streamName;
      list.set(e.streamName, {
        streamName: e.streamName,
        label: binding ? `${e.streamName} (${canonicalName})` : e.streamName,
        canonicalName,
      });
    }

    for (const s of sourceDiscoveredView.data?.streams ?? []) {
      if (!list.has(s.name)) {
        const binding = sourceTransformationsView.data?.find((t) => t.stream === s.name);
        const canonicalName = binding ? binding.transformationId : s.name;
        list.set(s.name, {
          streamName: s.name,
          label: binding ? `${s.name} (${canonicalName})` : s.name,
          canonicalName,
        });
      }
    }

    if (initialStreamName && !list.has(initialStreamName)) {
      list.set(initialStreamName, {
        streamName: initialStreamName,
        label: initialStreamName,
        canonicalName: initialStreamName,
      });
    }

    return Array.from(list.values());
  }, [
    sourceConnectionId,
    sourceEntitiesView.data,
    sourceDiscoveredView.data,
    sourceTransformationsView.data,
    initialStreamName,
  ]);

  // Available destination entities / topics / directories
  const availableDestinationEntities = useMemo<readonly { value: string; label: string }[]>(() => {
    if (!targetConnectionId) return [];

    const map = new Map<string, string>();

    // 1. Only actual discovered streams/entities for this target connection
    for (const e of targetEntitiesView.data ?? []) {
      map.set(e.streamName, e.streamName);
    }
    for (const s of targetDiscoveredView.data?.streams ?? []) {
      if (!map.has(s.name)) {
        map.set(s.name, s.name);
      }
    }

    // 2. If user has a selected or active custom topic, show it
    if (targetTopic && !map.has(targetTopic) && targetTopic !== '__custom_schema__') {
      map.set(targetTopic, targetTopic);
    }

    return Array.from(map.entries()).map(([value, label]) => ({ value, label }));
  }, [targetConnectionId, targetEntitiesView.data, targetDiscoveredView.data, targetTopic]);

  const selectedSourceConnection = useMemo(
    () => connectionsView.data?.find((c) => c.id === sourceConnectionId),
    [connectionsView.data, sourceConnectionId],
  );

  const selectedTargetConnection = useMemo(
    () => connectionsView.data?.find((c) => c.id === targetConnectionId),
    [connectionsView.data, targetConnectionId],
  );

  const selectedEntity = useMemo(
    () => availableEntities.find((e) => e.streamName === streamName),
    [availableEntities, streamName],
  );

  // Resolve Target Schema Fields dynamically from destination connection or custom input
  const targetFields = useMemo<readonly TargetSchemaField[]>(() => {
    if (customTargetFields !== null) {
      return customTargetFields;
    }
    if (!targetTopic || targetTopic === '__custom_schema__') {
      return [];
    }
    const destEntity = targetEntitiesView.data?.find((e) => e.streamName === targetTopic);
    const destDiscovered = targetDiscoveredView.data?.streams.find((s) => s.name === targetTopic);
    const rawFields = destEntity?.fields ?? destDiscovered?.fields ?? [];
    return rawFields.map((f) => {
      const lowerType = f.dataType.toLowerCase();
      const type = (
        ['string', 'number', 'boolean', 'object', 'array'].includes(lowerType)
          ? lowerType
          : 'string'
      ) as 'string' | 'number' | 'boolean' | 'object' | 'array';
      return {
        name: f.name,
        type,
        required: !f.nullable,
        description: f.description ?? undefined,
      };
    });
  }, [customTargetFields, targetTopic, targetEntitiesView.data, targetDiscoveredView.data]);

  // Resolve Canonical Model dynamically from the selected entity's schema (null when no entity or fields)
  const activeCanonicalModel = useMemo<CanonicalModelDef | null>(() => {
    if (!streamName) return null;

    const entity = sourceEntitiesView.data?.find((e) => e.streamName === streamName);
    const discovered = sourceDiscoveredView.data?.streams.find((s) => s.name === streamName);
    const rawFields = entity?.fields ?? discovered?.fields ?? [];

    if (rawFields.length === 0) {
      return null;
    }

    const binding = sourceTransformationsView.data?.find((t) => t.stream === streamName);
    const transformationId = binding?.transformationId ?? streamName;
    const version = binding?.transformationVersion ?? 1;

    const fields = rawFields.map((f) => {
      const lowerType = f.dataType.toLowerCase();
      const type = (
        ['string', 'number', 'boolean', 'object', 'array'].includes(lowerType)
          ? lowerType
          : 'string'
      ) as 'string' | 'number' | 'boolean' | 'object' | 'array';

      const sampleValue =
        type === 'number'
          ? 0
          : type === 'boolean'
            ? false
            : type === 'object'
              ? {}
              : type === 'array'
                ? []
                : `${f.name}_sample`;

      return {
        name: f.name,
        type,
        required: !f.nullable,
        description: f.description ?? f.name,
        sampleValue,
      };
    });

    return {
      transformationId,
      version,
      displayName: `${streamName} Canonical Model`,
      canonicalEventType: `canonical.${streamName}`,
      standard: 'Canonical Normalization',
      targetWorkflowId: `stitch.${streamName}`,
      idempotencyKeyField: 'id',
      fields,
      defaultSampleRecord: Object.fromEntries(fields.map((f) => [f.name, f.sampleValue])),
    };
  }, [
    sourceEntitiesView.data,
    sourceDiscoveredView.data,
    sourceTransformationsView.data,
    streamName,
  ]);

  // Apply new target fields to mapping pipeline
  const handleApplyTargetFields = (fields: readonly TargetSchemaField[]) => {
    setCustomTargetFields(fields);
    setMappingRules([]);
    setSchemaModalOpen(false);
    toast.success(`Applied ${fields.length} target fields to mapping.`);
  };

  const handleClearCustomContract = () => {
    setCustomContractJson('');
    setCustomTargetFields([]);
    setMappingRules([]);
    toast.success('Cleared custom schema.');
  };

  const handleAutoMapClick = () => {
    if (!activeCanonicalModel) return;
    const srcFieldNames = activeCanonicalModel.fields.map((f) => f.name);
    const autoRules = autoMapFields(srcFieldNames, targetFields);
    setMappingRules(autoRules);
    const mapped = autoRules.filter((r) => r.ruleType !== MappingRuleType.IGNORE).length;
    toast.success(`Auto-mapped ${mapped} of ${targetFields.length} target fields.`);
  };

  const updateMappingRule = (targetField: string, patch: Partial<FieldMappingRule>) => {
    setMappingRules((prev) => {
      const exists = prev.some((r) => r.targetField === targetField);
      if (exists) {
        return prev.map((r) => (r.targetField === targetField ? { ...r, ...patch } : r));
      }
      return [
        ...prev,
        {
          targetField,
          ruleType: MappingRuleType.DIRECT,
          ...patch,
        },
      ];
    });
  };

  // Live Diff Output calculation
  const liveProjectedOutput = useMemo<Record<string, unknown>>(() => {
    if (!activeCanonicalModel) return {};
    return applyFieldMappings(activeCanonicalModel.defaultSampleRecord, mappingRules);
  }, [activeCanonicalModel, mappingRules]);

  // Mapping completeness count
  const mappedCount = useMemo(() => {
    return mappingRules.filter((r) => r.ruleType !== MappingRuleType.IGNORE).length;
  }, [mappingRules]);

  const requiredUnmappedCount = useMemo(() => {
    return targetFields.filter((t) => {
      if (!t.required) return false;
      const rule = mappingRules.find((r) => r.targetField === t.name);
      return !rule || rule.ruleType === MappingRuleType.IGNORE;
    }).length;
  }, [targetFields, mappingRules]);

  const isSourceSelected = Boolean(sourceConnectionId && streamName && activeCanonicalModel);
  const isDestinationSelected = Boolean(targetConnectionId && targetTopic.trim());
  const isPipelineConfigured = isSourceSelected && isDestinationSelected;
  const isReadyToDeploy = isPipelineConfigured && requiredUnmappedCount === 0;

  // Stitch Deployment (Trinity: Translation MappingSpec + Orchestration Stitch)
  const handleDeployStitch = async () => {
    if (!activeCanonicalModel || !targetConnectionId || !targetTopic.trim()) {
      return;
    }

    setProblem(null);
    const workflowId =
      activeCanonicalModel.targetWorkflowId ||
      stitchDefinitionsView.data?.[0]?.workflowId ||
      'stitch.pipeline.sync';
    const def = stitchDefinitionsView.data?.find((d) => d.workflowId === workflowId);
    const workflowVersion = def?.version ?? 1;

    const effectiveName = stitchName.trim() || `${streamName} ➔ ${targetTopic} Wire Stitch`;

    // 1. Persist declarative Translation Layer (ip.mapping_specs)
    const specRules: MappingSpecRule[] = mappingRules.map((r) => ({
      targetField: r.targetField,
      ruleType: r.ruleType === MappingRuleType.FUNCTION ? 'EXPRESSION' : r.ruleType,
      sourceField: r.sourceField ?? null,
      constantValue: r.constantValue ?? null,
      expression: r.functionExpression ?? null,
    }));

    const specRes = await saveMappingSpecMutation.mutateAsync({
      name: `${effectiveName} Field Mapping`,
      description: `Declarative translation rules from ${activeCanonicalModel.canonicalEventType} to ${targetTopic}`,
      sourceType: activeCanonicalModel.canonicalEventType,
      targetConnectionId,
      targetEntityName: targetTopic,
      rules: specRules,
      isActive: true,
    });

    if (!specRes.ok) {
      setProblem(specRes.error);
      toast.error(specRes.error.message || 'Failed to persist field mapping specification.');
      return;
    }

    const mappingSpecId = specRes.value.id;
    setDeployedMappingSpecId(mappingSpecId);

    // 2. Deploy durable Orchestration Layer (ip.stitches) referencing mapping_spec_id
    const res = await registerStitchMutation.mutateAsync({
      name: effectiveName,
      mappingSpecId,
      workflowId,
      workflowVersion,
      canonicalEventType: activeCanonicalModel.canonicalEventType,
      isTrigger: true,
      conditionEventKey: null,
      idempotencyKeyField: activeCanonicalModel.idempotencyKeyField || 'event_id',
      concurrencyKeyField: activeCanonicalModel.concurrencyKeyField ?? null,
      isActive: true,
    });

    if (!res.ok) {
      setProblem(res.error);
      toast.error(res.error.message || 'Failed to deploy Stitch pipeline.');
      return;
    }

    setDeployedStitchId(res.value.id);
    toast.success(
      `Stitch pipeline deployed & activated successfully! (Stitch: ${res.value.id}, Spec: ${mappingSpecId})`,
    );
  };

  return (
    <div className="space-y-5">
      <IpPageHeader
        title="Stitch & Field Mapper"
        actions={
          <div className="flex items-center gap-2">
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={() => navigation.toStitches()}
              className="gap-1.5"
            >
              <ArrowLeft className="h-4 w-4" />
              <span>Back to Stitches</span>
            </Button>
            <Button
              type="button"
              variant="outline"
              size="sm"
              disabled={!isPipelineConfigured}
              onClick={handleAutoMapClick}
              className="gap-1.5 text-primary"
            >
              <Sparkles className="h-4 w-4" />
              <span>Auto-Map</span>
            </Button>
            <Button
              type="button"
              size="sm"
              disabled={!isReadyToDeploy || registerStitchMutation.isPending}
              onClick={() => void handleDeployStitch()}
              className="gap-1.5 bg-primary text-primary-foreground font-semibold"
            >
              <Zap className="h-4 w-4" />
              <span>
                {registerStitchMutation.isPending ? 'Deploying...' : 'Deploy & Activate Stitch'}
              </span>
            </Button>
          </div>
        }
      />

      <ApiProblemBanner problem={problem} />

      {/* Deployment Success Banner */}
      {deployedStitchId && (
        <Card className="border-emerald-500/40 bg-emerald-500/10">
          <CardContent className="py-4 space-y-3">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-3">
                <CheckCircle2 className="h-5 w-5 text-emerald-500 flex-shrink-0" />
                <div>
                  <h4 className="font-semibold text-sm text-foreground">
                    {stitchName.trim() || 'Stitch Pipeline Deployed & Active'}
                  </h4>
                  <span className="text-xs text-muted-foreground font-mono">
                    {streamName} ──▶ {targetTopic}
                  </span>
                </div>
              </div>
              <div className="flex items-center gap-2">
                <CopyableIdPill value={deployedStitchId} prefixLabel="Stitch ID" />
                {deployedMappingSpecId && (
                  <CopyableIdPill value={deployedMappingSpecId} prefixLabel="Mapping Spec" />
                )}
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={() => navigation.toStitches()}
                  className="gap-1.5 text-xs"
                >
                  <Workflow className="h-3.5 w-3.5" />
                  <span>View in Stitches Canvas</span>
                </Button>
              </div>
            </div>
          </CardContent>
        </Card>
      )}

      {/* TOP SECTION: PIPELINE NAME, SOURCE & DESTINATION */}
      <Card className="border-border">
        <CardContent className="pt-4 pb-4 space-y-4">
          {/* Pipeline Identification */}
          <div className="space-y-1.5 border-b border-border/60 pb-3.5">
            <div className="flex items-center justify-between">
              <Label htmlFor="stitch-pipeline-name" className="text-xs font-semibold">
                Stitch Pipeline Name
              </Label>
              <span className="text-[11px] text-muted-foreground">
                Human-readable identifier for monitoring & orchestration
              </span>
            </div>
            <Input
              id="stitch-pipeline-name"
              placeholder="e.g. Inbound Device Telemetry to Target Queue Wire Sync"
              value={stitchName}
              onChange={(e) => handleStitchNameChange(e.target.value)}
              className="h-9 text-xs font-medium"
            />
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-6 items-start">
            {/* Left: Source Connection & Entities below */}
            <div className="space-y-3">
              <div className="space-y-1.5">
                <Label className="text-xs font-semibold">Source Connection</Label>
                <Select
                  value={sourceConnectionId}
                  onValueChange={(val) => {
                    setSourceConnectionId(val);
                    setStreamName('');
                    setMappingRules([]);
                  }}
                >
                  <SelectTrigger className="h-9 text-xs">
                    <SelectValue placeholder="Select connection...">
                      {selectedSourceConnection
                        ? `${selectedSourceConnection.name} (${selectedSourceConnection.appId})`
                        : undefined}
                    </SelectValue>
                  </SelectTrigger>
                  <SelectContent>
                    {(connectionsView.data ?? []).map((conn) => (
                      <SelectItem key={conn.id} value={conn.id}>
                        {conn.name} ({conn.appId})
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              <div className="space-y-1.5">
                <Label className="text-xs font-semibold">Entity</Label>
                <Select
                  value={streamName}
                  onValueChange={(val) => {
                    setStreamName(val);
                    setMappingRules([]);
                  }}
                  disabled={!sourceConnectionId || availableEntities.length === 0}
                >
                  <SelectTrigger className="h-9 text-xs">
                    <SelectValue
                      placeholder={
                        !sourceConnectionId
                          ? 'Select source connection first'
                          : availableEntities.length === 0
                            ? 'No entities available'
                            : 'Select entity...'
                      }
                    >
                      {selectedEntity?.label}
                    </SelectValue>
                  </SelectTrigger>
                  <SelectContent>
                    {availableEntities.map((ent) => (
                      <SelectItem key={ent.streamName} value={ent.streamName}>
                        {ent.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </div>

            {/* Right: Destination Connection & Destination Entity / Topic below */}
            <div className="space-y-3">
              <div className="space-y-1.5">
                <Label className="text-xs font-semibold">Destination Connection</Label>
                <Select
                  value={targetConnectionId}
                  onValueChange={(val) => {
                    setTargetConnectionId(val);
                    setTargetTopic('');
                    setCustomTargetFields(null);
                    setMappingRules([]);
                  }}
                >
                  <SelectTrigger className="h-9 text-xs">
                    <SelectValue placeholder="Select destination...">
                      {selectedTargetConnection
                        ? `${selectedTargetConnection.name} (${selectedTargetConnection.appId})`
                        : undefined}
                    </SelectValue>
                  </SelectTrigger>
                  <SelectContent>
                    {(connectionsView.data ?? []).map((conn) => (
                      <SelectItem key={conn.id} value={conn.id}>
                        {conn.name} ({conn.appId})
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              <div className="space-y-1.5">
                <Label className="text-xs font-semibold">
                  Destination Entity / Topic / Directory
                </Label>
                <Select
                  value={targetTopic}
                  onValueChange={(val) => {
                    if (val === '__custom_schema__') {
                      setPendingCustomTopic(targetTopic || '');
                      setSchemaModalOpen(true);
                      return;
                    }
                    setTargetTopic(val);
                    setCustomTargetFields(null);
                    setMappingRules([]);
                  }}
                  disabled={!targetConnectionId}
                >
                  <SelectTrigger className="h-9 text-xs">
                    <SelectValue
                      placeholder={
                        !targetConnectionId
                          ? 'Select destination connection first'
                          : 'Select destination entity or topic...'
                      }
                    >
                      {targetTopic || undefined}
                    </SelectValue>
                  </SelectTrigger>
                  <SelectContent>
                    {availableDestinationEntities.map((dest) => (
                      <SelectItem key={dest.value} value={dest.value}>
                        {dest.label}
                      </SelectItem>
                    ))}
                    <SelectItem
                      value="__custom_schema__"
                      className="font-medium text-primary border-t border-border mt-1 pt-1.5"
                    >
                      Custom Schema
                    </SelectItem>
                  </SelectContent>
                </Select>
              </div>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* CENTER & BOTTOM: PROGRESSIVE REVEAL ONCE SOURCE & DESTINATION ARE CONFIGURED */}
      {!isPipelineConfigured || !activeCanonicalModel ? (
        <Card className="border-dashed border-2 border-border py-12">
          <CardContent className="flex flex-col items-center justify-center text-center space-y-2">
            <GitFork className="h-8 w-8 text-muted-foreground" />
            <p className="text-sm font-semibold text-foreground">
              {!isSourceSelected && !isDestinationSelected
                ? 'Configure Source and Destination'
                : !isSourceSelected
                  ? 'Source Configuration Incomplete'
                  : 'Destination Configuration Incomplete'}
            </p>
            <p className="text-xs text-muted-foreground max-w-md">
              {!isSourceSelected && !isDestinationSelected
                ? 'Select a Source Connection & Entity on the left, and a Destination Connection & Topic/Entity on the right to configure field mapping.'
                : !isSourceSelected
                  ? 'Select a Source Connection and Entity on the left to resolve the normalized CIM schema.'
                  : 'Select a Destination Connection and enter the Destination Topic, Entity, or Directory on the right to proceed.'}
            </p>
          </CardContent>
        </Card>
      ) : (
        <>
          {/* CENTER SECTION: 3 TABS (Source | Mapping | Destination) */}
          <Tabs defaultValue="mapping" className="space-y-3">
            <div className="flex items-center justify-center">
              <TabsList className="grid w-full max-w-md grid-cols-3">
                <TabsTrigger value="source">Source</TabsTrigger>
                <TabsTrigger value="mapping">Mapping</TabsTrigger>
                <TabsTrigger value="destination">Destination</TabsTrigger>
              </TabsList>
            </div>

            {/* TAB 1: SOURCE */}
            <TabsContent value="source" className="space-y-3 pt-1">
              <Card className="border-border">
                <CardHeader className="py-3 px-4 flex flex-row items-center justify-between">
                  <div className="flex items-center gap-2">
                    <StatusBadge label={activeCanonicalModel.standard} tone={StatusTone.HEALTHY} />
                    <span className="text-sm font-semibold">
                      {activeCanonicalModel.displayName}
                    </span>
                  </div>
                  <span className="font-mono text-xs text-muted-foreground">
                    {activeCanonicalModel.canonicalEventType}
                  </span>
                </CardHeader>
                <CardContent className="px-4 pb-4">
                  <div className="rounded-lg border border-border bg-card overflow-hidden">
                    <Table className="text-xs">
                      <TableHeader className="bg-muted/50">
                        <TableRow>
                          <TableHead className="py-2 px-3 font-semibold">Field Name</TableHead>
                          <TableHead className="py-2 px-3 font-semibold">Data Type</TableHead>
                          <TableHead className="py-2 px-3 font-semibold">Requirement</TableHead>
                          <TableHead className="py-2 px-3 font-semibold">Sample Value</TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {activeCanonicalModel.fields.map((f) => (
                          <TableRow key={f.name}>
                            <TableCell className="font-mono font-medium py-2 px-3">
                              {f.name}
                            </TableCell>
                            <TableCell className="font-mono text-muted-foreground py-2 px-3">
                              {f.type}
                            </TableCell>
                            <TableCell className="py-2 px-3">
                              {f.required ? (
                                <Badge
                                  variant="secondary"
                                  className="text-[10px] font-medium h-5 px-1.5"
                                >
                                  Required
                                </Badge>
                              ) : (
                                <span className="text-muted-foreground text-xs">Optional</span>
                              )}
                            </TableCell>
                            <TableCell className="font-mono text-muted-foreground py-2 px-3">
                              {String(f.sampleValue)}
                            </TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  </div>
                </CardContent>
              </Card>
            </TabsContent>

            {/* TAB 2: MAPPING (DEFAULT) */}
            <TabsContent value="mapping" className="space-y-3 pt-1">
              <Card className="border-border">
                <CardHeader className="py-3 px-4 flex flex-row items-center justify-between">
                  <div className="flex items-center gap-2">
                    <StatusBadge
                      label={`${mappedCount} / ${targetFields.length} Mapped`}
                      tone={requiredUnmappedCount === 0 ? StatusTone.HEALTHY : StatusTone.WARNING}
                    />
                  </div>
                </CardHeader>
                <CardContent className="px-4 pb-4">
                  <div className="rounded-lg border border-border bg-card overflow-hidden">
                    <Table className="text-xs">
                      <TableHeader className="bg-muted/50">
                        <TableRow>
                          <TableHead className="py-2.5 px-3 font-semibold w-2/5">
                            Source (CIM Field / Expression / Value)
                          </TableHead>
                          <TableHead className="py-2.5 px-3 font-semibold w-1/5">
                            Mapping Rule
                          </TableHead>
                          <TableHead className="py-2.5 px-3 font-semibold w-1/4">
                            Target Wire Field
                          </TableHead>
                          <TableHead className="py-2.5 px-3 font-semibold text-right">
                            Status
                          </TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {targetFields.map((target) => {
                          const rule = mappingRules.find((r) => r.targetField === target.name) ?? {
                            targetField: target.name,
                            ruleType: MappingRuleType.IGNORE,
                          };
                          const isMapped = rule.ruleType !== MappingRuleType.IGNORE;

                          return (
                            <TableRow key={target.name} className="hover:bg-muted/30">
                              {/* Column 1: Source CIM / Expression / Value */}
                              <TableCell className="py-2 px-3 align-middle">
                                {rule.ruleType === MappingRuleType.FUNCTION ? (
                                  <Input
                                    value={rule.functionExpression ?? ''}
                                    onChange={(e) =>
                                      updateMappingRule(target.name, {
                                        ruleType: MappingRuleType.FUNCTION,
                                        functionExpression: e.target.value,
                                      })
                                    }
                                    placeholder="e.g. UPPER(field) or ROUND(field, 2)"
                                    className="h-7 text-xs font-mono"
                                  />
                                ) : rule.ruleType === MappingRuleType.CONSTANT ? (
                                  <Input
                                    value={String(rule.constantValue ?? '')}
                                    onChange={(e) =>
                                      updateMappingRule(target.name, {
                                        ruleType: MappingRuleType.CONSTANT,
                                        constantValue: e.target.value,
                                      })
                                    }
                                    placeholder="Static constant value"
                                    className="h-7 text-xs font-mono"
                                  />
                                ) : (
                                  <Select
                                    value={rule.sourceField ?? '__unmapped__'}
                                    onValueChange={(val) => {
                                      if (val === '__unmapped__') {
                                        updateMappingRule(target.name, {
                                          ruleType: MappingRuleType.IGNORE,
                                          sourceField: undefined,
                                        });
                                      } else {
                                        updateMappingRule(target.name, {
                                          ruleType: MappingRuleType.DIRECT,
                                          sourceField: val,
                                        });
                                      }
                                    }}
                                  >
                                    <SelectTrigger className="h-7 text-xs font-mono">
                                      <SelectValue placeholder="Select source CIM field">
                                        {rule.sourceField ? (
                                          rule.sourceField
                                        ) : (
                                          <span className="text-muted-foreground font-sans italic">
                                            -- Unmapped --
                                          </span>
                                        )}
                                      </SelectValue>
                                    </SelectTrigger>
                                    <SelectContent>
                                      <SelectItem value="__unmapped__">
                                        <span className="text-muted-foreground font-sans italic">
                                          -- Unmapped --
                                        </span>
                                      </SelectItem>
                                      {activeCanonicalModel.fields.map((f) => (
                                        <SelectItem key={f.name} value={f.name}>
                                          {f.name} ({f.type})
                                        </SelectItem>
                                      ))}
                                    </SelectContent>
                                  </Select>
                                )}
                              </TableCell>

                              {/* Column 2: Mapping Rule */}
                              <TableCell className="py-2 px-3 align-middle">
                                <Select
                                  value={rule.ruleType}
                                  onValueChange={(val) => {
                                    const newType = val as MappingRuleTypeValue;
                                    if (newType === MappingRuleType.IGNORE) {
                                      updateMappingRule(target.name, {
                                        ruleType: newType,
                                        sourceField: undefined,
                                      });
                                    } else {
                                      updateMappingRule(target.name, {
                                        ruleType: newType,
                                      });
                                    }
                                  }}
                                >
                                  <SelectTrigger className="h-7 text-xs">
                                    <SelectValue>
                                      {rule.ruleType === MappingRuleType.DIRECT
                                        ? 'Direct Map'
                                        : rule.ruleType === MappingRuleType.FUNCTION
                                          ? 'Function / Transform'
                                          : rule.ruleType === MappingRuleType.CONSTANT
                                            ? 'Constant'
                                            : 'Ignore / Exclude'}
                                    </SelectValue>
                                  </SelectTrigger>
                                  <SelectContent>
                                    <SelectItem value={MappingRuleType.DIRECT}>
                                      Direct Map
                                    </SelectItem>
                                    <SelectItem value={MappingRuleType.FUNCTION}>
                                      Function / Transform
                                    </SelectItem>
                                    <SelectItem value={MappingRuleType.CONSTANT}>
                                      Constant
                                    </SelectItem>
                                    <SelectItem value={MappingRuleType.IGNORE}>
                                      Ignore / Exclude
                                    </SelectItem>
                                  </SelectContent>
                                </Select>
                              </TableCell>

                              {/* Column 3: Target Field */}
                              <TableCell className="py-2 px-3 align-middle">
                                <div className="flex items-center gap-1.5">
                                  <span className="font-mono font-semibold">{target.name}</span>
                                  <span className="text-[10px] font-mono text-muted-foreground uppercase">
                                    ({target.type})
                                  </span>
                                  {target.required ? (
                                    <Badge
                                      variant="secondary"
                                      className="text-[9px] font-medium h-4 px-1"
                                    >
                                      Required
                                    </Badge>
                                  ) : null}
                                </div>
                              </TableCell>

                              {/* Column 4: Status */}
                              <TableCell className="py-2 px-3 align-middle text-right">
                                {isMapped ? (
                                  <StatusBadge label="MAPPED" tone={StatusTone.HEALTHY} />
                                ) : target.required ? (
                                  <Badge
                                    variant="outline"
                                    className="text-[10px] font-medium h-5 px-1.5 text-muted-foreground"
                                  >
                                    Unmapped
                                  </Badge>
                                ) : (
                                  <span className="text-xs text-muted-foreground font-mono">—</span>
                                )}
                              </TableCell>
                            </TableRow>
                          );
                        })}
                      </TableBody>
                    </Table>
                  </div>
                </CardContent>
              </Card>
            </TabsContent>

            {/* TAB 3: DESTINATION */}
            <TabsContent value="destination" className="space-y-3 pt-1">
              <Card className="border-border">
                <CardHeader className="py-3 px-4 flex flex-row items-center justify-between">
                  <div className="flex items-center gap-2">
                    <StatusBadge label={targetTopic || 'Wire Contract'} tone={StatusTone.NEUTRAL} />
                    <span className="text-sm font-semibold">{targetFields.length} Wire Fields</span>
                  </div>
                </CardHeader>
                <CardContent className="px-4 pb-4">
                  <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                    {/* Reused Monaco Editor Component */}
                    <DestinationSchemaMonacoEditor
                      value={customContractJson}
                      onChange={setCustomContractJson}
                      onApply={handleApplyTargetFields}
                      onClear={handleClearCustomContract}
                      height={340}
                    />

                    {/* Active Wire Fields Table */}
                    <div className="space-y-2">
                      <div className="flex items-center justify-between text-xs">
                        <span className="font-semibold text-foreground">Active Wire Fields</span>
                        <span className="text-[11px] text-muted-foreground font-mono">
                          {targetFields.length} field(s)
                        </span>
                      </div>
                      <div className="rounded-lg border border-border bg-card overflow-hidden max-h-[380px] overflow-y-auto">
                        <Table className="text-xs">
                          <TableHeader className="bg-muted/50 sticky top-0 z-10">
                            <TableRow>
                              <TableHead className="py-2 px-3 font-semibold">Wire Field</TableHead>
                              <TableHead className="py-2 px-3 font-semibold">Data Type</TableHead>
                              <TableHead className="py-2 px-3 font-semibold">Requirement</TableHead>
                              <TableHead className="py-2 px-3 font-semibold">Description</TableHead>
                            </TableRow>
                          </TableHeader>
                          <TableBody>
                            {targetFields.map((t) => (
                              <TableRow key={t.name}>
                                <TableCell className="font-mono font-medium py-2 px-3">
                                  {t.name}
                                </TableCell>
                                <TableCell className="font-mono text-muted-foreground py-2 px-3">
                                  {t.type}
                                </TableCell>
                                <TableCell className="py-2 px-3">
                                  {t.required ? (
                                    <Badge
                                      variant="secondary"
                                      className="text-[10px] font-medium h-5 px-1.5"
                                    >
                                      Required
                                    </Badge>
                                  ) : (
                                    <span className="text-muted-foreground text-xs">Optional</span>
                                  )}
                                </TableCell>
                                <TableCell className="text-muted-foreground py-2 px-3">
                                  {t.description ?? '—'}
                                </TableCell>
                              </TableRow>
                            ))}
                          </TableBody>
                        </Table>
                      </div>
                    </div>
                  </div>
                </CardContent>
              </Card>
            </TabsContent>
          </Tabs>

          {/* BOTTOM SECTION: LIVE SPLIT MONACO PREVIEW */}
          <Card className="border-border">
            <CardHeader className="py-3 px-4 flex flex-row items-center justify-between">
              <div className="flex items-center gap-2">
                <Code2 className="h-4 w-4 text-primary" />
                <span className="text-sm font-semibold">Live Preview</span>
              </div>
              {requiredUnmappedCount === 0 ? (
                <span className="flex items-center gap-1.5 text-emerald-600 dark:text-emerald-400 text-xs font-medium">
                  <CheckCircle2 className="h-3.5 w-3.5" />
                  <span>Ready to Deploy</span>
                </span>
              ) : (
                <span className="text-amber-600 dark:text-amber-400 text-xs font-medium">
                  {requiredUnmappedCount} required field(s) unmapped
                </span>
              )}
            </CardHeader>
            <CardContent className="px-4 pb-4">
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div className="space-y-1.5">
                  <div className="flex items-center justify-between text-xs">
                    <span className="font-medium text-foreground">
                      Source: {activeCanonicalModel.displayName}
                    </span>
                    <span className="font-mono text-muted-foreground text-[11px]">
                      {activeCanonicalModel.canonicalEventType}
                    </span>
                  </div>
                  <div className="rounded-lg border border-border overflow-hidden">
                    <MonacoCodeViewer
                      height={220}
                      language="json"
                      value={stringifyJsonPretty(activeCanonicalModel.defaultSampleRecord)}
                    />
                  </div>
                </div>

                <div className="space-y-1.5">
                  <div className="flex items-center justify-between text-xs">
                    <span className="font-medium text-foreground">
                      Destination: {targetTopic || 'Wire Output'}
                    </span>
                    <span className="font-mono text-muted-foreground text-[11px]">
                      {mappedCount} active field(s)
                    </span>
                  </div>
                  <div className="rounded-lg border border-border overflow-hidden">
                    <MonacoCodeViewer
                      height={220}
                      language="json"
                      value={stringifyJsonPretty(liveProjectedOutput)}
                    />
                  </div>
                </div>
              </div>
            </CardContent>
          </Card>
        </>
      )}

      {/* CUSTOM SCHEMA MODAL DIALOG */}
      <Dialog open={schemaModalOpen} onOpenChange={setSchemaModalOpen}>
        <DialogContent className="sm:max-w-2xl">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2 text-base">
              <Code2 className="h-4 w-4 text-primary" />
              <span>Custom Schema</span>
            </DialogTitle>
          </DialogHeader>

          <div className="space-y-3 py-2">
            <div className="space-y-1.5">
              <Label className="text-xs font-semibold">
                Destination Entity / Topic / Directory
              </Label>
              <Input
                value={pendingCustomTopic}
                onChange={(e) => setPendingCustomTopic(e.target.value)}
                placeholder="Enter topic, entity, or directory name..."
                className="h-9 text-xs font-mono"
              />
            </div>

            <DestinationSchemaMonacoEditor
              value={customContractJson}
              onChange={setCustomContractJson}
              onClear={handleClearCustomContract}
              height={300}
            />
          </div>

          <DialogFooter className="flex items-center justify-end sm:justify-end gap-2">
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={() => setSchemaModalOpen(false)}
            >
              Cancel
            </Button>
            <Button
              type="button"
              size="sm"
              onClick={() => {
                const topicToSet = pendingCustomTopic.trim() || targetTopic.trim();
                if (!topicToSet) {
                  toast.error('Please enter a Destination Entity, Topic, or Directory name.');
                  return;
                }
                const res = inferSchemaFromSampleJson(customContractJson);
                if (res.error) {
                  toast.error(res.error);
                  return;
                }
                setTargetTopic(topicToSet);
                setCustomTargetFields(res.fields);
                setMappingRules([]);
                setSchemaModalOpen(false);

                // Persist to Contract Layer (ip.connection_entities) for target connection
                if (targetConnectionId) {
                  void addConnectionEntityMutation.mutateAsync({
                    streamName: topicToSet,
                    fields: res.fields.map((f) => ({
                      name: f.name,
                      dataType: f.type,
                      nullable: !f.required,
                      description: f.description ?? null,
                    })),
                  });
                }

                toast.success(
                  `Configured destination "${topicToSet}" with ${res.fields.length} wire fields.`,
                );
              }}
              className="gap-1.5"
            >
              <Sparkles className="h-3.5 w-3.5" />
              <span>Apply &amp; Select</span>
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
