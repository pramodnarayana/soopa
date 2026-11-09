import { describe, expect, it } from 'vitest';
import * as DomainEnums from '../domain/enums';
import * as SeedFixtures from '../testing/seed-fixtures';

const BANNED_VERTICAL_DOMAIN_PATTERN =
  /\bitron\b|itron_|meter_read|meter_interval|meter_serial|\bmeter\b|\bami\b|ami_|service_point|\benergy\b|mdm_|smart grid|\btms\b|sap[-_]isu/i;

describe('IP UI Domain Purity Guard', () => {
  it('excludes business-vertical vocabulary from domain enums', () => {
    const serializedDomainEnums = JSON.stringify(DomainEnums);
    expect(BANNED_VERTICAL_DOMAIN_PATTERN.exec(serializedDomainEnums)).toBeNull();
  });

  it('excludes business-vertical vocabulary from workspace seed fixtures', () => {
    const serializedSeedFixtures = JSON.stringify(SeedFixtures);
    expect(BANNED_VERTICAL_DOMAIN_PATTERN.exec(serializedSeedFixtures)).toBeNull();
  });
});
