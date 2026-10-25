import { screen } from '@testing-library/react';
import type { UserEvent } from '@testing-library/user-event';

export async function connectWithKey(user: UserEvent, masterKey = 'mk_test_123') {
  await user.type(await screen.findByLabelText('Master key'), masterKey);
  await user.click(screen.getByRole('button', { name: 'Connect' }));
}
