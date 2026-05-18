# Publishing @privacyshield/sdk

This package is published automatically by GitHub Actions on git tag push.

## One-time setup

### 1. Create the npm organization (if missing)

The `@privacyshield` scope must exist on npmjs.com before first publish.

- Visit https://www.npmjs.com/org/create
- Org name: `privacyshield`
- Plan: **Free** (sufficient for public packages)
- Confirm the org owner is your npm account

Verify:
```bash
npm org ls privacyshield
```

### 2. Create npm publish token

- Visit https://www.npmjs.com/settings/`<your-username>`/tokens/granular-access-tokens/new
- Token name: `privacyshield-sdk-ci`
- Expiration: **90 days** (renew before expiry)
- Packages and scopes: select `@privacyshield/*`
- Permission: **Read and write**
- Click **Generate token** and copy the `npm_...` value immediately (shown once only)

### 3. Add token to GitHub repo secrets

- Visit `https://github.com/paolobiancalana/privacy-shield/settings/secrets/actions/new`
- Name: `NPM_TOKEN`
- Secret: paste the `npm_...` token from step 2
- Save

## Releasing a new version

Bump the version in `sdks/js/package.json`, commit, then push a tag:

```bash
cd sdks/js
npm version patch   # or `minor` / `major` / explicit `1.2.0`
cd ../..
git add sdks/js/package.json sdks/js/package-lock.json
git commit -m "chore(sdk): release v$(node -p "require('./sdks/js/package.json').version")"
TAG="sdk-v$(node -p "require('./sdks/js/package.json').version")"
git tag "$TAG"
git push && git push --tags
```

The CI workflow (`.github/workflows/publish-sdk.yml`) will:

1. Checkout the tag
2. Install dependencies (`npm ci`)
3. Build (`npm run build` — produces `dist/index.{js,cjs,d.ts}`)
4. Run `scripts/verify-build.mjs` (exports + structure checks)
5. Run `npm pack --dry-run` (logs tarball contents)
6. Publish with **npm provenance** (`npm publish --access public --provenance`)
7. Wait for registry propagation and verify the version is live

## Provenance

Published packages carry a verifiable build attestation: consumers see a
"Built and signed on GitHub Actions" badge on the package page and can
verify the supply chain with:

```bash
npm audit signatures
```

## Token rotation

The npm token expires every 90 days. Set a calendar reminder.

When rotating:
1. Repeat steps 2 + 3 above with a new token
2. Old token is automatically invalidated when the new one with the same
   name is created, or revoke explicitly at npm settings → tokens

## Yank a published version

If a published version is broken, deprecate (preferred) rather than unpublish:

```bash
npm deprecate "@privacyshield/sdk@1.1.2" "Broken — use 1.1.3"
```

Unpublish is only allowed within 72 hours of publish and breaks all consumers:

```bash
npm unpublish "@privacyshield/sdk@1.1.2"
```

## Manual emergency publish

If CI is unavailable, publish from local:

```bash
cd sdks/js
npm run build
node scripts/verify-build.mjs
NPM_TOKEN="npm_xxx" bash -c 'echo "//registry.npmjs.org/:_authToken=${NPM_TOKEN}" > .npmrc.publish && npm publish --access public --userconfig .npmrc.publish && rm -f .npmrc.publish'
```

Manual publishes lack provenance attestation. Prefer CI.
