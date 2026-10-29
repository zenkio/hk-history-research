# Preview site

`preview.yml` builds the site from any branch of the private data repository and uploads it to Cloudflare
Pages, so unmerged data or code changes can be looked at before they reach the live site. The live site
(`deploy.yml`, GitHub Pages) is not touched.

Run it: Actions > "Preview site (Cloudflare Pages)" > Run workflow, `data_ref` = the data PR's branch.
Code comes from the branch the workflow is run on. The log prints the preview address
(`<branch-slug>.<project>.pages.dev`; `main` of the data repo is the project's production address).

## One-time setup (owner, in Cloudflare and GitHub settings)

1. Cloudflare > Workers & Pages > Create > Pages > Direct Upload: create project `hkhistory-preview`
   (or another name, then set the repository variable `CLOUDFLARE_PREVIEW_PROJECT`).
2. Cloudflare > My Profile > API Tokens: a token with only "Account > Cloudflare Pages > Edit".
   Add it as repository secret `CLOUDFLARE_API_TOKEN`; add the account id as `CLOUDFLARE_ACCOUNT_ID`.
3. Cloudflare Zero Trust > Access > Applications: protect `*.hkhistory-preview.pages.dev` and
   `hkhistory-preview.pages.dev` with a policy allowing only the owner's email. Do this BEFORE the first run:
   a preview can hold unmerged private data, and is otherwise public to anyone with the address.
4. Optional: a custom domain such as `preview.hkhistory.zenkio.uk` on the Pages project.

Previews are noindex (the same check as the live site) and are not a place for secrets or private notes:
only the built pages are uploaded, never the Markdown, research or state.
