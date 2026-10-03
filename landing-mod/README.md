# Modpack landing page

An independent Next.js project, ready to deploy from the account you choose.

## Structure

- `src/app`: routes, metadata, and page composition.
- `src/components`: UI components with a focused responsibility.
- `src/lib`: server configuration and download-link settings.
- `src/styles`: tokens and global styles.

## Local configuration

1. Copy `.env.example` to `.env.local`.
2. Add the public ZIP URL to `NEXT_PUBLIC_MODPACK_DOWNLOAD_URL`.
3. Run `npm install`, then `npm run dev`.

It does not include the ZIP, credentials, or a connection to any Vercel account.

## Deploying to Vercel

When importing the repository, select `landing-mod` as the **Root Directory**. You do not need to change the Build Command or Output Directory.

Configure Production and Preview environment variables from Vercel. `NEXT_PUBLIC_MODPACK_DOWNLOAD_URL` and `NEXT_PUBLIC_SERVER_ADDRESS` are the only values required to publish the download page. `NEXT_PUBLIC_MODPACK_CHANGELOG_URL` is optional: the landing page already includes a link to this project's change document.

## Server status

- The status card queries `mcstatus.io` directly from the browser. This is intentional: Vercel cannot reliably reach the host PC and must not access the administration panel.
- The query sends only the public Minecraft address to `mcstatus.io`; it does not use credentials, tokens, or panel endpoints.
- Do not replace this query with a Vercel route that forwards to the panel unless a private, authenticated network exists between both services.

## Modpack data

- The catalog uses `src/lib/mods-manifest.json`, generated with the published ZIP. JAR counts and totals are calculated from that manifest; `server/mods` is never read.
- The ZIP's compressed size is not shown as a static promise: it changes on every export and should only be published when updated with the file.

## Publishing a new version

1. In Google Drive, open `modpack-amigos.zip` and use **Manage versions → Upload new version**. This preserves the URL used by Vercel.
2. Add the new entry at the top of `src/lib/modpack-releases.ts`: version, summary, changes, and whether the ZIP must be downloaded again.
3. Update the [MODPACK CHANGELOG](https://docs.google.com/document/d/1vvTB8a44txZExpB45Iq77vi64njjB69tYByTQR-YzZw/edit) in the same Drive folder. It is the editable history for the group.
4. Deploy the landing page. You do not need to change the download URL or regenerate the catalog when the JARs have not changed.

The console and command sending are not exposed on the landing page: they remain protected in the administration panel.
