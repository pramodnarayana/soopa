# EDI AS2 Console

The EDI AS2 Console is the React-based frontend for the enterprise EDI AS2 platform. It provides a control plane for administrators to configure trading partners, monitor AS2 payloads, and manage tenants.

## Features

- **Authentication & Single Sign-On (SSO)**: Powered by Zitadel OIDC integration (`react-oidc-context`).
- **Dashboard**: High-level overview of incoming and outgoing AS2 payloads.
- **Tenant Provisioning**: Real-time verification of Just-In-Time (JIT) tenant provisioning and PostgreSQL Row-Level Security (RLS) enforcement.
- **Identity Insights**: Tools to introspect SSO claims and external identity profiles.

## Architecture & Stack

- **React 18** with Strict Mode enabled
- **Vite** for fast HMR and optimized builds
- **Tailwind CSS** + **Radix UI** + **shadcn/ui** for accessible, headless components
- **TanStack Router** for fully typed client-side routing

## Setup & Development

### Prerequisites

You must have the backend API gateway and Zitadel SSO running locally. See the root workspace for `docker-compose` instructions.

### Local Development

1. Create your local environment configuration by copying the example:
   ```bash
   cp .env.example .env
   ```

2. Update `.env` with your actual Zitadel Client ID and endpoint URLs.

3. Install dependencies and start the Vite dev server:
   ```bash
   npm install
   npm run dev
   ```

### Linting & Formatting

The project uses a combination of Biome, ESLint, and Stylelint.

```bash
# Run linters
npm run lint

# Format code
npm run format
```
