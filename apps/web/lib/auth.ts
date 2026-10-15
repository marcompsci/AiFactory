"use client";

/**
 * Sign in with Google or GitHub through Supabase Auth (configured with NEXT_PUBLIC_SUPABASE_URL and
 * NEXT_PUBLIC_SUPABASE_ANON_KEY). The session's access token becomes the API bearer token; the API verifies it with the
 * project's JWT secret and maps the owner by `app_metadata.role` (or AICIV_OWNER_EMAILS, see docs/AUTH.md).
 *
 * GitHub sign-in can also hand the App Lab a GitHub token (`provider_token`) for one repository the owner then
 * authorizes explicitly. Supabase returns it only right after the GitHub redirect, so it is kept in memory for this tab
 * and never written to storage.
 *
 * Claude: third-party apps may not offer claude.ai login, so this app never asks for one. Agents use an Anthropic API
 * key on the server, and Claude Code runs in GitHub through Anthropic's Claude Code GitHub Action with your own
 * CLAUDE_CODE_OAUTH_TOKEN repository secret (from `claude setup-token`).
 */
import { createClient, type Session, type SupabaseClient } from "@supabase/supabase-js";
import { loadConnection, saveConnection } from "./api";

let client: SupabaseClient | null = null;
let githubToken: string | null = null;

export function authConfigured(): boolean {
  return Boolean(process.env.NEXT_PUBLIC_SUPABASE_URL && process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY);
}

export function supabase(): SupabaseClient | null {
  if (!authConfigured()) return null;
  if (!client) {
    client = createClient(process.env.NEXT_PUBLIC_SUPABASE_URL!, process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!, {
      auth: { persistSession: true, autoRefreshToken: true, detectSessionInUrl: true, flowType: "pkce" },
    });
    client.auth.onAuthStateChange((_event, session) => adopt(session));
    client.auth.getSession().then(({ data }) => adopt(data.session));
  }
  return client;
}

function adopt(session: Session | null): void {
  const c = loadConnection();
  if (session?.provider_token && session.user?.app_metadata?.provider === "github") githubToken = session.provider_token;
  if (session?.access_token && c.token !== session.access_token) saveConnection({ ...c, token: session.access_token });
  if (!session && c.token && c.token.split(".").length === 3) saveConnection({ ...c, token: "" }); // signed out: drop the JWT
  listeners.forEach((fn) => fn(session));
}

const listeners = new Set<(s: Session | null) => void>();
export function onSession(fn: (s: Session | null) => void): () => void {
  listeners.add(fn);
  supabase();
  return () => listeners.delete(fn);
}

export async function signIn(provider: "google" | "github", withRepoAccess = false): Promise<void> {
  const sb = supabase();
  if (!sb) throw new Error("Sign-in is not configured on this deployment (NEXT_PUBLIC_SUPABASE_URL / NEXT_PUBLIC_SUPABASE_ANON_KEY).");
  const { error } = await sb.auth.signInWithOAuth({
    provider,
    options: {
      redirectTo: window.location.origin + window.location.pathname,
      // GitHub: `repo` only when the owner asks to connect repositories to the App Lab.
      scopes: provider === "github" ? (withRepoAccess ? "read:user user:email repo" : "read:user user:email") : undefined,
    },
  });
  if (error) throw error;
}

export async function signOut(): Promise<void> {
  githubToken = null;
  await supabase()?.auth.signOut();
}

/** The GitHub token from a fresh GitHub sign-in, if any (memory only). */
export function githubSigninToken(): string | null {
  return githubToken;
}
