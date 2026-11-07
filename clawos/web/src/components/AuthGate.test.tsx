import { describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import axe from 'axe-core';
import { AuthGate } from './AuthGate';

vi.mock('../api', () => ({
  fetchCurrentUser: vi.fn().mockRejectedValue(new Error('offline')),
  login: vi.fn(), bootstrapOwner: vi.fn(), logout: vi.fn(),
}));

describe('AuthGate accessibility', () => {
  it('renders an accessible authentication form while offline', async () => {
    const { container } = render(<AuthGate>{() => <div>workspace</div>}</AuthGate>);
    await waitFor(() => expect(screen.getByRole('button', { name: /登录|鐧诲綍/ })).toBeInTheDocument());
    const result = await axe.run(container, { rules: { 'color-contrast': { enabled: false } } });
    expect(result.violations).toEqual([]);
  });
});
