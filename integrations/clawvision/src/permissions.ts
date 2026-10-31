import type { CurrentUser } from './api';

export type Capability = 'runs:create'|'assets:write'|'assets:approve'|'workspace:admin';

const grants: Record<CurrentUser['role'], ReadonlySet<Capability>> = {
  viewer: new Set(),
  researcher: new Set(['runs:create','assets:write']),
  admin: new Set(['runs:create','assets:write','assets:approve','workspace:admin']),
  owner: new Set(['runs:create','assets:write','assets:approve','workspace:admin']),
};

export function can(user: CurrentUser, capability: Capability): boolean {
  return grants[user.role].has(capability) && (user.scopes.includes('*') || (
    capability === 'workspace:admin' || capability === 'assets:approve'
      ? user.scopes.includes('admin')
      : user.scopes.includes('write')
  ));
}
