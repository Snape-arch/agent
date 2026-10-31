import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import axe from 'axe-core';
import { describe, expect, it, vi } from 'vitest';
import { RoleHome } from '../App';
import { initialRuns } from '../domain';

describe('role home', () => {
  it('prioritizes viewer-safe tasks and has no detectable axe violations', async () => {
    const onNavigate=vi.fn();const {container}=render(<RoleHome user={{userId:'u',tenantId:'t',role:'viewer',scopes:['read']}} runs={initialRuns()} onNavigate={onNavigate}/>);
    expect(screen.getByText('查看项目进展')).toBeInTheDocument();
    expect(screen.queryByText('运行实验')).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole('button',{name:/查看最新结果/}));
    expect(onNavigate).toHaveBeenCalledWith('overview');
    const result=await axe.run(container);
    expect(result.violations.map((item)=>item.id)).toEqual([]);
  });
});
