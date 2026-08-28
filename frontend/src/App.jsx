import React, { useState, useEffect } from 'react'
import { Transition } from './components/motion'
import { Icon } from './components/ui'
import { api } from './lib/api'
import Connect from './pages/Connect'
import Dashboard from './pages/Dashboard'
import Landing from './pages/Landing'
import SocialIntelligence from './pages/SocialIntelligence'

function WorkspaceApp() {
  const [page, setPage] = useState('dashboard')
  const [productName, setProductName] = useState('')
  const [dataVersion, setDataVersion] = useState(0)
  const [health, setHealth] = useState(null)
  const [datasets, setDatasets] = useState([])
  const [banner, setBanner] = useState(null)
  
  const [isSidebarOpen, setIsSidebarOpen] = useState(true)
  const [isMobileMenuOpen, setIsMobileMenuOpen] = useState(false)

  useEffect(() => {
    let mounted = true

    api.ready()
      .then(res => mounted && setHealth(res))
      .catch(err => console.error('Health check failed', err))

    api.listDatasets()
      .then(res => mounted && setDatasets(res))
      .catch(err => console.error('Failed to list datasets', err))

    const urlParams = new URLSearchParams(window.location.search)
    const connectOutcome = urlParams.get('connect')
    if (connectOutcome) {
      if (connectOutcome === 'success') {
        setBanner({ type: 'success', message: 'Data source connected successfully.' })
      } else if (connectOutcome === 'error') {
        setBanner({ type: 'error', message: 'Failed to connect data source.' })
      }
      setPage('connect')
      window.history.replaceState({}, '', window.location.pathname)
    }

    return () => { mounted = false }
  }, [])

  useEffect(() => {
    window.scrollTo(0, 0)
    setIsMobileMenuOpen(false)
  }, [page])

  const handleDataChanged = () => {
    setDataVersion(v => v + 1)
  }

  const openSocial = () => setPage('social')

  const navGroups = [
    {
      label: 'Analyse',
      items: [
        { id: 'dashboard', label: 'Forecast', icon: 'Chart', pageId: 'dashboard' },
        { id: 'social', label: 'Social signal', icon: 'Share', pageId: 'social' }
      ]
    },
    {
      label: 'Data',
      items: [
        { id: 'connect', label: 'Data sources', icon: 'Plug', pageId: 'connect' },
        { id: 'datasets', label: 'Datasets', icon: 'Database', pageId: 'connect', disabled: false }
      ]
    },
    {
      label: 'Account',
      items: [
        { id: 'settings', label: 'Settings', icon: 'Shield', disabled: true },
        { id: 'help', label: 'Help', icon: 'Info', disabled: true }
      ]
    }
  ]

  const Sidebar = ({ isMobile = false }) => {
    const expanded = isMobile || isSidebarOpen
    return (
      <div className={`flex flex-col h-full bg-surface-50 border-r border-ink-200 transition-all duration-300 ease-out-expo ${expanded ? 'w-64' : 'w-20'}`}>
        <div className="flex items-center h-14 px-4 border-b border-ink-200 shrink-0">
          <div className="flex items-center gap-3 w-full overflow-hidden">
            <div className="flex items-center justify-center w-8 h-8 rounded-lg bg-brand-500 text-surface-0 shrink-0 shadow-glow">
              <Icon.Sparkles className="w-5 h-5" />
            </div>
            {expanded && (
              <span className="font-semibold text-ink-900 tracking-tight whitespace-nowrap">RetailIQ</span>
            )}
          </div>
        </div>

        <div className="flex-1 overflow-y-auto py-6 no-scrollbar">
          {navGroups.map((group, idx) => (
            <div key={idx} className="mb-6">
              {expanded && (
                <div className="px-5 mb-2">
                  <span className="eyebrow text-ink-500 uppercase tracking-wider text-[10px] font-bold">{group.label}</span>
                </div>
              )}
              <nav className="flex flex-col space-y-1 px-3">
                {group.items.map(item => {
                  const isActive = page === item.pageId && !item.disabled
                  const CurrentIcon = Icon[item.icon] || Icon.Box
                  
                  return (
                    <button
                      key={item.id}
                      onClick={() => !item.disabled && item.pageId && setPage(item.pageId)}
                      disabled={item.disabled}
                      title={!expanded ? item.label : undefined}
                      className={`
                        relative flex items-center h-9 px-2 rounded-md transition-colors duration-200 group
                        ${isActive ? 'bg-brand-50/80 text-brand-700' : 'text-ink-600 hover:bg-surface-200/50 hover:text-ink-900'}
                        ${item.disabled ? 'opacity-50 cursor-not-allowed hover:bg-transparent' : 'cursor-pointer'}
                      `}
                    >
                      {isActive && (
                        <div className="absolute left-0 top-1.5 bottom-1.5 w-1 bg-brand-500 rounded-r-full" />
                      )}
                      <div className="flex items-center justify-center w-8 shrink-0">
                        <CurrentIcon className={`w-4 h-4 ${isActive ? 'text-brand-600' : 'text-ink-500 group-hover:text-ink-700'}`} />
                      </div>
                      {expanded && (
                        <div className="flex items-center justify-between flex-1 ml-2 overflow-hidden">
                          <span className="text-sm font-medium whitespace-nowrap truncate">{item.label}</span>
                          {item.disabled && (
                            <span className="badge text-[10px] py-0.5 px-1.5 shrink-0 bg-surface-100 text-ink-500 border border-ink-200">Soon</span>
                          )}
                        </div>
                      )}
                    </button>
                  )
                })}
              </nav>
            </div>
          ))}
        </div>

        <div className="p-4 border-t border-ink-200 shrink-0">
          <div className={`p-3 rounded-xl bg-surface-0 border border-ink-200 shadow-sm transition-all overflow-hidden ${expanded ? '' : 'flex justify-center items-center p-2'}`}>
            {expanded ? (
              <div className="flex flex-col gap-2.5">
                <div className="flex items-center justify-between">
                  <span className="text-xs font-semibold text-ink-700 uppercase tracking-wide">System Status</span>
                  <div className={`w-2 h-2 rounded-full ${health?.status === 'ok' ? 'bg-green-500 shadow-[0_0_8px_rgba(34,197,94,0.4)]' : 'bg-yellow-500'}`} />
                </div>
                <div className="flex flex-col gap-1.5">
                  <div className="flex items-center gap-2 text-xs text-ink-600">
                    <Icon.Layers className="w-3.5 h-3.5 text-ink-400" />
                    <span className="truncate">{health?.forecasting?.chronos2?.model || 'Loading model...'}</span>
                  </div>
                  <div className="flex items-center gap-2 text-xs text-ink-600">
                    <Icon.Bolt className="w-3.5 h-3.5 text-ink-400" />
                    <span className="truncate">{health?.forecasting?.device || 'Initializing device...'}</span>
                  </div>
                </div>
              </div>
            ) : (
               <div title={health?.status === 'ok' ? 'System OK' : 'Degraded'} className={`w-2.5 h-2.5 rounded-full ${health?.status === 'ok' ? 'bg-green-500' : 'bg-yellow-500'}`} />
            )}
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="flex h-screen w-full bg-surface-100/30 overflow-hidden font-sans text-ink-900">
      
      <div className="hidden md:block shrink-0 z-20 shadow-card bg-surface-0">
        <Sidebar />
      </div>

      <Transition
        show={isMobileMenuOpen}
        enter="transition-opacity duration-300"
        enterFrom="opacity-0"
        enterTo="opacity-100"
        leave="transition-opacity duration-300"
        leaveFrom="opacity-100"
        leaveTo="opacity-0"
      >
        <div className="fixed inset-0 z-40 md:hidden">
          <div className="absolute inset-0 bg-ink-900/30 backdrop-blur-sm" onClick={() => setIsMobileMenuOpen(false)} />
          <div className="absolute inset-y-0 left-0 shadow-card-md">
             <Sidebar isMobile={true} />
          </div>
        </div>
      </Transition>

      <div className="flex flex-col flex-1 min-w-0 h-full relative">
        
        <header className="sticky top-0 z-10 flex items-center justify-between h-14 px-4 md:px-6 border-b border-ink-200/60 bg-surface-0/70 backdrop-blur-md">
          <div className="flex items-center gap-4 flex-1">
            <button 
              className="md:hidden p-1.5 -ml-1.5 text-ink-500 hover:text-ink-900 hover:bg-surface-100 rounded-md transition-colors"
              onClick={() => setIsMobileMenuOpen(true)}
            >
              <Icon.Layers className="w-5 h-5" />
            </button>
            <button 
              className="hidden md:flex p-1.5 -ml-1.5 text-ink-400 hover:text-ink-700 hover:bg-surface-100 rounded-md transition-colors"
              onClick={() => setIsSidebarOpen(!isSidebarOpen)}
            >
              <Icon.Layers className="w-5 h-5" />
            </button>

            <div className="max-w-sm w-full relative hidden sm:block">
              <div className="absolute inset-y-0 left-3 flex items-center pointer-events-none">
                <Icon.Search className="w-4 h-4 text-ink-400" />
              </div>
              <input 
                type="text" 
                placeholder="Search forecasts, insights, datasets..." 
                className="w-full h-8 pl-9 pr-12 bg-surface-50 border border-ink-200 rounded-md text-sm text-ink-900 placeholder-ink-400 focus:outline-none focus:ring-2 focus:ring-brand-500/20 focus:border-brand-500 transition-shadow shadow-sm"
              />
              <div className="absolute inset-y-0 right-2 flex items-center pointer-events-none">
                <span className="text-[10px] font-medium text-ink-400 bg-surface-100 px-1.5 py-0.5 rounded border border-ink-200 shadow-sm">⌘K</span>
              </div>
            </div>
          </div>

          <div className="flex items-center gap-4 shrink-0">
            {health && (
              <div className="hidden sm:flex items-center gap-2.5 px-3 py-1.5 rounded-full bg-surface-50 border border-ink-200 shadow-sm">
                 <div className={`w-2 h-2 rounded-full ${health.status === 'ok' ? 'bg-green-500 shadow-[0_0_8px_rgba(34,197,94,0.4)]' : 'bg-yellow-500'}`} />
                 <span className="text-xs font-medium text-ink-700 capitalize">{health.status}</span>
              </div>
            )}
            <button className="flex items-center justify-center w-8 h-8 rounded-full bg-brand-100 border border-brand-200 text-brand-700 font-bold text-sm hover:shadow-md hover:ring-2 hover:ring-brand-500/30 transition-all ring-offset-1">
              R
            </button>
          </div>
        </header>

        <main className="flex-1 overflow-y-auto relative no-scrollbar">
           <div className="max-w-7xl mx-auto p-4 md:p-8 min-h-full flex flex-col">
              
              <div className={page === 'dashboard' ? '' : 'hidden'}>
                <Dashboard 
                  onOpenSocial={openSocial} 
                  onOpenConnect={() => setPage('connect')}
                  productName={productName} 
                  setProductName={setProductName}
                  dataVersion={dataVersion} 
                />
              </div>

              {page === 'connect' && (
                <Connect 
                  onBack={() => setPage('dashboard')} 
                  banner={banner}
                  onDismissBanner={() => setBanner(null)} 
                  onDataChanged={handleDataChanged} 
                />
              )}

              {page === 'social' && (
                <SocialIntelligence 
                  query={productName} 
                  onBack={() => setPage('dashboard')}
                  datasets={datasets} 
                />
              )}

           </div>
           
           <footer className="mt-auto px-4 md:px-8 py-5 border-t border-ink-200/50 bg-surface-0/30">
             <div className="max-w-7xl mx-auto flex flex-col sm:flex-row items-center justify-between gap-4 text-xs text-ink-500">
               <div className="flex items-center gap-2 font-medium text-ink-600">
                 <Icon.Sparkles className="w-3.5 h-3.5 text-brand-500" />
                 <span>RetailIQ Demand Engine</span>
               </div>
               <div className="flex items-center gap-5">
                 <a href="#" className="hover:text-ink-900 transition-colors">Privacy</a>
                 <a href="#" className="hover:text-ink-900 transition-colors">Terms</a>
                 <span className="text-ink-400">v2.4.1</span>
               </div>
             </div>
           </footer>
        </main>
      </div>
    </div>
  )
}

/**
 * The public entry surface deliberately lives outside the analytics workspace.
 * Keeping the switch here means Dashboard, Social Intelligence and Connect retain
 * their existing state, layout and API contracts exactly as they are.
 */
export default function App() {
  const [workspaceOpen, setWorkspaceOpen] = useState(() => {
    const params = new URLSearchParams(window.location.search)
    return window.location.hash === '#workspace' || params.has('connect')
  })

  const openWorkspace = () => {
    window.history.replaceState({}, '', `${window.location.pathname}${window.location.search}#workspace`)
    setWorkspaceOpen(true)
  }

  if (!workspaceOpen) return <Landing onOpenWorkspace={openWorkspace} />
  return <WorkspaceApp />
}
