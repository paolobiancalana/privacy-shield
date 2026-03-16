# Platform Layer — UI Specification

> Every page, component, and interaction defined for implementation.

## Design System

| Property | Value |
|----------|-------|
| Primary color | #3b82f6 (blue-500) |
| Background | #0a0a0a (dark) |
| Surface | #1a1a2e |
| Border | #333333 |
| Text primary | #e0e0e0 |
| Text secondary | #888888 |
| Success | #22c55e (green-500) |
| Warning | #f59e0b (amber-500) |
| Error | #ef4444 (red-500) |
| Font | Inter (system fallback: -apple-system, sans-serif) |
| Border radius | 0.5rem (buttons), 0.75rem (cards) |
| Dark mode | Default and only mode |

## Pages

### 1. Landing Page (/)

```
┌─────────────────────────────────────────────┐
│  🛡️ Privacy Shield          [Login] [Signup]│
├─────────────────────────────────────────────┤
│                                             │
│    PII Detection API                        │
│    for Italian Business Documents           │
│                                             │
│    [Get Started Free]  [View Docs]          │
│                                             │
├─────────────────────────────────────────────┤
│  ┌─────────┐ ┌─────────┐ ┌─────────┐      │
│  │ 10 PII  │ │ <80ms   │ │ mTLS    │      │
│  │ Types   │ │ Latency │ │ Secured │      │
│  └─────────┘ └─────────┘ └─────────┘      │
├─────────────────────────────────────────────┤
│  How it works:                              │
│  1. Send text → 2. PII detected →          │
│  3. Tokens replace PII → 4. Rehydrate      │
├─────────────────────────────────────────────┤
│  Code example (curl):                       │
│  ┌─────────────────────────────────┐        │
│  │ curl -X POST .../tokenize ...   │        │
│  └─────────────────────────────────┘        │
├─────────────────────────────────────────────┤
│  Pricing    →  /pricing                     │
│  © 2026 Privacy Shield                      │
└─────────────────────────────────────────────┘
```

### 2. Pricing Page (/pricing)

```
┌─────────────────────────────────────────────────────────┐
│  Choose your plan                                        │
│                                                          │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐  │
│  │   Free   │ │Developer │ │ Business │ │Enterprise│  │
│  │   €0/mo  │ │ €19/mo   │ │  €79/mo  │ │ Custom   │  │
│  │          │ │          │ │          │ │          │  │
│  │ 10/min   │ │ 60/min   │ │ 200/min  │ │ 1000/min │  │
│  │ 1K tok   │ │ 50K tok  │ │ 500K tok │ │ 5M tok   │  │
│  │ 2 keys   │ │ 5 keys   │ │ 20 keys  │ │ 100 keys │  │
│  │          │ │          │ │ ★ Popular│ │          │  │
│  │[Start]   │ │ [Start]  │ │ [Start]  │ │[Contact] │  │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘  │
│                                                          │
│  Feature comparison table below                          │
└─────────────────────────────────────────────────────────┘
```

### 3. Signup (/signup)

```
┌─────────────────────────────────────┐
│       Create your account           │
│                                     │
│  [G] Continue with Google           │
│  [GH] Continue with GitHub          │
│                                     │
│  ─── or ───                         │
│                                     │
│  Email    [_________________]       │
│  Password [_________________]       │
│                                     │
│  [Create Account]                   │
│                                     │
│  Already have an account? Login     │
└─────────────────────────────────────┘
```

On signup success:
1. Supabase creates user
2. Trigger (database function or API): create personal org
3. Redirect to /dashboard

### 4. Login (/login)

Same layout as signup, with "Forgot password?" link.

### 5. Dashboard Layout

```
┌─────────────────────────────────────────────────────────┐
│  🛡️ PS   [Org: Materic.ai ▼]              [👤 Paolo ▼]│
├──────────┬──────────────────────────────────────────────┤
│          │                                              │
│ Usage    │   Main content area                          │
│ API Keys │                                              │
│ Settings │                                              │
│ Billing  │                                              │
│          │                                              │
│ ──────── │                                              │
│ Docs ↗   │                                              │
│          │                                              │
└──────────┴──────────────────────────────────────────────┘
```

### 6. Usage Page (/dashboard/usage)

