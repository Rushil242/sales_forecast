/**
 * The connect gallery.
 *
 * Two things this page refuses to do, both deliberate and both worth pointing at
 * during a review:
 *
 * 1. **No logo produces data it did not fetch.** Shopify and Zoho are real OAuth
 *    integrations. Every other tile says plainly that the route is a CSV export
 *    and gives the exact menu path in that product. There is no tile that looks
 *    connectable but quietly returns invented orders.
 *
 * 2. **Missing setup is stated, not discovered on click.** A provider we have
 *    built but whose API keys are absent shows which environment variables are
 *    missing, before the user commits to anything.
 */

import { useCallback, useEffect, useState } from 'react'

import { Reveal } from '../components/motion'
import { Callout, EmptyState, Icon, Spinner } from '../components/ui'
import { api } from '../lib/api'
import { longDate, num } from '../lib/format'

const STATE_BADGE = {
  connected: { label: 'Connected', className: 'bg-emerald-50 text-emerald-700 ring-1 ring-emerald-200' },
  ready: { label: 'Ready to connect', className: 'bg-brand-50 text-brand-700 ring-1 ring-brand-200' },
  needs_credentials: { label: 'Needs API keys', className: 'bg-amber-50 text-amber-700 ring-1 ring-amber-200' },
  csv: { label: 'CSV export', className: 'bg-slate-100 text-slate-600 ring-1 ring-slate-200' },
}

const CATEGORY_LABEL = {
  ecommerce: 'Online stores',
  accounting: 'Billing and accounting',
  payments: 'Payments',
  marketplace: 'Marketplaces',
  file: 'Files',
}

const REGION_LABEL = { india: 'India', uk: 'UK', global: 'Global' }

function Mark({ provider }) {
  return (
    <span
      className="shrink-0 w-11 h-11 rounded-xl flex items-center justify-center
                 text-white font-bold font-display text-sm"
      style={{ backgroundColor: provider.accent }}
    >
      {provider.mark}
    </span>
  )
}

function AccountRow({ account, provider, onSync, onDisconnect, busy }) {
  const synced = account.last_sync_rows > 0
  return (
    <div className="rounded-lg border border-slate-200 bg-slate-50/60 p-3.5 mt-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="min-w-0">
          <p className="text-sm font-semibold text-slate-800 truncate">{account.label}</p>
          <p className="text-xs text-slate-500 mt-0.5">
            {synced ? (
              <>
                {num(account.last_sync_rows)} line items · {account.last_sync_products} products
                {account.last_sync_first_date && (
                  <> · {longDate(account.last_sync_first_date)} to {longDate(account.last_sync_last_date)}</>
                )}
              </>
            ) : (
              'Connected, but no data pulled yet. Press Sync.'
            )}
          </p>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <button
            className="btn-primary py-1.5 px-3 text-xs inline-flex items-center gap-1.5"
            onClick={() => onSync(account)}
            disabled={busy}
          >
            {busy ? <Spinner className="w-3 h-3" /> : <Icon.Activity className="w-3 h-3" />}
            {synced ? 'Re-sync' : 'Sync'}
          </button>
          <button
            className="btn-secondary py-1.5 px-3 text-xs"
            onClick={() => onDisconnect(account)}
            disabled={busy}
          >
            Remove
          </button>
        </div>
      </div>

      {account.last_sync_error && (
        <p className="text-xs text-rose-700 mt-2 leading-relaxed">{account.last_sync_error}</p>
      )}
      {synced && (
        <p className="text-xs text-slate-500 mt-2 leading-relaxed">
          Available on the dashboard as a dataset — pick{' '}
          <span className="font-medium text-slate-700">{account.label}</span> there and
          forecast it exactly like any other.
        </p>
      )}
    </div>
  )
}

