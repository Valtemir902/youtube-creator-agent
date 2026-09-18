# Customer web authentication

The Elite dashboard supports direct customer access from notebook or mobile without requiring ChatGPT to mint an onboarding link.

## Browser flow

1. `https://creator.silvadigitaltech.com/` redirects anonymous users to `/login`.
2. The login page offers **Entrar**, **Criar conta**, and **Esqueci minha senha**.
3. Cloudflare Turnstile is verified server-side before an OIDC flow can start.
4. Keycloak handles email/password credentials, registration, email verification, and reset-credentials.
5. The backend uses Authorization Code + PKCE and consumes a single-use server-side state record.
6. After successful OIDC authentication, the backend creates an HttpOnly, Secure, SameSite=Lax session cookie.
7. Accounts without a connected YouTube channel are sent to `/onboarding`; connected accounts go to `/dashboard`.
8. YouTube OAuth remains separate from the Creator Agent customer account.

No password is collected or stored by the Creator Agent application.

## Keycloak realm requirements

Use the existing production realm behind `YCA_AUTH_ISSUER_URL`. In **Realm settings > Login** enable:

- User registration
- Forgot password
- Remember me (optional)
- Login with email
- Verify email

Configure SMTP in the realm so verification and password-reset messages can be delivered. Keep brute-force detection enabled.

## Dedicated browser OIDC client

Create a dedicated confidential OIDC client, for example `creator-web`.

Recommended settings:

- Standard flow: enabled
- Direct access grants: disabled
- Implicit flow: disabled
- PKCE method: S256
- Valid redirect URI: `https://creator.silvadigitaltech.com/auth/callback`
- Valid post logout redirect URI: `https://creator.silvadigitaltech.com/login`
- Web origin: `https://creator.silvadigitaltech.com`

Store the client secret only in `config/server.env` on the VPS.

Required server variables:

```text
YCA_WEB_OIDC_ISSUER_URL=https://auth.silvadigitaltech.com/realms/<REALM>
YCA_WEB_OIDC_CLIENT_ID=creator-web
YCA_WEB_OIDC_CLIENT_SECRET=<SERVER_ONLY_SECRET>
YCA_WEB_OIDC_REDIRECT_URI=https://creator.silvadigitaltech.com/auth/callback
YCA_WEB_OIDC_SCOPE=openid email profile
YCA_REQUIRE_VERIFIED_EMAIL=1
```

The browser OIDC issuer should be the same realm identity used by the MCP resource server so the same Keycloak user maps deterministically to the same tenant.

## Cloudflare Turnstile

Create a Turnstile widget in Cloudflare for:

```text
creator.silvadigitaltech.com
```

Store:

```text
YCA_TURNSTILE_SITE_KEY=<PUBLIC_SITE_KEY>
YCA_TURNSTILE_SECRET_KEY=<SERVER_ONLY_SECRET>
YCA_TURNSTILE_BYPASS=0
```

The site key is intentionally returned to the browser. The secret key is never returned by an API endpoint and must never be committed.

`YCA_TURNSTILE_BYPASS=1` is only for local development and tests. Production fails closed if anti-bot configuration is missing.

## Security properties

- OIDC Authorization Code flow
- PKCE S256
- one-time state stored server-side
- state expiry
- anti-open-redirect validation for the post-login destination
- Turnstile server verification
- rate limits on authentication start/callback
- HttpOnly session cookie
- Secure cookie by default
- SameSite=Lax
- stable tenant identity derived from issuer + OIDC subject
- verified email gate by default
- separate YouTube OAuth authorization
- no Creator Agent password database

## Smoke test after deployment

Do not test by changing a real video first. Validate the authentication surface in this order:

```text
GET /                  -> 303 /login when anonymous
GET /login             -> 200
GET /api/auth/config   -> 200, oidc_ready=true, turnstile_ready=true
```

Then complete Turnstile, create/login to an account, verify the email when required, and confirm:

- new account without YouTube -> `/onboarding`
- existing connected account -> `/dashboard`
- logout -> `/login`
- direct `/dashboard` without a valid session cannot expose channel data
