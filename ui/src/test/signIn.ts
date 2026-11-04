import { screen } from '@testing-library/react';
import type { UserEvent } from '@testing-library/user-event';

import { DEFAULT_ADMIN_PASSWORD, DEFAULT_ADMIN_USERNAME } from './fetchMock';

export async function signIn(
  user: UserEvent,
  credentials: { username?: string; password?: string } = {},
) {
  const username = await screen.findByLabelText('Username');
  await user.type(username, credentials.username ?? DEFAULT_ADMIN_USERNAME);
  await user.type(
    screen.getByLabelText('Password'),
    credentials.password ?? DEFAULT_ADMIN_PASSWORD,
  );
  await user.click(screen.getByRole('button', { name: 'Sign in' }));
  await screen.findByRole('tab', { name: 'Models' });
}
