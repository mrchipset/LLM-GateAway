/** Browser navigation target for the SSO flow; the backend answers with a redirect to the IdP. */
export const OIDC_START_PATH = '/api/v1/auth/oidc/start';

const SSO_ERROR_PARAM = 'sso_error';

const GENERIC_SSO_ERROR =
  'Single sign-on could not be completed. Try again, or sign in with your password.';

/**
 * The backend reports failures as `/?sso_error=<code>`. Messages stay short and
 * non-technical because the code itself is meaningless to the person signing in.
 */
const SSO_ERROR_MESSAGES: Record<string, string> = {
  admin_not_provisioned:
    'No console account is linked to this identity yet. Ask an owner to create one.',
  admin_inactive: 'This account has been deactivated. Ask an owner to reactivate it.',
  role_not_mapped:
    'Your sign-in role does not grant access to the console. Ask an owner to check the role mapping.',
  nonce_mismatch: 'This sign-in attempt could not be verified. Try again.',
  invalid_id_token: 'The identity provider sent a response we could not verify. Try again.',
  token_exchange_failed: 'Sign-in with the identity provider did not complete. Try again.',
  discovery_failed: 'The identity provider could not be reached. Try again in a moment.',
  oidc_failed:
    'Single sign-on stopped before it finished. Try again, or sign in with your password.',
};

export function readSsoErrorCode(search: string): string | null {
  return new URLSearchParams(search).get(SSO_ERROR_PARAM);
}

export function ssoErrorMessage(code: string | null): string | null {
  if (code === null || code === '') return null;
  return SSO_ERROR_MESSAGES[code] ?? GENERIC_SSO_ERROR;
}

/** Drops the error code from the query string so a refresh does not repeat the banner. */
export function withoutSsoError(search: string): string {
  const params = new URLSearchParams(search);
  params.delete(SSO_ERROR_PARAM);
  const query = params.toString();
  return query === '' ? '' : `?${query}`;
}
