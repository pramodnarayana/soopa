import {
  AuthType,
  type AuthTypeValue,
  ReplayStage,
  type ReplayStageValue,
  TransformationMode,
  type TransformationModeValue,
} from './enums';

const AUTH_TYPE_SET: ReadonlySet<string> = new Set(Object.values(AuthType));
export function isAuthTypeValue(candidate: string): candidate is AuthTypeValue {
  return AUTH_TYPE_SET.has(candidate);
}

const TRANSFORMATION_MODE_SET: ReadonlySet<string> = new Set(Object.values(TransformationMode));
export function isTransformationModeValue(candidate: string): candidate is TransformationModeValue {
  return TRANSFORMATION_MODE_SET.has(candidate);
}

const REPLAY_STAGE_SET: ReadonlySet<string> = new Set(Object.values(ReplayStage));
export function isReplayStageValue(candidate: string): candidate is ReplayStageValue {
  return REPLAY_STAGE_SET.has(candidate);
}
