import { describe,expect,it } from 'vitest';
import { can } from './permissions';

const user=(role:'viewer'|'researcher'|'admin'|'owner',scopes:string[])=>({userId:'u',tenantId:'t',role,scopes});

describe('capability policy',()=>{
  it('never lets wildcard scope exceed the role ceiling',()=>{
    expect(can(user('viewer',['*']),'runs:create')).toBe(false);
    expect(can(user('viewer',['*']),'workspace:admin')).toBe(false);
  });
  it('requires both a capable role and matching scope',()=>{
    expect(can(user('researcher',['write']),'runs:create')).toBe(true);
    expect(can(user('researcher',['read']),'runs:create')).toBe(false);
    expect(can(user('admin',['admin']),'assets:approve')).toBe(true);
    expect(can(user('researcher',['*']),'assets:approve')).toBe(false);
  });
});
