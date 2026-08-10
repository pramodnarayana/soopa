export type FilterOperator =
  | 'eq'
  | 'neq'
  | 'contains'
  | 'not_contains'
  | 'gt'
  | 'lt'
  | 'gte'
  | 'lte'
  | 'in'
  | 'not_in'
  | 'is_null'
  | 'is_not_null';

export interface FilterRule {
  id: string; // Unique identifier for the UI rule row
  field: string;
  operator: FilterOperator;
  value: string | number | boolean | unknown[] | null;
}

export type FieldType = 'text' | 'number' | 'date' | 'boolean' | 'enum';

export interface FieldOption {
  label: string;
  value: string | number | boolean;
}

export interface FieldDef {
  id: string;
  label: string;
  type?: FieldType; // Defaults to 'text' if not provided
  options?: FieldOption[]; // For 'enum' type
  operators?: FilterOperator[]; // Allow explicit override of permitted operators
}
