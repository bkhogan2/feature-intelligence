import { expect, test } from "bun:test";
import { Window } from "happy-dom";
import { createRoot } from "react-dom/client";
import { createElement, act } from "react";
import { AuthProvider, api, useAuth } from "../src/lib/auth-context";

test("401 clears signed-in state; 403 retains it", async () => {
  const win = new Window();
  const saved = {Event:globalThis.Event,fetch:globalThis.fetch,window:globalThis.window,document:globalThis.document};
  Object.assign(globalThis, { Event: win.Event, window: win, document: win.document, IS_REACT_ACT_ENVIRONMENT: true });
  let failure = 403;
  globalThis.fetch = (async (url: string) => {
    const body = url.endsWith('/auth/config') ? {provider:'local'} : url.endsWith('/me/workspaces') ? [] : url.endsWith('/me') ? {subject:'user',email:'user@example.com',email_verified:true} : {detail:'Please sign in'};
    return new Response(JSON.stringify(body), {status: url.endsWith('/feedback') ? failure : 200});
  }) as typeof fetch;
  function State() { const auth=useAuth(); return createElement('div',null,auth.user ? 'signed in' : 'login'); }
  const el=win.document.createElement('div');
  const root=createRoot(el as unknown as HTMLElement);
  try {
    await act(async () => { root.render(createElement(AuthProvider, null, createElement(State))); });
    expect(el.textContent).toBe('signed in');
    await act(async () => { await api('/feedback').catch(()=>{}); });
    expect(el.textContent).toBe('signed in');
    failure=401;
    await act(async () => { await api('/feedback').catch(()=>{}); });
    expect(el.textContent).toBe('login');
  } finally {
    await act(async () => root.unmount());
    Object.assign(globalThis, saved);
  }
});