function ProviderCard({ provider, onConnect, onSync, onDisconnect, busyId, connecting }) {
  const [shop, setShop] = useState('')
  const [showRoute, setShowRoute] = useState(false)
  const badge = STATE_BADGE[provider.state] ?? STATE_BADGE.csv
  const isLive = provider.integration === 'live'

  return (
    <div className="card card-interactive p-5 flex flex-col">
      <div className="flex items-start gap-3.5">
        <Mark provider={provider} />
        <div className="min-w-0 flex-1">
          <div className="flex items-start justify-between gap-2">
            <h3 className="font-semibold text-slate-900 font-display leading-tight">
              {provider.name}
            </h3>
            <span className={`badge shrink-0 ${badge.className}`}>{badge.label}</span>
          </div>
          <p className="text-[11px] text-slate-400 mt-0.5 uppercase tracking-wide">
            {CATEGORY_LABEL[provider.category] ?? provider.category}
            {' · '}{REGION_LABEL[provider.region] ?? provider.region}
          </p>
        </div>
      </div>

      <p className="text-sm text-slate-600 mt-3 leading-relaxed flex-1">{provider.summary}</p>

      {isLive && provider.pulls.length > 0 && (
        <ul className="mt-3 space-y-1">
          {provider.pulls.map((item) => (
            <li key={item} className="flex gap-2 text-xs text-slate-500">
              <Icon.Check className="w-3 h-3 mt-0.5 shrink-0 text-emerald-500" />
              {item}
            </li>
          ))}
        </ul>
      )}

      {/* ── live: the real connect flow ─────────────────────────────── */}
      {isLive && provider.state === 'ready' && (
        <div className="mt-4">
          {provider.key === 'shopify' && (
            <input
              className="form-input mb-2"
              placeholder="your-store  (or your-store.myshopify.com)"
              value={shop}
              onChange={(e) => setShop(e.target.value)}
            />
          )}
          <button
            className="btn-primary w-full inline-flex items-center justify-center gap-2"
            onClick={() => onConnect(provider, shop)}
            disabled={connecting || (provider.key === 'shopify' && !shop.trim())}
          >
            {connecting ? <Spinner className="w-4 h-4" /> : <Icon.Plug className="w-4 h-4" />}
            Connect {provider.name.split(' ')[0]}
          </button>
          <p className="text-[11px] text-slate-400 mt-1.5 leading-relaxed">
            Opens {provider.name.split(' ')[0]}'s own sign-in and permission screen. RetailIQ
            never sees your password.
          </p>
        </div>
      )}

      {isLive && provider.state === 'needs_credentials' && (
        <div className="mt-4 rounded-lg bg-amber-50 border border-amber-200 px-3.5 py-3">
          <p className="text-xs text-amber-900 leading-relaxed">
            This integration is built, but the app credentials are not configured. Set{' '}
            {provider.missing_credentials.map((key, i) => (
              <span key={key}>
                {i > 0 && ' and '}
                <code className="font-mono text-[11px] bg-amber-100 px-1 rounded">{key}</code>
              </span>
            ))}{' '}
            in <code className="font-mono text-[11px] bg-amber-100 px-1 rounded">.env</code> and
            restart the API.
          </p>
          {provider.redirect_uri && (
            <p className="text-[11px] text-amber-800 mt-2 leading-relaxed break-all">
              Register this redirect URL in the app:{' '}
              <code className="font-mono">{provider.redirect_uri}</code>
            </p>
          )}
        </div>
      )}

      {/* ── connected accounts ───────────────────────────────────────── */}
      {provider.accounts.map((account) => (
        <AccountRow
          key={account.id}
          account={account}
          provider={provider}
          onSync={onSync}
          onDisconnect={onDisconnect}
          busy={busyId === account.id}
        />
      ))}

      {isLive && provider.state === 'connected' && (
        <button
          className="btn-secondary w-full mt-3 text-xs py-1.5"
          onClick={() => onConnect(provider, shop)}
        >
          Connect another {provider.name.split(' ')[0]} account
        </button>
      )}

      {/* ── csv route ────────────────────────────────────────────────── */}
      {!isLive && (
        <div className="mt-4">
          <button
            className="btn-secondary w-full text-sm inline-flex items-center justify-center gap-2"
            onClick={() => setShowRoute((v) => !v)}
          >
            <Icon.Upload className="w-4 h-4" />
            {showRoute ? 'Hide export steps' : 'How to export'}
          </button>
          {showRoute && (
            <p className="text-xs text-slate-600 mt-2.5 leading-relaxed bg-slate-50 rounded-lg p-3 border border-slate-200">
              {provider.csv_route}
              <span className="block mt-2 text-slate-500">
                Then upload the file on the dashboard. Column names are matched
                automatically, so most exports load unchanged.
              </span>
            </p>
          )}
        </div>
      )}
    </div>
  )
}

