# Privacy Policy Template — YouTube Creator Agent

> TEMPLATE ONLY. Replace bracketed fields and review the final document before publication. Do not publish claims that do not match the deployed infrastructure.

Effective date: [DATE]
Operator: [LEGAL NAME]
Contact: [SUPPORT/PRIVACY EMAIL OR URL]

## What the service does

YouTube Creator Agent connects a user's authorized YouTube account to ChatGPT and/or the standalone desktop product so the user can analyze channel performance, validate content opportunities, and review or apply approved changes to video metadata.

## Data we may process

Depending on the features the user enables, the service may process:

- YouTube channel and video identifiers, titles, descriptions, tags and public statistics;
- YouTube Analytics data available to the connected account, including performance metrics and search terms that generated channel traffic when provided by YouTube Analytics;
- Google/YouTube OAuth credentials needed to maintain the authorized connection;
- account/tenant identifiers supplied by the configured authentication provider;
- optional external-AI provider settings and API credentials when the user chooses standalone/external-AI mode;
- operational security data such as request identifiers, rate-limit counters and sanitized audit events.

## How credentials are protected

OAuth credentials and optional external-AI API credentials are stored encrypted at rest by the server. Secrets should be stored separately from source code and production encryption keys must be held in the hosting provider's secret manager.

The service is designed not to write raw access tokens, API keys, cookies, passwords or authorization headers into operational audit metadata.

## ChatGPT Native mode

When the app is used in ChatGPT Native mode, the backend does not require a separate Gemini, OpenAI API, Groq, xAI or other external LLM key for strategy generation. ChatGPT performs the reasoning while this service supplies authenticated YouTube data, deterministic metrics and approved YouTube actions.

## Why we process data

Data is processed to provide features requested by the user, secure account access, prevent abuse, diagnose service reliability, and carry out user-approved actions.

## Data retention

[INSERT THE ACTUAL PRODUCTION RETENTION POLICY.]

The current application architecture includes short-lived onboarding links and sessions, encrypted account credentials, derived strategy/history data, operational rate-limit counters and sanitized audit events. Before publication, document the actual retention period for each category as deployed.

## Data sharing and service providers

[LIST ONLY THE HOSTING, AUTHENTICATION, DATABASE, MONITORING, EMAIL/SUPPORT OR OTHER PROCESSORS ACTUALLY USED IN PRODUCTION.]

Google/YouTube APIs are used when the user connects a YouTube account. ChatGPT/OpenAI handles conversation-side processing according to the user's ChatGPT account and OpenAI terms. Optional external AI providers are contacted only when the user configures that separate mode.

## User choices and deletion

Users can disconnect their YouTube account from the onboarding interface. Before publication, provide a documented path for account/data deletion requests at [DELETE/PRIVACY CONTACT URL].

## Security

The service uses authenticated tenant isolation, encrypted credential storage, short-lived setup links, scoped read/write permissions, rate limiting, signed write previews, explicit confirmation for metadata changes and audit logging designed to exclude secrets.

No internet service can promise absolute security. [ADD YOUR INCIDENT/SECURITY CONTACT PROCESS IF APPLICABLE.]

## Children's data

[DEFINE THE ACTUAL AGE/ELIGIBILITY POLICY FOR THE COMMERCIAL PRODUCT.]

## Changes to this policy

We may update this policy when the product or legal requirements change. The effective date above will be updated when a revised policy is published.

## Contact

[LEGAL NAME]
[BUSINESS ADDRESS IF REQUIRED]
[PRIVACY/SUPPORT EMAIL OR URL]
