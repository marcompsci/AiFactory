# Signing in

The web app signs you in with **Google** or **GitHub** through Supabase Auth. Without Supabase, it uses an API
token (`AICIV_API_TOKEN`), or dev mode on localhost.

## Setup

1. In Supabase → Authentication → Providers, enable **Google** and **GitHub** with your OAuth client ids and secrets.
   Add the web app's URL to the redirect allow-list.
2. Web app environment:
   `NEXT_PUBLIC_SUPABASE_URL=https://<project>.supabase.co`, `NEXT_PUBLIC_SUPABASE_ANON_KEY=<anon key>`.
3. API environment: `SUPABASE_JWT_SECRET=<project JWT secret>` (the API verifies every session token).
4. Make yourself the owner. Either:
   - set `app_metadata.role = "owner"` for your user (Supabase dashboard or service key; users can't change
     `app_metadata` themselves), or
   - set `AICIV_OWNER_EMAILS=you@example.com`. A signed-in user whose **verified** email is on that list is the owner.
     Everyone else is a `viewer` until you give them a role.

## What each sign-in gives

- **Google**: identity only.
- **GitHub**: identity. If you choose *Sign in with GitHub with repository access*, it also gives a GitHub token
  (`repo` scope), which you can use to connect a repository to App Lab. The browser keeps that token in memory for
  the tab only. The API stores it only after you explicitly authorize a specific repository, with step-up, and then
  encrypted. A fine-grained, single-repository token is the safer choice (see [APP_LAB.md](APP_LAB.md)).
- **Claude**: there is no "Sign in with Claude". Third-party apps may not offer claude.ai login
  ([Anthropic: legal and compliance](https://code.claude.com/docs/en/legal-and-compliance)). Agents use the server's
  `ANTHROPIC_API_KEY`. Claude Code works in your repository through the Claude Code GitHub Action with your own
  `CLAUDE_CODE_OAUTH_TOKEN` secret.

Approving money or code changes always needs step-up (an authenticator code, or a Supabase `aal2` session),
whatever you signed in with.
