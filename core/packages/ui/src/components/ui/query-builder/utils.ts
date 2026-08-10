import { FilterOperator } from './types';

export const getOperatorLabel = (operator: string | FilterOperator): string => {
  const map: Record<string, string> = {
    eq: '=',
    neq: '!=',
    contains: 'contains',
    not_contains: 'does not contain',
    gt: '>',
    lt: '<',
    gte: '>=',
    lte: '<=',
    in: 'in',
    not_in: 'not in',
    is_null: 'is empty',
    is_not_null: 'is not empty',
  };
  return map[operator] || operator;
};