export default function Connect({ onBack, banner, onDismissBanner, onDataChanged }) {
  const [gallery, setGallery] = useState(null)
  const [error, setError] = useState(null)
  const [busyId, setBusyId] = useState(null)
  const [connecting, setConnecting] = useState(false)
  const [syncResult, setSyncResult] = useState(null)

  const load = useCallback(() => {
    api.dataConnectors().then(setGallery).catch(setError)
  }, [])

  useEffect(load, [load])

  const handleConnect = async (provider, shop) => {
    setConnecting(true)
    setError(null)
    try {
      const { authorize_url: url } = await api.connectStart(provider.key, shop)
      // A full navigation, not a popup: the merchant must see the platform's own
      // domain in the address bar when they approve the scopes.
      window.location.href = url
    } catch (err) {
      setError(err)
      setConnecting(false)
    }
  }

  const handleSync = async (account) => {
    setBusyId(account.id)
    setError(null)
    setSyncResult(null)
    try {
      const result = await api.syncConnector(account.id)
      setSyncResult(result)
      load()
      onDataChanged?.()
    } catch (err) {
      setError(err)
      load()
    } finally {
      setBusyId(null)
    }
  }

  const handleDisconnect = async (account) => {
    setBusyId(account.id)
    try {
      await api.disconnectConnector(account.id)
      load()
      onDataChanged?.()
    } catch (err) {
      setError(err)
    } finally {
      setBusyId(null)
    }
  }

  const providers = gallery?.providers ?? []
  const live = providers.filter((p) => p.integration === 'live')
  const rest = providers.filter((p) => p.integration !== 'live')

  return (
    <div className="max-w-[1440px] mx-auto px-5 lg:px-8 py-8 space-y-7">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div className="animate-fade-up">
          <button onClick={onBack} className="btn-ghost -ml-3 mb-1.5 text-sm">
            <Icon.Back className="w-4 h-4" /> Dashboard
          </button>
          <span className="eyebrow text-brand-600 block">Integrations</span>
          <h1 className="page-title text-3xl sm:text-[2.1rem] mt-1.5 leading-[1.1]">
            Connect your data
          </h1>
          <p className="text-[15px] text-slate-500 mt-2.5 max-w-2xl leading-relaxed text-balance">
            Pull order history straight out of the tools you already run. Shopify and Zoho
            connect over OAuth — you approve on their screen, and we never see your password.
          </p>
        </div>
      </header>

      {banner?.kind === 'success' && (
        <Callout tone="blue" title="Connected" icon={Icon.Check}>
          <p>
            {banner.provider} is connected. Press <strong>Sync</strong> below to pull the
            order history, then forecast it from the dashboard.
          </p>
          <button className="text-xs underline mt-1" onClick={onDismissBanner}>Dismiss</button>
        </Callout>
      )}
      {banner?.kind === 'error' && (
        <Callout tone="rose" title="That connection did not complete">
          <p>{banner.reason}</p>
          <button className="text-xs underline mt-1" onClick={onDismissBanner}>Dismiss</button>
        </Callout>
      )}

      {error && (
        <Callout tone="rose" title="Something went wrong">
          <p>{error.message}</p>
        </Callout>
      )}

      {syncResult && (
        <Callout
          tone={syncResult.rows ? 'blue' : 'amber'}
          title={syncResult.rows ? 'Sync complete' : 'Nothing to import'}
          icon={syncResult.rows ? Icon.Check : Icon.Warning}
        >
          {syncResult.rows > 0 && (
            <p>
              Pulled {num(syncResult.rows)} line items from {num(syncResult.orders)} orders
              across {syncResult.products} products
              {syncResult.span_days ? ` and ${syncResult.span_days} days` : ''}. It is now
              selectable as a dataset on the dashboard.
            </p>
          )}
          {syncResult.warnings?.map((warning) => (
            <p key={warning} className="text-xs mt-1">{warning}</p>
          ))}
        </Callout>
      )}

      {gallery?.token_storage === 'ephemeral' && (
        <Callout tone="amber" title="Connections will not survive a restart">
          <p>{gallery.token_storage_note}</p>
        </Callout>
      )}

      {!gallery && !error && (
        <div className="grid md:grid-cols-2 xl:grid-cols-3 gap-4">
          {[0, 1, 2].map((i) => <div key={i} className="card h-56 skeleton" />)}
        </div>
      )}

      {live.length > 0 && (
        <section>
          <h2 className="section-title mb-1">Direct connections</h2>
          <p className="text-sm text-slate-500 mb-4 max-w-3xl leading-relaxed">
            These two publish a public OAuth app, which is what makes a genuine one-click
            connection possible. Between them they cover the platform most online stores
            run on and the accounting suite most Indian small retailers run on.
          </p>
          <Reveal stagger className="grid md:grid-cols-2 xl:grid-cols-3 gap-4">
            {live.map((provider) => (
              <ProviderCard
                key={provider.key}
                provider={provider}
                onConnect={handleConnect}
                onSync={handleSync}
                onDisconnect={handleDisconnect}
                busyId={busyId}
                connecting={connecting}
              />
            ))}
          </Reveal>
        </section>
      )}

      {rest.length > 0 && (
        <section>
          <h2 className="section-title mb-1">Export and upload</h2>
          <p className="text-sm text-slate-500 mb-4 max-w-3xl leading-relaxed">
            These platforms have no public OAuth app we could honestly connect to — Tally runs
            entirely on your own machine, WooCommerce issues keys per store, and Amazon
            requires an approved developer profile. Each card gives the real export path
            instead of a button that would not work.
          </p>
          <Reveal stagger className="grid md:grid-cols-2 xl:grid-cols-3 gap-4">
            {rest.map((provider) => (
              <ProviderCard
                key={provider.key}
                provider={provider}
                onConnect={handleConnect}
                onSync={handleSync}
                onDisconnect={handleDisconnect}
                busyId={busyId}
                connecting={connecting}
              />
            ))}
          </Reveal>
        </section>
      )}

      {gallery && providers.length === 0 && (
        <EmptyState icon={Icon.Plug} title="No providers registered">
          The connector registry is empty, which should not happen.
        </EmptyState>
      )}
    </div>
  )
}
