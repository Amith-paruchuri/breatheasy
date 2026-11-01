# Shareable short link (Vercel)

This folder is a tiny Vercel project whose only job is a short, easy-to-share address
(for example `breatheasy.vercel.app`). Every visit is redirected to the real app on
Cloud Run, so sign-in, the map key and rate limits all keep working unchanged.

Set up once in Vercel: Add New > Project > import `Amith-paruchuri/breatheasy`,
set **Root Directory** to `deploy/vercel`, Framework Preset **Other**, and deploy.

It's a redirect rather than a proxy on purpose: behind a proxy every visitor would
reach Cloud Run from Vercel's servers, which would break per-person rate limits
and need extra Google sign-in and Maps key settings. For a branded address that
stays in the address bar, use a custom domain instead (see deploy/LAUNCH_CHECKLIST.md).