```
┌──────────────────────────────────────────────┐
│  Usage                          [7d|30d|90d] │
│                                              │
│  ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐       │
│  │12,345│ │5,678 │ │ 1.1% │ │ 72ms │       │
│  │calls │ │tokens│ │ used │ │ avg  │       │
│  └──────┘ └──────┘ └──────┘ └──────┘       │
│                                              │
│  ┌──────────────────────────────────────┐   │
│  │  📈 Line chart: daily calls          │   │
│  │  (x: date, y: tokenize_calls)       │   │
│  └──────────────────────────────────────┘   │
│                                              │
│  ┌──────────────────────────────────────┐   │
│  │  📊 Bar chart: tokens created/day    │   │
│  └──────────────────────────────────────┘   │
│                                              │
│  Daily breakdown (table):                    │
│  Date        Calls   Tokens  Latency        │
│  2026-03-15  456     1234    68ms           │
│  2026-03-14  389     1098    71ms           │
│  ...                                         │
└──────────────────────────────────────────────┘
```

Chart library: **recharts** (lightweight, React-native, SSR compatible).

### 7. API Keys Page (/dashboard/keys)

```
┌──────────────────────────────────────────────┐
│  API Keys                     [+ Create Key] │
│                                              │
│  ┌──────────────────────────────────────┐   │
│  │ ps_live_...ef01                       │   │
│  │ Label: production-server              │   │
│  │ Created: Mar 15, 2026                 │   │
│  │ Last used: 2 hours ago                │   │
│  │ Environment: live 🟢                  │   │
│  │                          [Revoke] 🔴  │   │
│  └──────────────────────────────────────┘   │
│                                              │
│  ┌──────────────────────────────────────┐   │
│  │ ps_test_...ab12                       │   │
│  │ Label: development                    │   │
│  │ Created: Mar 14, 2026                 │   │
│  │ Environment: test 🟡                  │   │
│  │                          [Revoke] 🔴  │   │
│  └──────────────────────────────────────┘   │
└──────────────────────────────────────────────┘
```

Create Key Dialog:
```
┌──────────────────────────────────┐
│  Create API Key                  │
│                                  │
│  Label [________________]        │
│  Environment [live ▼]            │
│                                  │
│  [Cancel]         [Create]       │
└──────────────────────────────────┘
```

After creation:
```
┌──────────────────────────────────┐
│  ✅ API Key Created              │
│                                  │
│  ┌────────────────────────────┐  │
│  │ ps_live_a1b2c3d4e5f678... │  │
│  │                    [Copy]  │  │
│  └────────────────────────────┘  │
│                                  │
│  ⚠️ Copy this key now.          │
│  It will not be shown again.     │
│                                  │
│  [Done]                          │
└──────────────────────────────────┘
```

### 8. Settings (/dashboard/settings)

```
┌──────────────────────────────────────────────┐
│  Organization Settings                       │
│                                              │
│  Name:  [Materic.ai_______]                  │
│  Slug:  [materic___________] .privacyshield  │
│  [Save Changes]                              │
│                                              │
│  ─────────────────────────────               │
│  Team Members                    [+ Invite]  │
│                                              │
│  paolo@materic.ai    Owner                   │
│  dev@materic.ai      Admin    [Remove]       │
│                                              │
│  ─────────────────────────────               │
│  Danger Zone                                 │
│  [Delete Organization] (red, confirmation)   │
└──────────────────────────────────────────────┘
```

### 9. Billing (/dashboard/billing)

```
┌──────────────────────────────────────────────┐
│  Billing                                     │
│                                              │
│  Current Plan: Business (€79/mo)  [Upgrade]  │
│                                              │
│  Usage this month:                           │
│  ████████░░░░░░░░  45,678 / 500,000 tokens  │
│                    (9.1%)                     │
│                                              │
│  ─────────────────────────────               │
│  Invoice History                             │
│                                              │
│  Mar 2026  €79.00  Paid  [PDF]              │
│  Feb 2026  €79.00  Paid  [PDF]              │
│  Jan 2026  €19.00  Paid  [PDF]              │
└──────────────────────────────────────────────┘
```

## Component Library

Use shadcn/ui components. Install only what's needed:

```bash
npx shadcn@latest add button card dialog input label
npx shadcn@latest add table tabs badge separator
npx shadcn@latest add dropdown-menu avatar toast
npx shadcn@latest add alert-dialog progress
```

## Responsive Breakpoints

| Breakpoint | Layout |
|-----------|--------|
| < 768px | Sidebar collapses to hamburger menu |
| 768-1024px | Sidebar visible, content compressed |
| > 1024px | Full layout |

## Interaction States

Every interactive element must have:
- Hover state (opacity or background change)
- Loading state (spinner or skeleton)
- Disabled state (reduced opacity)
- Error state (red border + error message below)
- Success state (green checkmark, brief toast notification)

## Toasts

Use sonner (via shadcn/ui). Position: bottom-right.
- Success: green left border
- Error: red left border
- Duration: 4 seconds
